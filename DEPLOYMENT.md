# Deployment Guide

Production deployment guide for AI System.

## Prerequisites

- Docker & Docker Compose
- PostgreSQL 15+ (managed or self-hosted)
- Redis 7+ (managed or self-hosted)
- Kubernetes cluster (optional, for scale)
- Domain name with SSL certificate

---

## Quick Deploy (Docker Compose)

### 1. Environment Setup

```bash
# Clone repository
git clone <repo-url>
cd ai-system

# Create production .env
cp .env.example .env.production

# Edit .env.production with production values
nano .env.production
```

### 2. Required Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:password@host:5432/ai_system

# Redis
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# LLM API
ANTHROPIC_API_KEY=sk-ant-...

# OIDC/Keycloak
OIDC_ISSUER=https://your-keycloak.com/realms/ai-system
OIDC_JWKS_URL=https://your-keycloak.com/realms/ai-system/protocol/openid-connect/certs
OIDC_AUDIENCE=ai-system-api

# MinIO/S3
MINIO_ENDPOINT=your-minio-endpoint
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...

# Security
SECRET_KEY=generate-strong-random-key
ALLOWED_ORIGINS=https://your-frontend.com

# Monitoring (optional)
SENTRY_DSN=...
```

### 3. Deploy Services

```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Run database migrations
docker-compose -f docker-compose.prod.yml run --rm api alembic upgrade head

# Start all services
docker-compose -f docker-compose.prod.yml up -d

# Check health
curl https://your-api.com/health
```

---

## Kubernetes Deployment

### 1. Create Namespace

```bash
kubectl create namespace ai-system
```

### 2. Deploy Database (if not using managed)

```bash
kubectl apply -f k8s/postgresql.yaml
```

### 3. Deploy Redis

```bash
kubectl apply -f k8s/redis.yaml
```

### 4. Create Secrets

```bash
kubectl create secret generic ai-system-secrets \
  --from-literal=database-url='postgresql://...' \
  --from-literal=anthropic-api-key='sk-ant-...' \
  --from-literal=redis-password='...' \
  -n ai-system
```

### 5. Deploy API

```bash
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/api-ingress.yaml
```

### 6. Deploy Workers

```bash
kubectl apply -f k8s/worker-deployment.yaml
```

### 7. Verify Deployment

```bash
kubectl get pods -n ai-system
kubectl get services -n ai-system
kubectl logs -f deployment/ai-system-api -n ai-system
```

---

## Scaling

### Horizontal Scaling

**API Servers:**
```bash
# Docker Compose
docker-compose -f docker-compose.prod.yml up -d --scale api=3

# Kubernetes
kubectl scale deployment ai-system-api --replicas=5 -n ai-system
```

**Workers:**
```bash
# Docker Compose
docker-compose -f docker-compose.prod.yml up -d --scale worker=5

# Kubernetes
kubectl scale deployment ai-system-worker --replicas=10 -n ai-system
```

### Vertical Scaling

Edit resource limits in docker-compose.prod.yml or k8s manifests:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

---

## Monitoring

### Health Checks

```bash
# API health
curl https://api.yoursite.com/health

# Expected response
{
  "status": "healthy",
  "services": {
    "api": "operational",
    "database": "connected",
    "redis": "connected"
  }
}
```

### Prometheus Metrics

Add to docker-compose.prod.yml:

```yaml
prometheus:
  image: prom/prometheus:latest
  volumes:
    - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"

grafana:
  image: grafana/grafana:latest
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=your-password
```

### Logging

**Centralized logging with ELK:**

```bash
# Add to docker-compose
filebeat:
  image: elastic/filebeat:8.0.0
  volumes:
    - ./logs:/logs
    - ./filebeat.yml:/usr/share/filebeat/filebeat.yml

elasticsearch:
  image: elasticsearch:8.0.0
  environment:
    - discovery.type=single-node

kibana:
  image: kibana:8.0.0
  ports:
    - "5601:5601"
```

---

## Backup & Recovery

### Database Backups

**Automated daily backups:**

```bash
# Cron job
0 2 * * * docker exec ai-system-postgres pg_dump -U ai_user ai_system | gzip > /backups/ai_system_$(date +\%Y\%m\%d).sql.gz
```

**Restore from backup:**

```bash
gunzip < backup.sql.gz | docker exec -i ai-system-postgres psql -U ai_user ai_system
```

### Redis Snapshots

Enable in redis.conf:
```conf
save 900 1
save 300 10
save 60 10000
```

---

## Security Checklist

- [ ] All secrets in environment variables (not in code)
- [ ] SSL/TLS enabled for all endpoints
- [ ] Database encryption at rest
- [ ] Redis AUTH enabled
- [ ] API rate limiting configured
- [ ] CORS properly configured
- [ ] Firewall rules in place
- [ ] Regular security updates
- [ ] Audit logs monitored
- [ ] Backup encryption enabled

---

## Performance Tuning

### Database

```sql
-- Add indices for common queries
CREATE INDEX CONCURRENTLY idx_audit_event_session
  ON audit_event(context->>'session_id');

CREATE INDEX CONCURRENTLY idx_job_created_status
  ON job(created_at, status);

-- Connection pooling
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '256MB';
```

### Redis

```conf
maxmemory 2gb
maxmemory-policy allkeys-lru
```

### API

```python
# In main.py, add caching
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

@app.on_event("startup")
async def startup():
    redis_client = aioredis.from_url("redis://localhost")
    FastAPICache.init(RedisBackend(redis_client), prefix="fastapi-cache")
```

---

## Troubleshooting

### API Not Responding

```bash
# Check logs
docker logs ai-system-api

# Check database connection
docker exec ai-system-postgres psql -U ai_user -d ai_system -c "SELECT 1"

# Restart API
docker-compose restart api
```

### Worker Not Processing Jobs

```bash
# Check worker logs
docker logs ai-system-worker

# Check Redis queue
docker exec ai-system-redis redis-cli LLEN job_queue:llm_call

# Restart worker
docker-compose restart worker
```

### High Database Load

```bash
# Check active connections
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*) FROM pg_stat_activity"

# Check slow queries
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT query, calls, total_time FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10"
```

---

## Maintenance

### Regular Tasks

**Daily:**
- Monitor error rates
- Check disk space
- Review audit logs for anomalies

**Weekly:**
- Database vacuum and analyze
- Review and archive old audit logs
- Check SSL certificate expiry

**Monthly:**
- Security updates
- Performance review
- Cost optimization review

---

## Rollback Procedure

### API Rollback

```bash
# Docker Compose
docker-compose -f docker-compose.prod.yml down
git checkout <previous-version>
docker-compose -f docker-compose.prod.yml up -d

# Kubernetes
kubectl rollout undo deployment/ai-system-api -n ai-system
```

### Database Migration Rollback

```bash
# Check current version
alembic current

# Rollback one version
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision-id>
```

---

## Support

For production issues:
- Check logs first
- Review monitoring dashboards
- Consult troubleshooting section
- Create incident report

**Emergency contacts:**
- On-call engineer: [contact info]
- Database admin: [contact info]
- Security team: [contact info]
