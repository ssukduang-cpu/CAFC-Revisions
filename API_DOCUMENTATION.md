# CAFC Opinion Assistant - External API Documentation

## Overview

The CAFC Opinion Assistant provides a secure REST API for external applications to query Federal Circuit and Supreme Court patent precedent. All responses include citation-verified legal analysis with source attribution.

## Base URL

```
https://your-app-name.replit.app/api/v1
```

## Authentication

All API requests (except `/health`) require authentication via API key.

**Header:** `X-API-Key: your-api-key`

To get an API key, set the `EXTERNAL_API_KEY` environment variable in your Replit secrets.

---

## Endpoints

### 1. Query Patent Law

**POST** `/api/v1/query`

Submit a legal research question and receive a citation-backed answer.

#### Request

```json
{
  "question": "What are the Alice/Mayo steps for determining patent eligibility under 35 U.S.C. § 101?",
  "conversation_id": null,
  "include_debug": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | Yes | Legal research question (5-2000 chars) |
| `conversation_id` | string | No | For multi-turn conversations |
| `include_debug` | boolean | No | Include debug info (default: false) |

#### Response

```json
{
  "success": true,
  "answer": "Under the Alice/Mayo framework, courts apply a two-step test for patent eligibility...\n\n[1] *Alice Corp. v. CLS Bank* established that...",
  "sources": [
    {
      "case_name": "Alice Corp. v. CLS Bank International",
      "appeal_number": "13-298",
      "release_date": "2014-06-19",
      "page_number": 10,
      "quote": "We hold that the claims at issue are drawn to the abstract idea of intermediated settlement...",
      "confidence_tier": "STRONG",
      "verified": true
    }
  ],
  "conversation_id": "conv-abc123",
  "citation_summary": {
    "total_citations": 4,
    "verified_citations": 4,
    "verification_rate": 100.0,
    "sources_count": 4
  }
}
```

#### Response Fields

| Field | Description |
|-------|-------------|
| `success` | Whether the query was successful |
| `answer` | Markdown-formatted legal analysis with inline citations [1], [2], etc. |
| `sources` | Array of cited cases with verification status |
| `sources[].confidence_tier` | STRONG, MODERATE, WEAK, or UNVERIFIED |
| `sources[].verified` | Whether the quote was verified in source text |
| `citation_summary` | Aggregate verification metrics |

---

### 2. Health Check

**GET** `/api/v1/health`

Check if the API is operational. No authentication required.

```json
{
  "status": "healthy",
  "service": "CAFC Opinion Assistant External API",
  "version": "1.0.0"
}
```

---

### 3. API Info

**GET** `/api/v1/info`

Get information about API capabilities. Requires authentication.

```json
{
  "service": "CAFC Opinion Assistant",
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
  "rate_limit": "5 requests per second"
}
```

---

## Error Handling

All errors return a consistent format:

```json
{
  "success": false,
  "error": "Error description",
  "error_code": "ERROR_CODE"
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_API_KEY` | 401 | API key is missing or invalid |
| `API_NOT_CONFIGURED` | 503 | EXTERNAL_API_KEY not set on server |
| `RATE_LIMITED` | 429 | Exceeded 5 requests/second limit |
| `INTERNAL_ERROR` | 500 | Server-side error |

---

## Rate Limits

- **5 requests per second** per API key
- Burst capacity: 10 requests

---

## Example Integration (Python)

```python
import requests

API_URL = "https://your-app-name.replit.app/api/v1/query"
API_KEY = "your-api-key"

def query_patent_law(question: str) -> dict:
    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        json={"question": question}
    )
    response.raise_for_status()
    return response.json()

# Example usage
result = query_patent_law("What is the standard for obviousness under KSR?")
print(f"Answer: {result['answer']}")
print(f"Sources: {len(result['sources'])} verified citations")
```

---

## Example Integration (JavaScript/Node.js)

```javascript
const API_URL = "https://your-app-name.replit.app/api/v1/query";
const API_KEY = "your-api-key";

async function queryPatentLaw(question) {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ question })
  });
  
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }
  
  return response.json();
}

// Example usage
const result = await queryPatentLaw("What are the Graham v. John Deere factors?");
console.log("Answer:", result.answer);
console.log("Verification Rate:", result.citation_summary.verification_rate + "%");
```

---

## Best Practices

1. **Store your API key securely** - Use environment variables, not hardcoded strings
2. **Handle rate limits gracefully** - Implement exponential backoff for 429 errors
3. **Use conversation_id for follow-ups** - Maintains context across related questions
4. **Check verification status** - Prioritize STRONG/MODERATE tier citations for briefs
5. **Cache responses when appropriate** - Reduce API calls for repeated queries

---

## Support

For issues or questions, contact the application administrator.
