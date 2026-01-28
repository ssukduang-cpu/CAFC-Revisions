"""
Citation Telemetry Dashboard API

Provides endpoints for viewing verification metrics by doctrine,
binding failure analysis, and alerting when rates drop below thresholds.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
from backend import db_postgres as db

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class TelemetryRecord(BaseModel):
    doctrine: Optional[str]
    total_citations: int
    verified_citations: int
    unsupported_statements: int
    total_statements: int
    latency_ms: Optional[int]
    created_at: datetime


class DoctrineMetrics(BaseModel):
    doctrine: str
    verification_rate: float
    total_queries: int
    total_citations: int
    verified_citations: int
    unsupported_rate: float
    avg_latency_ms: float
    alert: bool  # True if rate < 80%


class BindingFailureReason(BaseModel):
    reason: str
    count: int
    percentage: float
    examples: List[str]


class DashboardSummary(BaseModel):
    overall_verification_rate: float
    total_queries: int
    total_citations: int
    verified_citations: int
    unsupported_statements_rate: float
    median_latency_ms: float
    by_doctrine: List[DoctrineMetrics]
    top_binding_failures: List[BindingFailureReason]
    alerts: List[str]
    period_start: datetime
    period_end: datetime


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(days: int = 7):
    """Get telemetry dashboard summary for the last N days."""
    try:
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        # Get all telemetry records for the period
        records = db.get_telemetry_records(period_start, period_end)
        
        if not records:
            return DashboardSummary(
                overall_verification_rate=0.0,
                total_queries=0,
                total_citations=0,
                verified_citations=0,
                unsupported_statements_rate=0.0,
                median_latency_ms=0.0,
                by_doctrine=[],
                top_binding_failures=[],
                alerts=["No data available for this period"],
                period_start=period_start,
                period_end=period_end,
            )
        
        # Calculate overall metrics
        total_citations = sum(r.get("total_citations", 0) for r in records)
        verified_citations = sum(r.get("verified_citations", 0) for r in records)
        total_unsupported = sum(r.get("unsupported_statements", 0) for r in records)
        total_statements = sum(r.get("total_statements", 0) for r in records)
        
        overall_rate = (verified_citations / total_citations * 100) if total_citations > 0 else 0
        unsupported_rate = (total_unsupported / total_statements * 100) if total_statements > 0 else 0
        
        latencies = [r.get("latency_ms") for r in records if r.get("latency_ms")]
        median_latency = sorted(latencies)[len(latencies) // 2] if latencies else 0
        
        # Group by doctrine
        doctrine_data: Dict[str, Dict] = {}
        for r in records:
            doc = r.get("doctrine") or "unknown"
            if doc not in doctrine_data:
                doctrine_data[doc] = {
                    "queries": 0,
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unsupported": 0,
                    "statements": 0,
                    "latencies": []
                }
            doctrine_data[doc]["queries"] += 1
            doctrine_data[doc]["total_citations"] += r.get("total_citations", 0)
            doctrine_data[doc]["verified_citations"] += r.get("verified_citations", 0)
            doctrine_data[doc]["unsupported"] += r.get("unsupported_statements", 0)
            doctrine_data[doc]["statements"] += r.get("total_statements", 0)
            if r.get("latency_ms"):
                doctrine_data[doc]["latencies"].append(r.get("latency_ms"))
        
        by_doctrine = []
        alerts = []
        
        for doc, data in doctrine_data.items():
            rate = (data["verified_citations"] / data["total_citations"] * 100) if data["total_citations"] > 0 else 0
            unsup_rate = (data["unsupported"] / data["statements"] * 100) if data["statements"] > 0 else 0
            avg_lat = sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else 0
            
            is_alert = rate < 80
            if is_alert:
                alerts.append(f"⚠️ {doc}: verification rate {rate:.1f}% is below 80% threshold")
            
            by_doctrine.append(DoctrineMetrics(
                doctrine=doc,
                verification_rate=rate,
                total_queries=data["queries"],
                total_citations=data["total_citations"],
                verified_citations=data["verified_citations"],
                unsupported_rate=unsup_rate,
                avg_latency_ms=avg_lat,
                alert=is_alert,
            ))
        
        # Sort by verification rate (lowest first for alerts visibility)
        by_doctrine.sort(key=lambda x: x.verification_rate)
        
        # Analyze binding failure reasons
        failure_counts: Dict[str, int] = {}
        failure_examples: Dict[str, List[str]] = {}
        
        for r in records:
            reasons_json = r.get("binding_failure_reasons")
            if reasons_json:
                try:
                    import json
                    reasons = json.loads(reasons_json) if isinstance(reasons_json, str) else reasons_json
                    for reason in reasons[:5]:  # Limit per record
                        key = str(reason.get("reason", "unknown"))[:50]
                        failure_counts[key] = failure_counts.get(key, 0) + 1
                        if key not in failure_examples:
                            failure_examples[key] = []
                        if len(failure_examples[key]) < 3:
                            failure_examples[key].append(reason.get("example", "")[:100])
                except:
                    pass
        
        total_failures = sum(failure_counts.values())
        top_failures = [
            BindingFailureReason(
                reason=reason,
                count=count,
                percentage=(count / total_failures * 100) if total_failures > 0 else 0,
                examples=failure_examples.get(reason, [])
            )
            for reason, count in sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        return DashboardSummary(
            overall_verification_rate=overall_rate,
            total_queries=len(records),
            total_citations=total_citations,
            verified_citations=verified_citations,
            unsupported_statements_rate=unsupported_rate,
            median_latency_ms=median_latency,
            by_doctrine=by_doctrine,
            top_binding_failures=top_failures,
            alerts=alerts,
            period_start=period_start,
            period_end=period_end,
        )
        
    except Exception as e:
        logging.error(f"Error getting dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TelemetryRecordRequest(BaseModel):
    conversation_id: Optional[str] = None
    doctrine: Optional[str] = None
    total_citations: int = 0
    verified_citations: int = 0
    unsupported_statements: int = 0
    total_statements: int = 0
    latency_ms: Optional[int] = None
    binding_failure_reasons: Optional[List[Dict]] = None


def record_telemetry_internal(
    conversation_id: Optional[str] = None,
    doctrine: Optional[str] = None,
    total_citations: int = 0,
    verified_citations: int = 0,
    unsupported_statements: int = 0,
    total_statements: int = 0,
    latency_ms: Optional[int] = None,
    binding_failure_reasons: Optional[List[Dict]] = None,
):
    """Internal function to record telemetry - called from chat pipeline only."""
    try:
        import json
        db.insert_telemetry(
            conversation_id=conversation_id,
            doctrine=doctrine,
            total_citations=total_citations,
            verified_citations=verified_citations,
            unsupported_statements=unsupported_statements,
            total_statements=total_statements,
            latency_ms=latency_ms,
            binding_failure_reasons=json.dumps(binding_failure_reasons) if binding_failure_reasons else None,
        )
        return True
    except Exception as e:
        logging.error(f"Error recording telemetry: {e}")
        return False
