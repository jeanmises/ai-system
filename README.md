# AI System v1.0

**Deterministic AI System with Governance and Self-Evolution**

Production-ready system for managing AI sessions, jobs, and self-evolution proposals with complete auditability and deterministic behavior.

---

## Features

- **Deterministic Execution**: Same inputs always produce same outputs
- **Complete Audit Trail**: Immutable, append-only audit log for all actions
- **Async Job Processing**: Redis-based job queue with worker pools
- **LLM Integration**: Anthropic Claude API with deterministic retry
- **Session Management**: Isolated sessions with subsession support
- **Meta-Evolution**: Self-improvement proposals with governance workflow
- **Sandbox Execution**: Safe testing environment for changes
- **OIDC Authentication**: Keycloak integration with JWT validation
- **Production-Ready**: Health checks, metrics, rate limiting, circuit breakers
- **Comprehensive Monitoring**: Prometheus + Grafana dashboards

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- PostgreSQL 15+ (or use Docker)
- Redis 7+ (or use Docker)
- Anthropic API key

### 1. Clone & Setup

```bash
# Clone repository
git clone <repo-url>
cd ai-system

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 2. Start Services

```bash
# Start all services
docker-compose up -d

# Check services are running
docker-compose ps

# Watch logs
docker-compose logs -f api worker
```

### 3. Initialize Database

```bash
# Run migrations
docker-compose exec api alembic upgrade head

# Verify
docker-compose exec postgres psql -U ai_user -d ai_system -c "\dt"
```

### 4. Verify Health

```bash
# Health check
curl http://localhost:8000/health | jq

# API documentation
open http://localhost:8000/docs
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLIENTS                                 │
│   Web UI  │  Mobile  │  CLI  │  SDKs                        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                FASTAPI APPLICATION                           │
│  - Sessions    - Jobs    - LLM Proxy    - Audit            │
│  - SubSessions - Meta-Proposals - Sandbox                   │
└──────┬──────────────────────────────────────────┬───────────┘
       │                                           │
       ▼                                           ▼
┌──────────────────┐                    ┌──────────────────┐
│   POSTGRESQL     │                    │   REDIS QUEUE    │
│  - Sessions      │                    │  - Job Queue     │
│  - Jobs          │                    │  - Rate Limit    │
│  - Audit Events  │                    │  - Circuit Break │
│  - Proposals     │                    └────────┬─────────┘
└──────────────────┘                             │
                                                 ▼
                                      ┌─────────────────────┐
                                      │  WORKER PROCESSES   │
                                      │  - Job Processing   │
                                      │  - LLM API Calls    │
                                      └──────────┬──────────┘
                                                 │
                                                 ▼
                                      ┌─────────────────────┐
                                      │  ANTHROPIC API      │
                                      │  (Claude Models)    │
                                      └─────────────────────┘
```

---

## Core Concepts

### 1. Sessions

Sessions represent AI conversation contexts.

```python
# Create session
POST /api/sessions
{
  "objective": "Analyze financial data",
  "llm_id": "claude-3-sonnet-20240229",
  "llm_version": "20240229"
}
```

**States:** `active` → `paused` → `archived`

### 2. Jobs

Asynchronous tasks processed by workers.

```python
# Create job
POST /api/jobs
{
  "session_id": "...",
  "job_type": "llm_call",
  "payload": {...}
}
```

**States:** `PENDING` → `RUNNING` → `COMPLETED`/`FAILED`

### 3. SubSessions

Isolated subsessions for parallel processing.

```python
# Create subsession
POST /api/sessions/{id}/subsessions
{
  "objective": "Analyze section 1",
  "input_snapshot": {...}
}
```

### 4. Meta-Proposals

System improvement proposals with governance.

```python
# Create proposal
POST /api/meta-proposals
{
  "title": "Add caching layer",
  "category": "config_change",
  "proposed_changes": {...},
  "impact_assessment": {...},
  "rollback_plan": {...}
}
```

**Workflow:** `draft` → `submitted` → `under_review` → `approved` → `executing` → `completed`

### 5. Audit Log

Immutable, append-only audit trail.

```python
# Query events
GET /api/audit/events?session_id=...
```

**Format:** `namespace.action` (e.g., `session.created`, `job.completed`)

---

## API Examples

### Authentication

```bash
# Get token from Keycloak
TOKEN=$(curl -X POST "http://localhost:8080/realms/ai-system/protocol/openid-connect/token" \
  -d "client_id=ai-system-api" \
  -d "username=admin" \
  -d "password=admin" \
  -d "grant_type=password" | jq -r .access_token)

# Use token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/sessions
```

### Create Session & Call LLM

```bash
# Create session
SESSION=$(curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user",
    "objective": "Test",
    "llm_id": "claude-3-haiku-20240307",
    "llm_version": "20240307"
  }' | jq -r .session_id)

# Call LLM
curl -X POST http://localhost:8000/api/llm/call \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION\",
    \"model\": \"claude-3-haiku-20240307\",
    \"messages\": [{\"role\": \"user\", \"content\": \"Hello!\"}],
    \"max_tokens\": 100
  }" | jq
```

### Create & Monitor Job

```bash
# Create job
JOB=$(curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION\",
    \"job_type\": \"llm_call\",
    \"payload\": {\"test\": \"data\"}
  }" | jq -r .job_id)

# Poll job status
watch -n 1 "curl -s http://localhost:8000/api/jobs/$JOB | jq '.status'"
```

---

## Testing

### Run Unit Tests

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-asyncio

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

### Run Integration Tests

```bash
# Ensure services are running
docker-compose up -d

# Run integration tests
pytest tests/test_integration.py -v
```

### Run Performance Tests

```bash
# Install locust
pip install locust

# Run load test (interactive)
locust -f tests/test_performance.py --host=http://localhost:8000

# Run headless
locust -f tests/test_performance.py --host=http://localhost:8000 \
  --users 100 --spawn-rate 10 --run-time 5m --headless
```

### Run Benchmark

```bash
# Quick benchmark
python tests/test_performance.py
```

---

## Monitoring

### Prometheus Metrics

```bash
# View metrics
curl http://localhost:8000/metrics

# Key metrics:
# - http_requests_total
# - http_request_duration_seconds
# - sessions_active_total
# - jobs_total
# - llm_calls_total
```

### Grafana Dashboard

```bash
# Access Grafana (if deployed)
open http://localhost:3000

# Default credentials
Username: admin
Password: admin

# Import dashboard
Upload: monitoring/grafana-dashboard.json
```

### Health Checks

```bash
# Comprehensive health check
curl http://localhost:8000/health | jq

# Readiness (for load balancer)
curl http://localhost:8000/ready

# Liveness (for Kubernetes)
curl http://localhost:8000/alive
```

---

## Deployment

### Docker Compose (Simple)

```bash
# Production mode
docker-compose -f docker-compose.prod.yml up -d

# Scale components
docker-compose -f docker-compose.prod.yml up -d --scale api=3 --scale worker=5
```

### Kubernetes (Production)

```bash
# Create namespace
kubectl create namespace ai-system

# Deploy services
kubectl apply -f k8s/

# Scale
kubectl scale deployment ai-system-api --replicas=5 -n ai-system
kubectl scale deployment ai-system-worker --replicas=10 -n ai-system

# Monitor
kubectl get pods -n ai-system -w
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete deployment guide.

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:password@host:5432/ai_system

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=optional

# LLM API
ANTHROPIC_API_KEY=sk-ant-...

# OIDC
OIDC_ISSUER=http://keycloak:8080/realms/ai-system
OIDC_JWKS_URL=http://keycloak:8080/realms/ai-system/protocol/openid-connect/certs
OIDC_AUDIENCE=ai-system-api

# Security
SECRET_KEY=generate-random-key
ALLOWED_ORIGINS=http://localhost:3000,https://app.example.com

# Monitoring (optional)
SENTRY_DSN=...
```

### Rate Limits

Configure in `middleware/rate_limiter.py`:

```python
endpoint_limits = {
    "/api/llm/call": (10, 60),    # 10 req/min
    "/api/sessions": (50, 60),    # 50 req/min
    "/api/jobs": (100, 60),       # 100 req/min
}
```

---

## Maintenance

### Backup Database

```bash
# Automated daily backup
0 2 * * * docker exec ai-system-postgres pg_dump -U ai_user ai_system | \
  gzip > /backups/ai_system_$(date +\%Y\%m\%d).sql.gz
```

### Restore Database

```bash
gunzip < backup.sql.gz | docker exec -i ai-system-postgres \
  psql -U ai_user ai_system
```

### Archive Old Data

```sql
-- Archive old audit events (>90 days)
DELETE FROM audit_event WHERE timestamp < now() - interval '90 days';

-- Archive completed jobs (>30 days)
DELETE FROM job WHERE status = 'COMPLETED' AND created_at < now() - interval '30 days';

-- Vacuum
VACUUM FULL;
```

### Update System

```bash
# Pull latest code
git pull

# Rebuild images
docker-compose build

# Run migrations
docker-compose exec api alembic upgrade head

# Restart services
docker-compose restart api worker
```

---

## Troubleshooting

### API Not Responding

```bash
# Check logs
docker logs ai-system-api --tail=100

# Restart API
docker restart ai-system-api
```

### Workers Not Processing

```bash
# Check worker logs
docker logs ai-system-worker --tail=100

# Check queue length
docker exec ai-system-redis redis-cli LLEN "job_queue:llm_call"

# Restart workers
docker restart ai-system-worker
```

### Database Issues

```bash
# Check connections
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"

# Kill idle connections
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE state = 'idle' AND state_change < now() - interval '5 minutes';"
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for complete troubleshooting guide.

---

## Documentation

- [API Reference](API_REFERENCE.md) - Complete API documentation with examples
- [Architecture](ARCHITECTURE.md) - System architecture and design decisions
- [Deployment Guide](DEPLOYMENT.md) - Production deployment instructions
- [Troubleshooting](TROUBLESHOOTING.md) - Common issues and solutions
- [OpenAPI Docs](http://localhost:8000/docs) - Interactive API documentation

---

## Development

### Setup Development Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

### Code Quality

```bash
# Format code
black .
isort .

# Lint
flake8 .

# Type check
mypy . --ignore-missing-imports

# Security scan
bandit -r . -f json -o bandit-report.json
```

### Database Migrations

```bash
# Create migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

---

## CI/CD

GitHub Actions workflow automatically:
- Runs linting and tests
- Performs security scans
- Builds Docker images
- Deploys to staging/production

See [.github/workflows/ci.yml](.github/workflows/ci.yml) for configuration.

---

## Performance

### Benchmarks

| Operation | Latency (P95) | Throughput |
|-----------|---------------|------------|
| Create Session | ~50ms | 200 req/s |
| Create Job | ~30ms | 300 req/s |
| LLM Call | ~850ms | 10 req/s |
| Query Audit | ~100ms | 100 req/s |

### Scaling

- **API**: Horizontally scalable (add more instances)
- **Workers**: Horizontally scalable (add more workers)
- **Database**: Vertically scalable + read replicas
- **Redis**: Vertically scalable + clustering

---

## Security

- JWT authentication with JWKS validation
- Rate limiting per endpoint
- Circuit breaker for external services
- SQL injection prevention (parameterized queries)
- CORS configuration
- Secrets in environment variables only
- Immutable audit log
- Sandbox execution for proposals

See security checklist in [DEPLOYMENT.md](DEPLOYMENT.md).

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- **Documentation**: All docs in this repository
- **Issues**: GitHub Issues
- **Email**: support@ai-system.com
- **Discord**: https://discord.gg/ai-system

---

## Roadmap

### Phase 1: Core System (COMPLETED ✅)
- ✅ Sessions, Jobs, Audit
- ✅ LLM Integration
- ✅ Worker System
- ✅ Authentication

### Phase 2: Advanced Features (COMPLETED ✅)
- ✅ SubSessions
- ✅ Meta-Proposals
- ✅ Sandbox Execution

### Phase 3: Production Hardening (COMPLETED ✅)
- ✅ Monitoring & Metrics
- ✅ Health Checks
- ✅ Rate Limiting
- ✅ Circuit Breakers

### Phase 4: Future Enhancements
- [ ] GraphQL API
- [ ] WebSocket support for real-time updates
- [ ] Multi-tenant support
- [ ] Advanced analytics dashboard
- [ ] Plugin system for custom agents
- [ ] Distributed tracing (OpenTelemetry)

---

## Contributors

- AI System Team

---

## Changelog

### v1.0.0 (2024-03-20)
- Initial production release
- Complete session and job management
- LLM integration with Anthropic Claude
- Meta-proposals and sandbox execution
- Comprehensive monitoring and observability
- Production-ready deployment configurations

---

**Built with ❤️ using FastAPI, PostgreSQL, Redis, and Anthropic Claude**
