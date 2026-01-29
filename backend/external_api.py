"""
External API Module for CAFC Opinion Assistant

This module provides a secure API endpoint for external applications to query
the patent law research system. It handles:
- API key authentication
- Clean request/response formatting
- Rate limiting for external access
"""

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import logging
import time
import threading

from backend.chat import generate_chat_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["External API"])


# Rate limiter for external API (more restrictive: 5 req/sec)
class ExternalRateLimiter:
    def __init__(self, rate: float = 5.0, capacity: float = 10.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = threading.Lock()
    
    def allow(self) -> bool:
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


external_rate_limiter = ExternalRateLimiter(rate=5.0, capacity=10.0)


# Request/Response Models
class QueryRequest(BaseModel):
    """Request model for external API queries."""
    question: str = Field(..., min_length=5, max_length=2000, description="Legal research question")
    conversation_id: Optional[str] = Field(None, description="Optional conversation ID for multi-turn queries")
    include_debug: bool = Field(False, description="Include debug information in response")


class SourceInfo(BaseModel):
    """Simplified source information for external consumers."""
    case_name: str
    appeal_number: Optional[str] = None
    release_date: Optional[str] = None
    page_number: int
    quote: str
    confidence_tier: str
    verified: bool


class QueryResponse(BaseModel):
    """Response model for external API queries."""
    success: bool
    answer: str
    sources: List[SourceInfo]
    conversation_id: Optional[str] = None
    citation_summary: Dict[str, Any]
    debug: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Error response model."""
    success: bool = False
    error: str
    error_code: str


def get_api_key():
    """Get the configured API key from environment."""
    return os.environ.get("EXTERNAL_API_KEY")


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """Verify the provided API key."""
    expected_key = get_api_key()
    
    if not expected_key:
        logger.warning("EXTERNAL_API_KEY not configured - external API access disabled")
        raise HTTPException(
            status_code=503,
            detail={"error": "External API not configured", "error_code": "API_NOT_CONFIGURED"}
        )
    
    if x_api_key != expected_key:
        logger.warning(f"Invalid API key attempt")
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid API key", "error_code": "INVALID_API_KEY"}
        )
    
    return x_api_key


@router.post("/query", response_model=QueryResponse)
async def query_patent_law(
    request: QueryRequest,
    api_key: str = Depends(verify_api_key)
) -> QueryResponse:
    """
    Query the patent law research system.
    
    This endpoint provides access to Federal Circuit and Supreme Court patent
    precedent with citation-verified answers.
    
    **Authentication:** Requires X-API-Key header with valid API key.
    
    **Rate Limit:** 5 requests per second.
    
    **Example Request:**
    ```
    POST /api/v1/query
    Headers: X-API-Key: your-api-key
    Body: {"question": "What are the Alice/Mayo steps for patent eligibility?"}
    ```
    """
    
    # Check rate limit
    if not external_rate_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded. Max 5 requests/second.", "error_code": "RATE_LIMITED"}
        )
    
    try:
        logger.info(f"[External API] Query received: {request.question[:100]}...")
        
        # Call the main chat function
        response = await generate_chat_response(
            message=request.question,
            conversation_id=request.conversation_id
        )
        
        # Extract and simplify sources
        sources = []
        raw_sources = response.get("sources", [])
        
        for src in raw_sources:
            cv = src.get("citation_verification", {})
            sources.append(SourceInfo(
                case_name=src.get("caseName", "Unknown"),
                appeal_number=src.get("appealNo"),
                release_date=src.get("releaseDate"),
                page_number=src.get("pageNumber", 0),
                quote=src.get("quote", "")[:500],
                confidence_tier=cv.get("tier", "UNKNOWN"),
                verified=cv.get("verified", False)
            ))
        
        # Build citation summary
        debug_info = response.get("debug", {})
        citation_metrics = debug_info.get("citation_metrics", {})
        
        citation_summary = {
            "total_citations": citation_metrics.get("total_citations", len(sources)),
            "verified_citations": citation_metrics.get("verified_citations", 0),
            "verification_rate": citation_metrics.get("verified_rate_pct", 0),
            "sources_count": len(sources)
        }
        
        # Build response
        result = QueryResponse(
            success=True,
            answer=response.get("answer_markdown", "No answer generated."),
            sources=sources,
            conversation_id=response.get("conversation_id"),
            citation_summary=citation_summary,
            debug=debug_info if request.include_debug else None
        )
        
        logger.info(f"[External API] Query completed with {len(sources)} sources, {citation_summary.get('verification_rate', 0):.1f}% verified")
        
        return result
        
    except Exception as e:
        logger.error(f"[External API] Error processing query: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "error_code": "INTERNAL_ERROR"}
        )


@router.get("/health")
async def health_check():
    """Health check endpoint (no authentication required)."""
    return {
        "status": "healthy",
        "service": "CAFC Opinion Assistant External API",
        "version": "1.0.0"
    }


@router.get("/info", dependencies=[Depends(verify_api_key)])
async def api_info(api_key: str = Depends(verify_api_key)):
    """Get API information and capabilities."""
    return {
        "service": "CAFC Opinion Assistant",
        "description": "Federal Circuit and Supreme Court patent law research with citation verification",
        "capabilities": [
            "Patent eligibility (35 U.S.C. § 101)",
            "Obviousness (35 U.S.C. § 103)",
            "Written description & enablement (35 U.S.C. § 112)",
            "Claim construction",
            "Infringement analysis",
            "Remedies and damages",
            "PTAB proceedings",
            "Doctrine of equivalents"
        ],
        "rate_limit": "5 requests per second",
        "response_format": {
            "answer": "Markdown-formatted legal analysis with inline citations",
            "sources": "Array of cited cases with quotes and verification status",
            "citation_summary": "Aggregate verification metrics"
        }
    }
