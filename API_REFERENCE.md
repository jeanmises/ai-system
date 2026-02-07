# API Reference

Complete API documentation for AI System v1.0.

---

## Base URL

```
Production:  https://api.ai-system.com
Staging:     https://staging-api.ai-system.com
Development: http://localhost:8000
```

---

## Authentication

All API requests require authentication via JWT bearer token.

```http
Authorization: Bearer <your_jwt_token>
```

### Get Token (OIDC)

```bash
curl -X POST "https://keycloak.ai-system.com/realms/ai-system/protocol/openid-connect/token" \
  -d "client_id=ai-system-api" \
  -d "username=user@example.com" \
  -d "password=your_password" \
  -d "grant_type=password"
```

---

## Sessions

### Create Session

Create a new AI session.

**Endpoint:** `POST /api/sessions`

**Request:**
```json
{
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "objective": "Analyze quarterly financial reports",
  "llm_id": "claude-3-sonnet-20240229",
  "llm_version": "20240229",
  "title": "Q4 Financial Analysis",
  "llm_config": {
    "temperature": 0.7,
    "max_tokens": 4000
  }
}
```

**Response:** `200 OK`
```json
{
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "owner_user_id": "123e4567-e89b-12d3-a456-426614174000",
  "objective": "Analyze quarterly financial reports",
  "status": "active",
  "llm_id": "claude-3-sonnet-20240229",
  "llm_version": "20240229",
  "title": "Q4 Financial Analysis",
  "session_metadata": {
    "temperature": 0.7,
    "max_tokens": 4000
  },
  "created_at": "2024-03-20T10:30:00Z"
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/api/sessions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "objective": "Test session",
    "llm_id": "claude-3-haiku-20240307",
    "llm_version": "20240307"
  }'
```

---

### Get Session

Retrieve session details.

**Endpoint:** `GET /api/sessions/{session_id}`

**Response:** `200 OK`
```json
{
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "owner_user_id": "123e4567-e89b-12d3-a456-426614174000",
  "objective": "Analyze quarterly financial reports",
  "status": "active",
  "llm_id": "claude-3-sonnet-20240229",
  "llm_version": "20240229",
  "title": "Q4 Financial Analysis",
  "created_at": "2024-03-20T10:30:00Z"
}
```

---

### List Sessions

List all sessions with optional filters.

**Endpoint:** `GET /api/sessions`

**Query Parameters:**
- `status` (optional): Filter by status (active, paused, archived)
- `limit` (optional): Max results (default: 50, max: 100)

**Response:** `200 OK`
```json
[
  {
    "session_id": "456e7890-e89b-12d3-a456-426614174111",
    "owner_user_id": "123e4567-e89b-12d3-a456-426614174000",
    "objective": "Analyze quarterly financial reports",
    "status": "active",
    "title": "Q4 Financial Analysis",
    "created_at": "2024-03-20T10:30:00Z"
  }
]
```

---

### Update Session Status

Update session status (active ↔ paused → archived).

**Endpoint:** `PATCH /api/sessions/{session_id}/status`

**Request:**
```json
{
  "new_status": "paused"
}
```

**Response:** `200 OK`
```json
{
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "status": "paused",
  "updated_at": "2024-03-20T11:00:00Z"
}
```

---

## Jobs

### Create Job

Create an asynchronous job.

**Endpoint:** `POST /api/jobs`

**Request:**
```json
{
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "job_type": "llm_call",
  "payload": {
    "messages": [
      {
        "role": "user",
        "content": "Summarize this report"
      }
    ]
  },
  "timeout_seconds": 300,
  "max_retries": 3
}
```

**Response:** `200 OK`
```json
{
  "job_id": "789e0123-e89b-12d3-a456-426614174222",
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "job_type": "llm_call",
  "status": "PENDING",
  "created_at": "2024-03-20T10:35:00Z"
}
```

---

### Get Job Status

Check job status and result.

**Endpoint:** `GET /api/jobs/{job_id}`

**Response:** `200 OK`
```json
{
  "job_id": "789e0123-e89b-12d3-a456-426614174222",
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "job_type": "llm_call",
  "status": "COMPLETED",
  "result": {
    "content": "Summary of the report...",
    "tokens_used": 150
  },
  "created_at": "2024-03-20T10:35:00Z",
  "completed_at": "2024-03-20T10:35:15Z"
}
```

---

### List Jobs

List all jobs with optional filters.

**Endpoint:** `GET /api/jobs`

**Query Parameters:**
- `session_id` (optional): Filter by session
- `status` (optional): Filter by status (PENDING, RUNNING, COMPLETED, FAILED)
- `job_type` (optional): Filter by type
- `limit` (optional): Max results (default: 50)

**Response:** `200 OK`
```json
[
  {
    "job_id": "789e0123-e89b-12d3-a456-426614174222",
    "job_type": "llm_call",
    "status": "COMPLETED",
    "created_at": "2024-03-20T10:35:00Z"
  }
]
```

---

## LLM

### Call LLM

Make synchronous LLM API call with deterministic retry.

**Endpoint:** `POST /api/llm/call`

**Request:**
```json
{
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "model": "claude-3-sonnet-20240229",
  "messages": [
    {
      "role": "user",
      "content": "What is the capital of France?"
    }
  ],
  "max_tokens": 100,
  "temperature": 0.7,
  "system": "You are a helpful assistant."
}
```

**Response:** `200 OK`
```json
{
  "response": {
    "content": "The capital of France is Paris.",
    "stop_reason": "end_turn"
  },
  "usage": {
    "input_tokens": 15,
    "output_tokens": 8
  },
  "model": "claude-3-sonnet-20240229",
  "duration_ms": 850
}
```

---

## SubSessions

### Create SubSession

Create isolated subsession for parallel work.

**Endpoint:** `POST /api/sessions/{session_id}/subsessions`

**Request:**
```json
{
  "objective": "Analyze section 3 of report",
  "input_snapshot": {
    "section": 3,
    "data": "..."
  },
  "config": {
    "timeout_seconds": 300
  }
}
```

**Response:** `200 OK`
```json
{
  "subsession_id": "abc12345-e89b-12d3-a456-426614174333",
  "parent_session_id": "456e7890-e89b-12d3-a456-426614174111",
  "objective": "Analyze section 3 of report",
  "status": "active",
  "created_at": "2024-03-20T10:40:00Z"
}
```

---

### List SubSessions

List all subsessions for a parent session.

**Endpoint:** `GET /api/sessions/{session_id}/subsessions`

**Response:** `200 OK`
```json
[
  {
    "subsession_id": "abc12345-e89b-12d3-a456-426614174333",
    "objective": "Analyze section 3 of report",
    "status": "completed",
    "created_at": "2024-03-20T10:40:00Z"
  }
]
```

---

## Meta-Proposals

### Create Meta-Proposal

Propose system improvement.

**Endpoint:** `POST /api/meta-proposals`

**Request:**
```json
{
  "session_id": "456e7890-e89b-12d3-a456-426614174111",
  "title": "Add caching layer for frequent queries",
  "description": "Implement Redis caching to reduce database load",
  "category": "config_change",
  "proposed_changes": {
    "component": "database",
    "change_type": "add_caching",
    "details": "..."
  },
  "impact_assessment": {
    "risk": "low",
    "affected_components": ["database", "api"],
    "estimated_effort": "2 hours"
  },
  "rollback_plan": {
    "strategy": "disable_feature_flag",
    "backup_required": false
  }
}
```

**Response:** `200 OK`
```json
{
  "proposal_id": "def45678-e89b-12d3-a456-426614174444",
  "status": "draft",
  "created_at": "2024-03-20T10:50:00Z"
}
```

---

### Update Proposal Status

Move proposal through workflow.

**Endpoint:** `PATCH /api/meta-proposals/{proposal_id}/status`

**Request:**
```json
{
  "new_status": "submitted",
  "reviewer_notes": "Looks good, ready for review"
}
```

**Response:** `200 OK`
```json
{
  "proposal_id": "def45678-e89b-12d3-a456-426614174444",
  "status": "submitted",
  "updated_at": "2024-03-20T11:00:00Z"
}
```

---

## Audit

### Query Audit Events

Query immutable audit log.

**Endpoint:** `GET /api/audit/events`

**Query Parameters:**
- `session_id` (optional): Filter by session
- `event_type` (optional): Filter by event type
- `actor_id` (optional): Filter by actor
- `start_time` (optional): Filter by time range
- `end_time` (optional): Filter by time range
- `limit` (optional): Max results (default: 100)

**Response:** `200 OK`
```json
[
  {
    "event_id": "ghi78901-e89b-12d3-a456-426614174555",
    "timestamp": "2024-03-20T10:30:00Z",
    "event_type": "session.created",
    "actor_type": "user",
    "actor_id": "123e4567-e89b-12d3-a456-426614174000",
    "action_verb": "created",
    "entity_type": "session",
    "entity_id": "456e7890-e89b-12d3-a456-426614174111",
    "result_status": "success"
  }
]
```

---

## Health & Monitoring

### Health Check

Comprehensive health check of all services.

**Endpoint:** `GET /health`

**Response:** `200 OK`
```json
{
  "status": "healthy",
  "timestamp": "2024-03-20T12:00:00Z",
  "duration_ms": 45,
  "checks": {
    "database": {
      "status": "healthy",
      "response_time_ms": 15,
      "active_connections": 5
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 5,
      "used_memory_mb": 128.5
    },
    "llm_api": {
      "status": "healthy",
      "message": "LLM API configured"
    }
  }
}
```

---

### Readiness Check

Check if system is ready to accept traffic.

**Endpoint:** `GET /ready`

**Response:** `200 OK`
```json
{
  "status": "ready",
  "message": "System ready to accept traffic"
}
```

---

### Liveness Check

Check if application is alive.

**Endpoint:** `GET /alive`

**Response:** `200 OK`
```json
{
  "status": "alive",
  "timestamp": "2024-03-20T12:00:00Z"
}
```

---

### Metrics (Prometheus)

Prometheus-formatted metrics.

**Endpoint:** `GET /metrics`

**Response:** `200 OK` (text/plain)
```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/api/sessions",status="200"} 1523

# HELP sessions_active_total Number of active sessions
# TYPE sessions_active_total gauge
sessions_active_total 42

...
```

---

## Rate Limits

All endpoints are rate limited:

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/api/llm/call` | 10 requests | 60 seconds |
| `/api/sessions` | 50 requests | 60 seconds |
| `/api/jobs` | 100 requests | 60 seconds |
| All others | 100 requests | 60 seconds |

**Rate Limit Headers:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1710936000
```

**Rate Limit Exceeded:** `429 Too Many Requests`
```json
{
  "error": "Rate limit exceeded",
  "limit": 100,
  "window_seconds": 60,
  "retry_after": 60
}
```

---

## Error Responses

### Standard Error Format

```json
{
  "detail": {
    "error": "Error message",
    "error_code": "SPECIFIC_ERROR_CODE",
    "details": "Additional context"
  }
}
```

### HTTP Status Codes

- `200` OK - Request successful
- `201` Created - Resource created
- `400` Bad Request - Invalid request
- `401` Unauthorized - Invalid/missing auth
- `403` Forbidden - Insufficient permissions
- `404` Not Found - Resource not found
- `429` Too Many Requests - Rate limit exceeded
- `500` Internal Server Error - Server error
- `503` Service Unavailable - Service down

---

## Pagination

List endpoints support pagination:

```
GET /api/sessions?limit=50&offset=100
```

**Response Headers:**
```
X-Total-Count: 250
X-Page-Size: 50
X-Page-Offset: 100
```

---

## Versioning

API version is included in base URL:

```
https://api.ai-system.com/v1/...
```

Current version: `v1`

---

## SDKs & Client Libraries

### Python

```bash
pip install ai-system-sdk
```

```python
from ai_system import Client

client = Client(api_key="your_api_key")

# Create session
session = client.sessions.create(
    objective="Analyze data",
    llm_id="claude-3-sonnet-20240229"
)

# Call LLM
response = client.llm.call(
    session_id=session.id,
    messages=[{"role": "user", "content": "Hello"}]
)
```

### JavaScript

```bash
npm install @ai-system/sdk
```

```javascript
import { AISystemClient } from '@ai-system/sdk';

const client = new AISystemClient({ apiKey: 'your_api_key' });

// Create session
const session = await client.sessions.create({
  objective: 'Analyze data',
  llmId: 'claude-3-sonnet-20240229'
});

// Call LLM
const response = await client.llm.call({
  sessionId: session.id,
  messages: [{ role: 'user', content: 'Hello' }]
});
```

---

## Support

For API support:
- Documentation: https://docs.ai-system.com
- Email: api-support@ai-system.com
- Discord: https://discord.gg/ai-system
