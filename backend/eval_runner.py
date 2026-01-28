"""
Internal Eval Runner for batch prompt evaluations.

Executes 50-200 prompts asynchronously in STRICT mode with:
- Background job execution (not blocking HTTP requests)
- Batching with rate limit awareness (5 prompts, then sleep)
- Persistence after each prompt for resumability
- Stratified sampling across doctrine families
"""

import uuid
import json
import time
import random
import threading
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from collections import defaultdict
import statistics

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

import asyncio

from backend import db_postgres as db
from backend.chat import generate_chat_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal/eval", tags=["eval"])

# Prompt bank organized by doctrine
EVAL_PROMPT_BANK = {
    "101_eligibility": [
        "What is the Alice/Mayo two-step test for patent eligibility?",
        "How do courts analyze abstract ideas under Alice step one?",
        "What constitutes an inventive concept under Alice step two?",
        "How did Bilski v. Kappos define abstract ideas?",
        "What are the Enfish factors for software patent eligibility?",
        "How does DDR Holdings apply to internet-based claims?",
        "What makes a claim patent-ineligible under Section 101?",
        "How do courts handle mathematical algorithms under 101?",
        "What is the preemption concern in eligibility analysis?",
        "How did Diamond v. Diehr treat software claims?",
        "What are methods of organizing human activity under Alice?",
        "How do courts analyze diagnostic method claims under Mayo?",
        "What is the significance of Vanda Pharmaceuticals for method claims?",
        "How does American Axle apply to eligibility analysis?",
        "What are the Federal Circuit's guidelines for step two analysis?",
        "How do courts treat data manipulation claims under 101?",
        "What makes a claim directed to a law of nature?",
        "How did CardioNet expand eligibility for health monitoring?",
        "What is the role of claim construction in 101 analysis?",
        "How do courts analyze claims directed to natural phenomena?",
    ],
    "103_obviousness": [
        "What is the KSR framework for analyzing obviousness?",
        "How do courts apply the Graham v. John Deere factors?",
        "What is the motivation to combine analysis under KSR?",
        "How does obvious to try apply to obviousness?",
        "What are teaching away arguments in obviousness?",
        "How do courts analyze secondary considerations of nonobviousness?",
        "What is the TSM test after KSR?",
        "How does hindsight reconstruction apply to obviousness?",
        "What makes a combination of known elements obvious?",
        "How do courts handle predictable results in obviousness?",
        "What is the role of commercial success in nonobviousness?",
        "How do long-felt but unsolved needs support nonobviousness?",
        "What is the failure of others doctrine?",
        "How do courts analyze unexpected results?",
        "What is a design choice in obviousness analysis?",
        "How does In re Wands apply to obviousness?",
        "What is the level of ordinary skill in the art?",
        "How do courts handle combining prior art references?",
        "What is the rational underpinning requirement for obviousness?",
        "How did SRI International v. Cisco apply KSR?",
    ],
    "112_disclosure": [
        "What is the written description requirement under 35 USC 112?",
        "How do courts analyze enablement under Section 112?",
        "What are the Wands factors for enablement?",
        "How does the full scope of claims affect enablement?",
        "What is undue experimentation in enablement analysis?",
        "How do courts analyze definiteness under 112(b)?",
        "What is the Nautilus standard for definiteness?",
        "How does claim construction affect 112 analysis?",
        "What is the written description requirement for genus claims?",
        "How do Ariad and Lockwood apply to written description?",
        "What is possession of the invention under 112?",
        "How do courts handle prophetic examples in enablement?",
        "What is the relationship between enablement and written description?",
        "How does the specification support functional claim language?",
        "What makes a claim indefinite under Nautilus?",
        "How do courts analyze best mode under Section 112?",
        "What is the disclosure requirement for means-plus-function claims?",
        "How does Williamson affect claim construction?",
        "What is the unpredictability of technology in enablement?",
        "How do courts evaluate the scope of generic claims?",
    ],
    "claim_construction": [
        "What is the Phillips standard for claim construction?",
        "How do courts use intrinsic evidence in claim construction?",
        "What is the role of the specification in construing claims?",
        "How does prosecution history affect claim construction?",
        "When can extrinsic evidence be used in claim construction?",
        "What is claim differentiation in construction?",
        "How do courts construe means-plus-function claims?",
        "What is the ordinary meaning of claim terms?",
        "How does Markman apply to claim construction?",
        "What is the role of dictionaries in claim construction?",
        "How do courts handle preamble limitations?",
        "What is the prosecution disclaimer doctrine?",
        "How do courts construe transitional phrases?",
        "What is the effect of exemplary embodiments on construction?",
        "How do courts handle open-ended claim language?",
        "What is lexicography in claim construction?",
        "How do courts construe product-by-process claims?",
        "What is the broadest reasonable interpretation standard?",
        "How does en banc Williamson affect means-plus-function?",
        "What is the role of expert testimony in construction?",
    ],
    "infringement": [
        "What is literal infringement of patent claims?",
        "How does the doctrine of equivalents apply?",
        "What is the function-way-result test for equivalents?",
        "How does prosecution history estoppel limit equivalents?",
        "What is all-elements rule in infringement?",
        "How do courts analyze induced infringement under 271(b)?",
        "What is contributory infringement under 271(c)?",
        "How does Akamai apply to divided infringement?",
        "What is the knowledge requirement for indirect infringement?",
        "How do courts analyze method claims in infringement?",
        "What is joint infringement doctrine?",
        "How does Limelight affect multi-actor infringement?",
        "What is the substantial noninfringing use defense?",
        "How do courts handle means-plus-function in infringement?",
        "What is the timing of infringement for method claims?",
        "How does the all-advantages rule apply?",
        "What is the insubstantial differences test?",
        "How do courts analyze claim limitations in infringement?",
        "What is the role of claim construction in infringement?",
        "How does exhaustion affect infringement claims?",
    ],
    "remedies": [
        "What are the eBay factors for permanent injunctions?",
        "How do courts calculate reasonable royalty damages?",
        "What is the Georgia-Pacific framework for royalties?",
        "How do courts determine lost profits damages?",
        "What is the Panduit test for lost profits?",
        "How does enhanced damages work under 35 USC 284?",
        "What is the Halo standard for willful infringement?",
        "How do courts award attorney fees under Section 285?",
        "What makes a case exceptional for fee shifting?",
        "How does Octane Fitness apply to fee awards?",
        "What is the entire market value rule?",
        "How do courts apportion damages for multi-component products?",
        "What is the smallest salable unit for damages?",
        "How do courts handle ongoing royalties?",
        "What is prejudgment interest in patent damages?",
        "How do courts analyze irreparable harm for injunctions?",
        "What is the public interest factor in injunctions?",
        "How does Grain Processing affect damages?",
        "What are the requirements for preliminary injunctions?",
        "How do courts handle damages for design patents?",
    ],
    "ptab": [
        "What is inter partes review at the PTAB?",
        "How do courts review PTAB decisions on appeal?",
        "What is the claim construction standard at the PTAB?",
        "How does the PTAB apply obviousness in IPR?",
        "What is post-grant review procedure?",
        "How does discretionary denial work at the PTAB?",
        "What is the Fintiv doctrine for stays?",
        "How do courts handle estoppel from PTAB proceedings?",
        "What is the difference between IPR and PGR?",
        "How does ex parte reexamination work?",
        "What is the standard of review for PTAB findings?",
        "How do courts handle constitutional challenges to PTAB?",
        "What is the appointment of PTAB judges issue?",
        "How does Arthrex affect PTAB proceedings?",
        "What is the NHK-Fintiv discretionary denial?",
        "How do courts review PTAB claim construction?",
        "What is the burden of proof in IPR?",
        "How does the PTAB handle new prior art references?",
        "What is the effect of a final written decision?",
        "How do courts handle parallel litigation and IPR?",
    ],
    "doe_equivalents": [
        "What is the doctrine of equivalents in patent law?",
        "How does prosecution history estoppel limit DOE?",
        "What is the Festo presumption for claim amendments?",
        "How do courts apply the function-way-result test?",
        "What is the insubstantial differences test for DOE?",
        "How does the all-elements rule apply to DOE?",
        "What is the vitiation doctrine?",
        "How do courts analyze dedication to the public?",
        "What is argument-based estoppel?",
        "How does Warner-Jenkinson apply to DOE?",
        "What is the tangential relation exception to estoppel?",
        "How do courts determine if an element is equivalent?",
        "What is the objective inquiry for equivalents?",
        "How does technology at the time of infringement matter?",
        "What is the after-arising technology doctrine?",
        "How do courts handle narrowing amendments for estoppel?",
        "What is the complete bar for estoppel?",
        "How does Graver Tank apply to equivalents?",
        "What is the role of expert testimony in DOE?",
        "How do courts analyze claim scope limits on DOE?",
    ],
    "validity": [
        "What is the presumption of validity under 35 USC 282?",
        "How do courts analyze anticipation under Section 102?",
        "What is the clear and convincing evidence standard?",
        "How does prior art invalidate claims?",
        "What is inherent anticipation?",
        "How do courts analyze on-sale bar?",
        "What is the public use bar under AIA?",
        "How does experimental use exception apply?",
        "What is the printed publication bar?",
        "How do courts handle secret prior art?",
        "What is the critical date for prior art?",
        "How does AIA change prior art rules?",
        "What is the grace period under AIA?",
        "How do courts analyze derivation?",
        "What is double patenting doctrine?",
        "How does terminal disclaimer work?",
        "What is the on-sale bar for methods?",
        "How do courts handle commercial offers for sale?",
        "What is the ready for patenting standard?",
        "How does Helsinn affect the on-sale bar?",
    ],
    "procedure": [
        "What is venue for patent cases under TC Heartland?",
        "How do courts handle case-within-a-case in malpractice?",
        "What is the standard for summary judgment in patent cases?",
        "How do courts handle claim construction appeals?",
        "What is the role of the jury in patent trials?",
        "How does Markman hearing work?",
        "What is the standard for preliminary injunctions?",
        "How do courts handle discovery in patent cases?",
        "What is the procedure for IPR appeals?",
        "How does standing work in patent cases?",
        "What is the Declaratory Judgment Act in patent law?",
        "How do courts analyze joinder in patent cases?",
        "What is the standard for transfer of venue?",
        "How do courts handle stays pending IPR?",
        "What is the procedure for design patent cases?",
        "How does Federal Circuit jurisdiction work?",
        "What is the standard of review for claim construction?",
        "How do courts handle bifurcation in patent trials?",
        "What is the procedure for Hatch-Waxman litigation?",
        "How do courts analyze laches in patent cases?",
    ],
}

# Global tracking of active eval runs (in-memory for resumability)
_active_runs: Dict[str, threading.Thread] = {}
_run_locks: Dict[str, threading.Lock] = {}


class StartEvalRequest(BaseModel):
    count: int = 50
    mode: str = "STRICT"


class EvalRunStatus(BaseModel):
    eval_run_id: str
    status: str
    mode: str
    total_prompts: int
    completed_prompts: int
    failed_prompts: int
    verification_rate: Optional[float] = None
    latency_p50: Optional[float] = None
    latency_p95: Optional[float] = None
    error_summary: Optional[str] = None
    created_at: datetime
    by_doctrine: Optional[Dict[str, Any]] = None


class EvalResult(BaseModel):
    prompt_id: str
    prompt_text: str
    doctrine_tag: str
    verified_rate: float
    citations_total: int
    citations_verified: int
    citations_unverified: int
    case_attributed_propositions: int
    case_attributed_unsupported: int
    failure_reason_counts: Dict[str, int]
    latency_ms: int
    created_at: datetime


def _init_eval_tables():
    """Create eval tables if they don't exist."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                mode VARCHAR(20) NOT NULL DEFAULT 'STRICT',
                status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
                total_prompts INTEGER NOT NULL DEFAULT 0,
                completed_prompts INTEGER NOT NULL DEFAULT 0,
                failed_prompts INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT,
                latency_p50 FLOAT,
                latency_p95 FLOAT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS eval_results (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                eval_run_id UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
                prompt_id VARCHAR(100) NOT NULL,
                prompt_text TEXT NOT NULL,
                doctrine_tag VARCHAR(50) NOT NULL,
                verified_rate FLOAT NOT NULL DEFAULT 0,
                citations_total INTEGER NOT NULL DEFAULT 0,
                citations_verified INTEGER NOT NULL DEFAULT 0,
                citations_unverified INTEGER NOT NULL DEFAULT 0,
                case_attributed_propositions INTEGER NOT NULL DEFAULT 0,
                case_attributed_unsupported INTEGER NOT NULL DEFAULT 0,
                failure_reason_counts JSONB DEFAULT '{}',
                latency_ms INTEGER NOT NULL DEFAULT 0,
                response_id VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_eval_results_run_id ON eval_results(eval_run_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_eval_results_doctrine ON eval_results(doctrine_tag)
        """)


def _create_eval_run(mode: str, total_prompts: int) -> str:
    """Create a new eval run and return its ID."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        eval_run_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO eval_runs (id, mode, status, total_prompts)
            VALUES (%s, %s, 'RUNNING', %s)
        """, (eval_run_id, mode, total_prompts))
        return eval_run_id


def _update_eval_run(eval_run_id: str, **kwargs):
    """Update eval run fields."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        sets = []
        values = []
        for k, v in kwargs.items():
            sets.append(f"{k} = %s")
            values.append(v)
        sets.append("updated_at = NOW()")
        values.append(eval_run_id)
        
        cursor.execute(f"""
            UPDATE eval_runs SET {', '.join(sets)} WHERE id = %s
        """, values)


def _get_eval_run(eval_run_id: str) -> Optional[Dict]:
    """Get eval run by ID."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM eval_runs WHERE id = %s
        """, (eval_run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def _insert_eval_result(
    eval_run_id: str,
    prompt_id: str,
    prompt_text: str,
    doctrine_tag: str,
    verified_rate: float,
    citations_total: int,
    citations_verified: int,
    citations_unverified: int,
    case_attributed_propositions: int,
    case_attributed_unsupported: int,
    failure_reason_counts: Dict[str, int],
    latency_ms: int,
    response_id: Optional[str] = None
):
    """Insert a single eval result."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO eval_results (
                eval_run_id, prompt_id, prompt_text, doctrine_tag,
                verified_rate, citations_total, citations_verified, citations_unverified,
                case_attributed_propositions, case_attributed_unsupported,
                failure_reason_counts, latency_ms, response_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            eval_run_id, prompt_id, prompt_text, doctrine_tag,
            verified_rate, citations_total, citations_verified, citations_unverified,
            case_attributed_propositions, case_attributed_unsupported,
            json.dumps(failure_reason_counts), latency_ms, response_id
        ))


def _get_eval_results(eval_run_id: str, limit: int = 100, offset: int = 0) -> List[Dict]:
    """Get eval results for a run."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM eval_results 
            WHERE eval_run_id = %s 
            ORDER BY created_at
            LIMIT %s OFFSET %s
        """, (eval_run_id, limit, offset))
        return [dict(row) for row in cursor.fetchall()]


def _get_doctrine_breakdown(eval_run_id: str) -> Dict[str, Dict]:
    """Get per-doctrine breakdown for an eval run."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                doctrine_tag,
                COUNT(*) as count,
                AVG(verified_rate) as avg_verified_rate,
                SUM(citations_total) as total_citations,
                SUM(citations_verified) as verified_citations,
                SUM(citations_unverified) as unverified_citations,
                SUM(case_attributed_unsupported) as case_attr_unsupported,
                SUM(case_attributed_propositions) as case_attr_total,
                AVG(latency_ms) as avg_latency_ms
            FROM eval_results
            WHERE eval_run_id = %s
            GROUP BY doctrine_tag
        """, (eval_run_id,))
        
        result = {}
        for row in cursor.fetchall():
            d = dict(row)
            doctrine = d.pop('doctrine_tag')
            case_attr_total = d.get('case_attr_total', 0) or 0
            case_attr_unsup = d.get('case_attr_unsupported', 0) or 0
            d['case_attributed_unsupported_rate'] = (
                (case_attr_unsup / case_attr_total * 100) if case_attr_total > 0 else 0
            )
            result[doctrine] = d
        return result


def _sample_prompts(count: int) -> List[Dict[str, str]]:
    """Sample prompts stratified by doctrine."""
    doctrines = list(EVAL_PROMPT_BANK.keys())
    prompts_per_doctrine = count // len(doctrines)
    remainder = count % len(doctrines)
    
    result = []
    prompt_idx = 0
    
    for i, doctrine in enumerate(doctrines):
        available = EVAL_PROMPT_BANK[doctrine]
        num_to_sample = prompts_per_doctrine + (1 if i < remainder else 0)
        sampled = available[:num_to_sample]
        
        for j, prompt in enumerate(sampled):
            result.append({
                "prompt_id": f"{doctrine}_{j}",
                "doctrine_tag": doctrine,
                "prompt_text": prompt
            })
            prompt_idx += 1
    
    random.shuffle(result)
    return result


def _run_single_prompt(prompt_text: str, doctrine: str) -> Dict:
    """Run a single prompt and return metrics."""
    start_time = time.time()
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(generate_chat_response(
                message=prompt_text,
                conversation_id=None
            ))
        finally:
            loop.close()
        
        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Eval] Prompt completed in {latency_ms}ms: '{prompt_text[:50]}...'")
        
        debug = response.get("debug", {})
        citation_metrics = debug.get("citation_metrics", {})
        
        total_citations = citation_metrics.get("total_citations", 0)
        verified_citations = citation_metrics.get("verified_citations", 0)
        unverified_citations = total_citations - verified_citations
        verified_rate = (verified_citations / total_citations * 100) if total_citations > 0 else 100
        
        statement_support = response.get("statement_support", [])
        case_attributed = sum(1 for s in statement_support if s.get("mentioned_cases"))
        case_unsupported = sum(1 for s in statement_support if s.get("mentioned_cases") and not s.get("supported"))
        
        failure_reasons: Dict[str, int] = defaultdict(int)
        sources = response.get("sources", [])
        for s in sources:
            cv = s.get("citation_verification", {})
            if cv.get("tier", "").upper() == "UNVERIFIED":
                signals = cv.get("signals", [])
                quote = s.get("quote", "")
                
                # Classify failure using enhanced taxonomy
                failure_classified = False
                for sig in signals:
                    sig_lower = sig.lower()
                    if "not_found" in sig_lower or "no_match" in sig_lower:
                        failure_reasons["QUOTE_NOT_FOUND"] += 1
                        failure_classified = True
                    elif "wrong_case" in sig_lower or "binding_failed" in sig_lower:
                        failure_reasons["WRONG_CASE_ID"] += 1
                        failure_classified = True
                    elif "wrong_page" in sig_lower:
                        failure_reasons["WRONG_PAGE"] += 1
                        failure_classified = True
                    elif "too_short" in sig_lower:
                        failure_reasons["TOO_SHORT"] += 1
                        failure_classified = True
                    elif "ocr" in sig_lower or "artifact" in sig_lower:
                        failure_reasons["OCR_ARTIFACT_MISMATCH"] += 1
                        failure_classified = True
                    elif "normalization" in sig_lower:
                        failure_reasons["NORMALIZATION_MISMATCH"] += 1
                        failure_classified = True
                
                # Check for ellipsis fragments
                if not failure_classified and ("..." in quote or "…" in quote):
                    failure_reasons["ELLIPSIS_FRAGMENT"] += 1
                    failure_classified = True
                
                # Check for short quotes
                if not failure_classified and len(quote.strip()) < 25:
                    failure_reasons["TOO_SHORT"] += 1
                    failure_classified = True
                
                if not failure_classified:
                    failure_reasons["OTHER"] += 1
        
        return {
            "success": True,
            "verified_rate": verified_rate,
            "citations_total": total_citations,
            "citations_verified": verified_citations,
            "citations_unverified": unverified_citations,
            "case_attributed_propositions": case_attributed,
            "case_attributed_unsupported": case_unsupported,
            "failure_reason_counts": dict(failure_reasons),
            "latency_ms": latency_ms,
            "response_id": response.get("response_id"),
        }
        
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Error running eval prompt: {e}")
        return {
            "success": False,
            "error": str(e),
            "verified_rate": 0,
            "citations_total": 0,
            "citations_verified": 0,
            "citations_unverified": 0,
            "case_attributed_propositions": 0,
            "case_attributed_unsupported": 0,
            "failure_reason_counts": {"ERROR": 1},
            "latency_ms": latency_ms,
        }


def _run_eval_background(eval_run_id: str, prompts: List[Dict], mode: str):
    """Background worker that runs prompts in batches."""
    BATCH_SIZE = 5
    BATCH_SLEEP_SECONDS = 2
    
    logger.info(f"[Eval {eval_run_id}] Starting background eval with {len(prompts)} prompts")
    
    completed = 0
    failed = 0
    all_latencies = []
    
    try:
        for i, prompt in enumerate(prompts):
            result = _run_single_prompt(prompt["prompt_text"], prompt["doctrine_tag"])
            
            if result.get("success"):
                _insert_eval_result(
                    eval_run_id=eval_run_id,
                    prompt_id=prompt["prompt_id"],
                    prompt_text=prompt["prompt_text"],
                    doctrine_tag=prompt["doctrine_tag"],
                    verified_rate=result["verified_rate"],
                    citations_total=result["citations_total"],
                    citations_verified=result["citations_verified"],
                    citations_unverified=result["citations_unverified"],
                    case_attributed_propositions=result["case_attributed_propositions"],
                    case_attributed_unsupported=result["case_attributed_unsupported"],
                    failure_reason_counts=result["failure_reason_counts"],
                    latency_ms=result["latency_ms"],
                    response_id=result.get("response_id")
                )
                completed += 1
                all_latencies.append(result["latency_ms"])
            else:
                _insert_eval_result(
                    eval_run_id=eval_run_id,
                    prompt_id=prompt["prompt_id"],
                    prompt_text=prompt["prompt_text"],
                    doctrine_tag=prompt["doctrine_tag"],
                    verified_rate=0,
                    citations_total=0,
                    citations_verified=0,
                    citations_unverified=0,
                    case_attributed_propositions=0,
                    case_attributed_unsupported=0,
                    failure_reason_counts={"ERROR": 1},
                    latency_ms=result["latency_ms"]
                )
                failed += 1
            
            _update_eval_run(eval_run_id, completed_prompts=completed, failed_prompts=failed)
            
            logger.info(f"[Eval {eval_run_id}] Progress: {completed + failed}/{len(prompts)}")
            
            if (i + 1) % BATCH_SIZE == 0 and i + 1 < len(prompts):
                logger.info(f"[Eval {eval_run_id}] Batch complete, sleeping {BATCH_SLEEP_SECONDS}s...")
                time.sleep(BATCH_SLEEP_SECONDS)
        
        p50 = statistics.median(all_latencies) if all_latencies else 0
        p95 = sorted(all_latencies)[int(len(all_latencies) * 0.95)] if all_latencies else 0
        
        _update_eval_run(
            eval_run_id,
            status="COMPLETE",
            latency_p50=p50,
            latency_p95=p95
        )
        logger.info(f"[Eval {eval_run_id}] Completed: {completed} success, {failed} failed")
        
    except Exception as e:
        logger.error(f"[Eval {eval_run_id}] Fatal error: {e}")
        _update_eval_run(
            eval_run_id,
            status="FAILED",
            error_summary=str(e)
        )
    finally:
        if eval_run_id in _active_runs:
            del _active_runs[eval_run_id]


@router.on_event("startup")
async def startup_init_tables():
    """Initialize eval tables on startup."""
    _init_eval_tables()


@router.post("/start")
async def start_eval(request: StartEvalRequest, background_tasks: BackgroundTasks):
    """Start a new eval run."""
    _init_eval_tables()
    
    if request.count < 10 or request.count > 200:
        raise HTTPException(400, "Count must be between 10 and 200")
    if request.mode not in ("STRICT", "RESEARCH"):
        raise HTTPException(400, "Mode must be STRICT or RESEARCH")
    
    prompts = _sample_prompts(request.count)
    eval_run_id = _create_eval_run(request.mode, len(prompts))
    
    thread = threading.Thread(
        target=_run_eval_background,
        args=(eval_run_id, prompts, request.mode),
        daemon=True
    )
    _active_runs[eval_run_id] = thread
    thread.start()
    
    return {"eval_run_id": eval_run_id, "total_prompts": len(prompts)}


@router.get("/status")
async def get_eval_status(eval_run_id: str = Query(...)):
    """Get status of an eval run."""
    run = _get_eval_run(eval_run_id)
    if not run:
        raise HTTPException(404, "Eval run not found")
    
    results = _get_eval_results(eval_run_id, limit=1000, offset=0)
    
    verification_rate = None
    if results:
        total_cites = sum(r.get("citations_total", 0) for r in results)
        verified_cites = sum(r.get("citations_verified", 0) for r in results)
        verification_rate = (verified_cites / total_cites * 100) if total_cites > 0 else 0
    
    by_doctrine = _get_doctrine_breakdown(eval_run_id)
    
    return EvalRunStatus(
        eval_run_id=eval_run_id,
        status=run["status"],
        mode=run["mode"],
        total_prompts=run["total_prompts"],
        completed_prompts=run["completed_prompts"],
        failed_prompts=run["failed_prompts"],
        verification_rate=verification_rate,
        latency_p50=run.get("latency_p50"),
        latency_p95=run.get("latency_p95"),
        error_summary=run.get("error_summary"),
        created_at=run["created_at"],
        by_doctrine=by_doctrine
    )


@router.get("/results")
async def get_eval_results(
    eval_run_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Get paginated results for an eval run."""
    run = _get_eval_run(eval_run_id)
    if not run:
        raise HTTPException(404, "Eval run not found")
    
    results = _get_eval_results(eval_run_id, limit=limit, offset=offset)
    
    return {
        "eval_run_id": eval_run_id,
        "total": run["completed_prompts"] + run["failed_prompts"],
        "limit": limit,
        "offset": offset,
        "results": [
            EvalResult(
                prompt_id=r["prompt_id"],
                prompt_text=r["prompt_text"],
                doctrine_tag=r["doctrine_tag"],
                verified_rate=r["verified_rate"],
                citations_total=r["citations_total"],
                citations_verified=r["citations_verified"],
                citations_unverified=r["citations_unverified"],
                case_attributed_propositions=r["case_attributed_propositions"],
                case_attributed_unsupported=r["case_attributed_unsupported"],
                failure_reason_counts=r["failure_reason_counts"] or {},
                latency_ms=r["latency_ms"],
                created_at=r["created_at"]
            )
            for r in results
        ]
    }


@router.get("/runs")
async def list_eval_runs(limit: int = Query(20, ge=1, le=100)):
    """List recent eval runs."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        runs = [dict(row) for row in cursor.fetchall()]
    
    return {"runs": runs}
