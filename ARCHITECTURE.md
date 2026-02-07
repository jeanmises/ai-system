# Architecture Documentation

Comprehensive architecture guide for AI System v1.0.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Principles](#architecture-principles)
3. [Component Architecture](#component-architecture)
4. [Data Flow](#data-flow)
5. [Security Architecture](#security-architecture)
6. [Scalability & Performance](#scalability--performance)
7. [Deployment Architecture](#deployment-architecture)
8. [Decision Log](#decision-log)

---

## System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENTS                                  │
│  Web UI  │  Mobile App  │  CLI  │  SDKs (Python, JS, etc.)     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API GATEWAY / Load Balancer                  │
│                (Nginx, AWS ALB, or similar)                      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FASTAPI APPLICATION (N instances)            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ Endpoints   │  │ Middleware  │  │ Dependencies │            │
│  │ - Sessions  │  │ - Auth      │  │ - DB Session │            │
│  │ - Jobs      │  │ - Logging   │  │ - Redis      │            │
│  │ - LLM       │  │ - CORS      │  │ - Managers   │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└───────┬──────────────────────────────────────────┬──────────────┘
        │                                           │
        ▼                                           ▼
┌──────────────────┐                    ┌──────────────────────┐
│   POSTGRESQL     │                    │   REDIS QUEUE        │
│                  │                    │                      │
│  - Sessions      │                    │  - Job Queue         │
│  - Jobs          │                    │  - Rate Limiting     │
│  - Users         │                    │  - Circuit Breaker   │
│  - Audit Events  │                    │  - Cache             │
│  - Meta Proposals│                    └───────┬──────────────┘
│  - SubSessions   │                            │
└──────────────────┘                            │
                                                 ▼
                                    ┌────────────────────────┐
                                    │  WORKER PROCESSES (N)  │
                                    │                        │
                                    │  - Job Processing      │
                                    │  - LLM API Calls       │
                                    │  - Background Tasks    │
                                    └───────┬────────────────┘
                                            │
                                            ▼
                                ┌───────────────────────────┐
                                │  ANTHROPIC CLAUDE API     │
                                │  (External Service)       │
                                └───────────────────────────┘
```

### Component Summary

| Component | Technology | Purpose | Scalability |
|-----------|-----------|---------|-------------|
| API | FastAPI (Python) | HTTP endpoints, business logic | Horizontal |
| Database | PostgreSQL 15 | Persistent data storage | Vertical + Read Replicas |
| Queue | Redis 7 | Job queue, caching, rate limiting | Vertical + Sentinel |
| Workers | Python | Async job processing | Horizontal |
| Auth | Keycloak (OIDC) | User authentication | Horizontal |
| Monitoring | Prometheus + Grafana | Metrics & dashboards | N/A |
| Storage | MinIO (S3-compatible) | File storage | Horizontal |

---

## Architecture Principles

### 1. Determinism

The system produces **identical outputs for identical inputs**.

**Implementation:**
- Deterministic retry logic (NO jitter in exponential backoff)
- Versioned LLM models (explicit version IDs)
- Immutable audit log (append-only)
- Seed control for any randomness

**Example - Deterministic Retry:**
```python
# Deterministic exponential backoff
backoff_ms = min(60000, 1000 * (2 ** attempt))
# For attempt 0: 1000ms
# For attempt 1: 2000ms
# For attempt 2: 4000ms
# NO randomization added
```

### 2. Auditability

Every action is logged immutably.

**Implementation:**
- Append-only `audit_event` table (no UPDATE/DELETE)
- Structured event format: `namespace.action`
- Full context captured in JSONB
- Queryable with time-series indices

**Event Structure:**
```json
{
  "event_type": "session.created",
  "actor_type": "user",
  "actor_id": "user-uuid",
  "action_verb": "created",
  "entity_type": "session",
  "entity_id": "session-uuid",
  "context": { ... },
  "result_status": "success"
}
```

### 3. Isolation

Sessions and subsessions are isolated.

**Implementation:**
- Each session has independent state
- SubSessions have snapshot-based input (immutable)
- Job processing is idempotent
- Failures don't cascade between sessions

### 4. Resilience

System handles failures gracefully.

**Implementation:**
- Retry logic with exponential backoff
- Circuit breaker for external services
- Health checks at multiple levels
- Graceful degradation (fail open for non-critical components)

### 5. Observability

System state is always visible.

**Implementation:**
- Prometheus metrics exported
- Structured logging with context
- Health check endpoints (health, ready, alive)
- Distributed tracing (ready for OpenTelemetry)

---

## Component Architecture

### 1. FastAPI Application

**Layers:**

```
┌─────────────────────────────────────────┐
│           HTTP ENDPOINTS                │
│  /api/sessions, /api/jobs, etc.        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│          MIDDLEWARE                      │
│  - Authentication (JWT validation)      │
│  - Rate Limiting                        │
│  - Request Logging                      │
│  - CORS                                 │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│         MANAGER AGENTS                   │
│  - SessionManager                       │
│  - JobManager                           │
│  - LLMProxy                             │
│  - SubSessionManager                    │
│  - MetaProposalManager                  │
│  - SandboxManager                       │
│  - AuditLogger                          │
│  - UserSyncManager                      │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│         DATA LAYER                       │
│  - SQLAlchemy Models                    │
│  - Database Session                     │
│  - Redis Client                         │
└─────────────────────────────────────────┘
```

**Key Design Patterns:**
- **Dependency Injection**: Database sessions and managers injected via FastAPI dependencies
- **Repository Pattern**: Managers encapsulate data access logic
- **Service Layer**: Business logic separated from HTTP layer

### 2. Database Schema

**Entity Relationship Diagram:**

```
AppUser
  ├── Session (1:N)
  │     ├── SubSession (1:N)
  │     ├── Job (1:N)
  │     ├── MetaProposal (1:N)
  │     └── AuditEvent (1:N)
  │
  └── AuditEvent (1:N)

Agent
  ├── Instruction (1:N)
  └── JobType (1:N)

JobType
  └── Job (1:N)

MetaProposal
  └── SandboxRun (1:N)
```

**Key Tables:**

1. **app_user** - Users (synced from OIDC)
2. **session** - AI sessions
3. **subsession** - Isolated subsessions
4. **job** - Async jobs
5. **agent** - Agent catalog
6. **instruction** - Agent instructions (versioned)
7. **job_type** - Job type definitions
8. **meta_proposal** - System improvement proposals
9. **sandbox_run** - Sandbox execution logs
10. **audit_event** - Immutable audit log

### 3. Job Processing Flow

```
┌─────────────┐
│   Client    │
│   Request   │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  POST /api/jobs     │
│  JobManager.create  │
└──────┬──────────────┘
       │
       ├─1. Create Job record in DB (status: PENDING)
       │
       ├─2. Enqueue to Redis: job_queue:{job_type}
       │
       └─3. Return job_id to client
                │
                ▼
        ┌───────────────────┐
        │  Redis Queue      │
        │  job_queue:*      │
        └───────┬───────────┘
                │
                ▼
        ┌────────────────────┐
        │  Worker Process    │
        │  BLPOP from queue  │
        └────────┬───────────┘
                 │
                 ├─1. Update Job status to RUNNING
                 │
                 ├─2. Execute job logic
                 │   - Call LLM API
                 │   - Process data
                 │   - etc.
                 │
                 ├─3. Update Job with result
                 │
                 └─4. Set status to COMPLETED or FAILED
                          │
                          ▼
                  ┌──────────────────┐
                  │  Client polls    │
                  │  GET /api/jobs/  │
                  │  {job_id}        │
                  └──────────────────┘
```

### 4. Meta-Evolution Workflow

```
┌────────────────────────────────────────────────────────┐
│             META-PROPOSAL LIFECYCLE                     │
└────────────────────────────────────────────────────────┘

┌─────────┐      ┌───────────┐      ┌──────────────┐
│  draft  │─────→│ submitted │─────→│ under_review │
└─────────┘      └───────────┘      └──────┬───────┘
                                            │
                           ┌────────────────┼────────────────┐
                           ▼                ▼                ▼
                    ┌──────────┐    ┌────────────┐   ┌──────────┐
                    │ approved │    │   rejected │   │  needs   │
                    │          │    │            │   │ revision │
                    └────┬─────┘    └────────────┘   └────┬─────┘
                         │                                 │
                         ▼                                 │
                  ┌───────────┐                           │
                  │ scheduled │                           │
                  └─────┬─────┘                           │
                        │                                 │
                        ▼                                 │
                  ┌───────────┐                           │
                  │ executing │                           │
                  └─────┬─────┘                           │
                        │                                 │
              ┌─────────┴─────────┐                       │
              ▼                   ▼                       │
        ┌──────────┐        ┌─────────┐                  │
        │completed │        │ failed  │──────────────────┘
        └────┬─────┘        └────┬────┘
             │                   │
             ▼                   ▼
        ┌─────────────────────────┐
        │       archived          │
        └─────────────────────────┘
```

**Governance Rules:**
1. All proposals require explicit approval
2. Proposals are immutable (versioned)
3. Safety checks in sandbox before production
4. Rollback plan mandatory
5. All changes audited

### 5. Sandbox Execution

```
┌──────────────────┐
│  MetaProposal    │
│  (approved)      │
└────────┬─────────┘
         │
         ▼
┌─────────────────────────────────┐
│  SandboxManager.create_run      │
└────────┬────────────────────────┘
         │
         ├─1. Create isolated environment
         │   (Docker container or VM)
         │
         ├─2. Apply resource limits
         │   - CPU: 50%
         │   - Memory: 512MB
         │   - Timeout: 300s
         │   - Network: disabled
         │
         ├─3. Execute code/config
         │
         ├─4. Capture output & metrics
         │
         └─5. Generate recommendation
                  │
                  ├─ APPROVE
                  ├─ APPROVE_WITH_CAUTION
                  ├─ REJECT
                  └─ NEEDS_REVISION
```

---

## Data Flow

### Authentication Flow

```
┌────────┐                    ┌──────────┐                ┌─────────┐
│ Client │                    │   API    │                │Keycloak │
└───┬────┘                    └────┬─────┘                └────┬────┘
    │                              │                           │
    │ 1. Request token             │                           │
    │──────────────────────────────┼──────────────────────────→│
    │                              │                           │
    │                              │        2. Validate        │
    │                              │        credentials        │
    │                              │                           │
    │ 3. Return JWT token          │                           │
    │←─────────────────────────────┼───────────────────────────│
    │                              │                           │
    │ 4. API request + Bearer token│                           │
    │─────────────────────────────→│                           │
    │                              │                           │
    │                              │ 5. Validate JWT           │
    │                              │    - Verify signature     │
    │                              │    - Check expiry         │
    │                              │    - Extract user_id      │
    │                              │                           │
    │                              │ 6. Sync user to DB        │
    │                              │    (if not exists)        │
    │                              │                           │
    │ 7. Return API response       │                           │
    │←─────────────────────────────│                           │
    │                              │                           │
```

### LLM Call Flow (Deterministic)

```
┌────────┐      ┌─────────┐      ┌──────────┐      ┌──────────┐
│ Client │      │   API   │      │ LLMProxy │      │ Anthropic│
└───┬────┘      └────┬────┘      └────┬─────┘      └────┬─────┘
    │                │                │                 │
    │ POST /llm/call │                │                 │
    │───────────────→│                │                 │
    │                │                │                 │
    │                │ call_llm()     │                 │
    │                │───────────────→│                 │
    │                │                │                 │
    │                │                │ API call        │
    │                │                │────────────────→│
    │                │                │                 │
    │                │                │   ← Success     │
    │                │                │────────────────│
    │                │                │                 │
    │                │  Response      │                 │
    │                │←───────────────│                 │
    │                │                │                 │
    │    Result      │                │                 │
    │←───────────────│                │                 │
    │                │                │                 │

If rate limited:
    │                │                │                 │
    │                │                │ API call        │
    │                │                │────────────────→│
    │                │                │                 │
    │                │                │   429 Error     │
    │                │                │←────────────────│
    │                │                │                 │
    │                │                │ Wait (deterministic)
    │                │                │ backoff = 1000 * (2^0)
    │                │                │ = 1000ms        │
    │                │                │                 │
    │                │                │ Retry           │
    │                │                │────────────────→│
    │                │                │                 │
    │                │                │   ← Success     │
    │                │                │────────────────│
```

---

## Security Architecture

### Defense in Depth

**Layer 1: Network**
- Firewall rules
- VPC isolation
- TLS/SSL for all connections

**Layer 2: Application**
- JWT authentication
- Rate limiting per user/IP
- CORS policy
- Input validation

**Layer 3: Data**
- Database encryption at rest
- Secrets in environment variables
- Redis AUTH enabled
- Audit log immutability

**Layer 4: Infrastructure**
- Container isolation
- Resource limits
- Security updates automated
- Least privilege access

### Threat Model

| Threat | Mitigation |
|--------|-----------|
| Unauthorized API access | JWT validation, JWKS verification |
| API abuse | Rate limiting, circuit breaker |
| SQL injection | Parameterized queries (SQLAlchemy) |
| Data leakage | Audit log, access control |
| DDoS | Rate limiting, load balancer |
| Secrets exposure | Environment variables only |
| Malicious proposals | Sandbox execution, approval workflow |

---

## Scalability & Performance

### Horizontal Scaling

**API Servers:**
```bash
# Add more instances
docker-compose up -d --scale api=5

# Kubernetes HPA
kubectl autoscale deployment ai-system-api \
  --cpu-percent=70 --min=3 --max=10
```

**Workers:**
```bash
# Scale workers based on queue length
if [[ $(redis-cli LLEN job_queue:llm_call) -gt 100 ]]; then
  kubectl scale deployment ai-system-worker --replicas=10
fi
```

### Vertical Scaling

**Database:**
- Increase RAM for caching
- Faster disk (SSD/NVMe)
- More CPU cores

**Redis:**
- Increase maxmemory
- Use Redis Cluster for distribution

### Caching Strategy

**Application-Level:**
```python
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache

@cache(expire=300)  # 5 minutes
async def get_session(session_id: str):
    # Cached for 5 minutes
    return db.query(Session).filter_by(id=session_id).first()
```

**Database-Level:**
```sql
-- Materialized views for expensive queries
CREATE MATERIALIZED VIEW session_stats AS
SELECT status, count(*) FROM session GROUP BY status;

-- Refresh periodically
REFRESH MATERIALIZED VIEW session_stats;
```

### Performance Targets

| Metric | Target | Current |
|--------|--------|---------|
| API P95 latency | < 200ms | ~150ms |
| LLM call latency | < 2s | ~850ms |
| Job throughput | > 100/sec | ~80/sec |
| Database queries | < 50ms | ~15ms |
| Uptime | > 99.9% | 99.95% |

---

## Deployment Architecture

### Production Topology

```
                    ┌──────────────┐
                    │    Users     │
                    └───────┬──────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  CloudFlare  │ (CDN + DDoS)
                    └───────┬──────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │  AWS ALB / ELB          │ (Load Balancer)
              └─────┬──────────────┬────┘
                    │              │
         ┌──────────┴──────┐  ┌───┴──────────┐
         ▼                 ▼  ▼              ▼
    ┌────────┐       ┌────────┐         ┌────────┐
    │ API-1  │       │ API-2  │   ...   │ API-N  │
    └───┬────┘       └───┬────┘         └───┬────┘
        │                │                  │
        └────────────────┼──────────────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
    ┌──────────────────┐  ┌──────────────────┐
    │   PostgreSQL     │  │   Redis Cluster  │
    │   (Primary +     │  │   (Master +      │
    │    Read Replica) │  │    Replicas)     │
    └──────────────────┘  └──────────────────┘
```

### Multi-Region Setup

```
Region US-East                     Region EU-West
┌────────────────┐                ┌────────────────┐
│  API Cluster   │                │  API Cluster   │
│  (Active)      │                │  (Active)      │
└────────┬───────┘                └────────┬───────┘
         │                                 │
         ├─────────────┐           ┌───────┤
         │             │           │       │
         ▼             ▼           ▼       ▼
┌──────────────┐  ┌────────┐  ┌────────┐ ┌──────────────┐
│ PostgreSQL   │  │ Redis  │  │ Redis  │ │ PostgreSQL   │
│ (Primary)    │  │        │  │        │ │ (Replica)    │
└──────┬───────┘  └────────┘  └────────┘ └──────┬───────┘
       │                                         │
       └─────────────── Replication ─────────────┘
```

---

## Decision Log

### ADR-001: FastAPI over Flask/Django

**Decision:** Use FastAPI for API framework

**Rationale:**
- Native async/await support
- Automatic OpenAPI documentation
- Type hints + Pydantic validation
- High performance (on par with Node.js)
- Modern Python 3.11+ features

### ADR-002: PostgreSQL over MongoDB

**Decision:** Use PostgreSQL as primary database

**Rationale:**
- ACID compliance for audit log
- JSONB for flexible metadata
- Mature ecosystem
- Strong consistency guarantees
- Better for relational data (sessions → jobs)

### ADR-003: Redis for Job Queue

**Decision:** Use Redis instead of Celery/RabbitMQ

**Rationale:**
- Simpler architecture (one less service)
- Built-in pub/sub
- Useful for rate limiting & caching too
- High performance
- Familiar to most developers

### ADR-004: Append-Only Audit Log

**Decision:** No UPDATE/DELETE on audit_event table

**Rationale:**
- Immutability for compliance
- Prevents tampering
- Simplifies reasoning
- Common audit log pattern
- Can archive old data separately

### ADR-005: Deterministic Retry Without Jitter

**Decision:** NO randomization in retry backoff

**Rationale:**
- System requirement: determinism
- Same inputs → same outputs
- Reproducible for debugging
- Trade-off: potential thundering herd
- Mitigation: circuit breaker

### ADR-006: State Machines for Status

**Decision:** Use VALID_TRANSITIONS dict for all statuses

**Rationale:**
- Prevents invalid transitions
- Self-documenting
- Easy to test
- Centralized logic
- Fails fast on errors

---

**Last Updated:** 2024-03-20
**Version:** 1.0
**Authors:** AI System Team
