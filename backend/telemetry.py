"""
Citation Telemetry Dashboard API

Provides endpoints for viewing verification metrics by doctrine,
binding failure analysis, and alerting when rates drop below thresholds.
Supports STRICT/RESEARCH mode segmentation for attorney-risk metrics.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
import json
from backend import db_postgres as db

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


FAILURE_REASONS = [
    "QUOTE_NOT_FOUND",
    "WRONG_CASE_ID", 
    "WRONG_PAGE",
    "TOO_SHORT",
    "OCR_ARTIFACT_MISMATCH",
    "ELLIPSIS_FRAGMENT",
    "NORMALIZATION_MISMATCH",
    "NO_CANDIDATE_PASSAGES",
    "OTHER"
]


class DoctrineMetrics(BaseModel):
    doctrine: str
    verification_rate: float
    total_queries: int
    total_citations: int
    verified_citations: int
    unverified_citations: int
    unsupported_rate: float
    case_attributed_unsupported_rate: float
    avg_latency_ms: float
    alert: bool
    alert_reasons: List[str]


class FailureReasonBreakdown(BaseModel):
    reason: str
    count: int
    percentage: float


class LatencyMetrics(BaseModel):
    p50_ms: float
    p95_ms: float
    avg_ms: float


class PropositionMetrics(BaseModel):
    total: int
    case_attributed: int
    unsupported: int
    case_attributed_unsupported: int
    unsupported_rate: float
    case_attributed_unsupported_rate: float


class DashboardSummary(BaseModel):
    mode: str
    overall_verification_rate: float
    overall_unverified_rate: float
    total_queries: int
    total_citations: int
    verified_citations: int
    unverified_citations: int
    latency: LatencyMetrics
    propositions: PropositionMetrics
    by_doctrine: List[DoctrineMetrics]
    failure_reasons: List[FailureReasonBreakdown]
    alerts: List[str]
    period_start: datetime
    period_end: datetime


class DoctrineDrilldown(BaseModel):
    doctrine: str
    failure_reasons: List[FailureReasonBreakdown]
    failing_responses: List[Dict]
    total_failures: int


@router.get("/dashboard")
async def get_dashboard(
    days: int = Query(7, ge=1, le=90),
    mode: Optional[str] = Query(None, pattern="^(STRICT|RESEARCH)$")
):
    """Get telemetry dashboard summary for the last N days, optionally filtered by mode."""
    try:
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        records = db.get_telemetry_records(period_start, period_end, mode)
        
        if not records:
            return DashboardSummary(
                mode=mode or "ALL",
                overall_verification_rate=0.0,
                overall_unverified_rate=0.0,
                total_queries=0,
                total_citations=0,
                verified_citations=0,
                unverified_citations=0,
                latency=LatencyMetrics(p50_ms=0, p95_ms=0, avg_ms=0),
                propositions=PropositionMetrics(
                    total=0, case_attributed=0, unsupported=0,
                    case_attributed_unsupported=0, unsupported_rate=0, case_attributed_unsupported_rate=0
                ),
                by_doctrine=[],
                failure_reasons=[],
                alerts=["No data available for this period"],
                period_start=period_start,
                period_end=period_end,
            )
        
        total_citations = sum(r.get("total_citations", 0) for r in records)
        verified_citations = sum(r.get("verified_citations", 0) for r in records)
        unverified_citations = total_citations - verified_citations
        
        props_total = sum(r.get("propositions_total", 0) for r in records)
        props_case_attributed = sum(r.get("propositions_case_attributed", 0) for r in records)
        props_unsupported = sum(r.get("propositions_unsupported", 0) for r in records)
        props_case_attr_unsupported = sum(r.get("propositions_case_attributed_unsupported", 0) for r in records)
        
        overall_rate = (verified_citations / total_citations * 100) if total_citations > 0 else 0
        overall_unverified_rate = (unverified_citations / total_citations * 100) if total_citations > 0 else 0
        unsupported_rate = (props_unsupported / props_total * 100) if props_total > 0 else 0
        case_attr_unsup_rate = (props_case_attr_unsupported / props_case_attributed * 100) if props_case_attributed > 0 else 0
        
        latency_data = db.get_latency_percentiles(period_start, period_end, mode)
        latencies = [r.get("latency_ms") for r in records if r.get("latency_ms")]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        
        doctrine_data: Dict[str, Dict] = {}
        for r in records:
            doc = r.get("doctrine") or "unknown"
            if doc not in doctrine_data:
                doctrine_data[doc] = {
                    "queries": 0,
                    "total_citations": 0,
                    "verified_citations": 0,
                    "props_total": 0,
                    "props_case_attributed": 0,
                    "props_unsupported": 0,
                    "props_case_attr_unsupported": 0,
                    "latencies": []
                }
            doctrine_data[doc]["queries"] += 1
            doctrine_data[doc]["total_citations"] += r.get("total_citations", 0)
            doctrine_data[doc]["verified_citations"] += r.get("verified_citations", 0)
            doctrine_data[doc]["props_total"] += r.get("propositions_total", 0)
            doctrine_data[doc]["props_case_attributed"] += r.get("propositions_case_attributed", 0)
            doctrine_data[doc]["props_unsupported"] += r.get("propositions_unsupported", 0)
            doctrine_data[doc]["props_case_attr_unsupported"] += r.get("propositions_case_attributed_unsupported", 0)
            if r.get("latency_ms"):
                doctrine_data[doc]["latencies"].append(r.get("latency_ms"))
        
        by_doctrine = []
        alerts = []
        
        p95_threshold_ms = 30000
        
        for doc, data in doctrine_data.items():
            rate = (data["verified_citations"] / data["total_citations"] * 100) if data["total_citations"] > 0 else 0
            unverified = data["total_citations"] - data["verified_citations"]
            unverified_rate = (unverified / data["total_citations"] * 100) if data["total_citations"] > 0 else 0
            unsup_rate = (data["props_unsupported"] / data["props_total"] * 100) if data["props_total"] > 0 else 0
            case_attr_unsup = (data["props_case_attr_unsupported"] / data["props_case_attributed"] * 100) if data["props_case_attributed"] > 0 else 0
            avg_lat = sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else 0
            
            alert_reasons = []
            is_alert = False
            
            if mode == "STRICT" or mode is None:
                if rate < 90:
                    is_alert = True
                    alert_reasons.append(f"Verified rate {rate:.1f}% < 90%")
                if case_attr_unsup > 0.5:
                    is_alert = True
                    alert_reasons.append(f"Case-attributed unsupported {case_attr_unsup:.2f}% > 0.5%")
                if unverified_rate > 10:
                    is_alert = True
                    alert_reasons.append(f"Unverified rate {unverified_rate:.1f}% > 10%")
            
            if is_alert:
                alerts.append(f"⚠️ {doc}: " + "; ".join(alert_reasons))
            
            by_doctrine.append(DoctrineMetrics(
                doctrine=doc,
                verification_rate=rate,
                total_queries=data["queries"],
                total_citations=data["total_citations"],
                verified_citations=data["verified_citations"],
                unverified_citations=unverified,
                unsupported_rate=unsup_rate,
                case_attributed_unsupported_rate=case_attr_unsup,
                avg_latency_ms=avg_lat,
                alert=is_alert,
                alert_reasons=alert_reasons,
            ))
        
        by_doctrine.sort(key=lambda x: x.verification_rate)
        
        failure_breakdown = db.get_failure_reason_breakdown(period_start, period_end, mode)
        total_failures = sum(f.get("count", 0) for f in failure_breakdown)
        failure_reasons = [
            FailureReasonBreakdown(
                reason=f.get("failure_reason") or "UNKNOWN",
                count=f.get("count", 0),
                percentage=(f.get("count", 0) / total_failures * 100) if total_failures > 0 else 0
            )
            for f in failure_breakdown
        ]
        
        if latency_data.get("p95", 0) > p95_threshold_ms:
            alerts.append(f"⚠️ p95 latency {latency_data['p95']/1000:.1f}s exceeds {p95_threshold_ms/1000}s threshold")
        
        return DashboardSummary(
            mode=mode or "ALL",
            overall_verification_rate=overall_rate,
            overall_unverified_rate=overall_unverified_rate,
            total_queries=len(records),
            total_citations=total_citations,
            verified_citations=verified_citations,
            unverified_citations=unverified_citations,
            latency=LatencyMetrics(
                p50_ms=latency_data.get("p50", 0),
                p95_ms=latency_data.get("p95", 0),
                avg_ms=avg_latency
            ),
            propositions=PropositionMetrics(
                total=props_total,
                case_attributed=props_case_attributed,
                unsupported=props_unsupported,
                case_attributed_unsupported=props_case_attr_unsupported,
                unsupported_rate=unsupported_rate,
                case_attributed_unsupported_rate=case_attr_unsup_rate
            ),
            by_doctrine=by_doctrine,
            failure_reasons=failure_reasons,
            alerts=alerts,
            period_start=period_start,
            period_end=period_end,
        )
        
    except Exception as e:
        logging.error(f"Error getting dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drilldown/{doctrine}")
async def get_doctrine_drilldown(
    doctrine: str,
    days: int = Query(7, ge=1, le=90),
    mode: Optional[str] = Query(None, pattern="^(STRICT|RESEARCH)$")
):
    """Get detailed failure analysis for a specific doctrine."""
    try:
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        failing_responses = db.get_failing_responses(doctrine, period_start, period_end, limit=50)
        failure_breakdown = db.get_failure_reason_breakdown(period_start, period_end, mode)
        
        total_failures = sum(f.get("count", 0) for f in failure_breakdown)
        
        return DoctrineDrilldown(
            doctrine=doctrine,
            failure_reasons=[
                FailureReasonBreakdown(
                    reason=f.get("failure_reason") or "UNKNOWN",
                    count=f.get("count", 0),
                    percentage=(f.get("count", 0) / total_failures * 100) if total_failures > 0 else 0
                )
                for f in failure_breakdown
            ],
            failing_responses=[
                {
                    "response_id": r.get("response_id"),
                    "created_at": r.get("created_at").isoformat() if r.get("created_at") else None,
                    "total_citations": r.get("total_citations"),
                    "verified_citations": r.get("verified_citations"),
                }
                for r in failing_responses
            ],
            total_failures=total_failures
        )
    except Exception as e:
        logging.error(f"Error getting drilldown: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def record_telemetry_internal(
    conversation_id: Optional[str] = None,
    doctrine: Optional[str] = None,
    total_citations: int = 0,
    verified_citations: int = 0,
    unsupported_statements: int = 0,
    total_statements: int = 0,
    latency_ms: Optional[int] = None,
    binding_failure_reasons: Optional[List[Dict]] = None,
    mode: str = "STRICT",
    response_id: Optional[str] = None,
    propositions_total: int = 0,
    propositions_case_attributed: int = 0,
    propositions_unsupported: int = 0,
    propositions_case_attributed_unsupported: int = 0,
    citation_results: Optional[List[Dict]] = None
) -> Optional[str]:
    """
    Internal function to record telemetry - called from chat pipeline only.
    Returns the telemetry ID if successful.
    
    citation_results should be a list of dicts with:
    - citation_text: str
    - case_name: str
    - verified: bool
    - failure_reason: str (one of FAILURE_REASONS)
    """
    try:
        telemetry_id = db.insert_telemetry(
            conversation_id=conversation_id,
            doctrine=doctrine,
            total_citations=total_citations,
            verified_citations=verified_citations,
            unsupported_statements=unsupported_statements,
            total_statements=total_statements,
            latency_ms=latency_ms,
            binding_failure_reasons=json.dumps(binding_failure_reasons) if binding_failure_reasons else None,
            mode=mode,
            response_id=response_id,
            propositions_total=propositions_total,
            propositions_case_attributed=propositions_case_attributed,
            propositions_unsupported=propositions_unsupported,
            propositions_case_attributed_unsupported=propositions_case_attributed_unsupported
        )
        
        if citation_results:
            for result in citation_results:
                failure_reason = result.get("failure_reason")
                if failure_reason and failure_reason not in FAILURE_REASONS:
                    failure_reason = "OTHER"
                
                db.insert_citation_verification_result(
                    telemetry_id=telemetry_id,
                    response_id=response_id,
                    citation_text=result.get("citation_text", ""),
                    case_name=result.get("case_name"),
                    verified=result.get("verified", False),
                    failure_reason=failure_reason if not result.get("verified") else None
                )
        
        return telemetry_id
    except Exception as e:
        logging.error(f"Error recording telemetry: {e}")
        return None
