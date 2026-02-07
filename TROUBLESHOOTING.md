# Troubleshooting Guide

Production troubleshooting guide for AI System operators.

---

## Quick Diagnosis

### System Health Check

```bash
# Check overall health
curl http://localhost:8000/health | jq

# Check specific service
curl http://localhost:8000/ready
curl http://localhost:8000/alive
```

### Service Status

```bash
# Docker Compose
docker-compose ps

# Kubernetes
kubectl get pods -n ai-system
kubectl get services -n ai-system
```

---

## Common Issues

### 1. API Not Responding

#### Symptoms
- HTTP timeouts
- Connection refused errors
- 502/503 errors from load balancer

#### Diagnosis

```bash
# Check if API container is running
docker ps | grep ai-system-api

# Check API logs
docker logs ai-system-api --tail=100

# Check resource usage
docker stats ai-system-api

# Check if port is open
netstat -tuln | grep 8000
```

#### Common Causes & Solutions

**Cause: Container crashed**
```bash
# Check exit code
docker inspect ai-system-api | grep ExitCode

# Restart container
docker restart ai-system-api

# If using Kubernetes
kubectl describe pod ai-system-api-xxx -n ai-system
kubectl logs ai-system-api-xxx -n ai-system --previous
```

**Cause: Out of memory**
```bash
# Check memory usage
docker stats ai-system-api --no-stream

# Increase memory limit in docker-compose.yml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 2G  # Increase this
```

**Cause: Database connection exhausted**
```bash
# Check active connections
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*) FROM pg_stat_activity;"

# Kill idle connections
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE state = 'idle' AND state_change < now() - interval '5 minutes';"
```

---

### 2. Worker Not Processing Jobs

#### Symptoms
- Jobs stuck in PENDING status
- Queue length increasing
- No worker activity in logs

#### Diagnosis

```bash
# Check if worker is running
docker ps | grep ai-system-worker

# Check worker logs
docker logs ai-system-worker --tail=100 -f

# Check Redis queue length
docker exec ai-system-redis redis-cli LLEN "job_queue:llm_call"

# List all keys
docker exec ai-system-redis redis-cli KEYS "job_queue:*"
```

#### Solutions

**Restart worker:**
```bash
docker restart ai-system-worker
```

**Scale workers:**
```bash
# Docker Compose
docker-compose up -d --scale worker=3

# Kubernetes
kubectl scale deployment ai-system-worker --replicas=5 -n ai-system
```

**Clear stuck jobs (use with caution):**
```bash
# View pending jobs
docker exec ai-system-redis redis-cli LRANGE "job_queue:llm_call" 0 -1

# Clear specific queue
docker exec ai-system-redis redis-cli DEL "job_queue:llm_call"
```

---

### 3. Database Connection Issues

#### Symptoms
- "could not connect to server" errors
- Slow queries
- Connection pool exhausted

#### Diagnosis

```bash
# Test database connection
docker exec ai-system-postgres pg_isready

# Check active connections
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"

# Check slow queries
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT pid, now() - query_start AS duration, query
      FROM pg_stat_activity
      WHERE state = 'active' AND now() - query_start > interval '5 seconds';"
```

#### Solutions

**Restart database (use with caution):**
```bash
docker restart ai-system-postgres

# Wait for database to be ready
until docker exec ai-system-postgres pg_isready; do
  sleep 1
done
```

**Increase connection pool:**
```sql
-- Connect to database
docker exec -it ai-system-postgres psql -U ai_user -d ai_system

-- Increase max connections
ALTER SYSTEM SET max_connections = 200;

-- Restart PostgreSQL
\q
docker restart ai-system-postgres
```

**Kill long-running queries:**
```sql
-- Find long-running queries
SELECT pid, query_start, state, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '1 minute';

-- Kill specific query
SELECT pg_terminate_backend(12345);  -- Replace with actual PID
```

---

### 4. Redis Connection Issues

#### Symptoms
- Redis connection errors
- Job queue not working
- Rate limiter failing

#### Diagnosis

```bash
# Test Redis connection
docker exec ai-system-redis redis-cli ping

# Check Redis info
docker exec ai-system-redis redis-cli INFO

# Check memory usage
docker exec ai-system-redis redis-cli INFO memory

# Check connected clients
docker exec ai-system-redis redis-cli CLIENT LIST
```

#### Solutions

**Restart Redis:**
```bash
docker restart ai-system-redis
```

**Clear Redis data (development only):**
```bash
docker exec ai-system-redis redis-cli FLUSHALL
```

**Increase Redis memory:**
```bash
# Edit redis.conf
docker exec -it ai-system-redis sh
echo "maxmemory 2gb" >> /etc/redis/redis.conf
exit

docker restart ai-system-redis
```

---

### 5. LLM API Errors

#### Symptoms
- 401 Unauthorized errors
- 429 Rate limit errors
- 500 errors from Anthropic

#### Diagnosis

```bash
# Check API key is set
docker exec ai-system-api env | grep ANTHROPIC_API_KEY

# Check LLM call logs
docker logs ai-system-api | grep "\[LLMProxy\]"
```

#### Solutions

**Invalid API key:**
```bash
# Update .env file
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# Restart API
docker-compose restart api
```

**Rate limit exceeded:**
```
The system uses deterministic retry with exponential backoff.
Wait for the circuit breaker to reset (60 seconds).

Check circuit breaker status in logs:
docker logs ai-system-api | grep "\[CircuitBreaker\]"
```

**Model not found:**
```bash
# Check available models in logs
# Update to valid model in session config

# Valid models (as of 2024):
# - claude-3-haiku-20240307
# - claude-3-sonnet-20240229
# - claude-3-opus-20240229
```

---

### 6. High Latency

#### Symptoms
- Slow API responses
- P95 latency > 2 seconds
- Timeouts

#### Diagnosis

```bash
# Check system resources
docker stats

# Check slow database queries
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT query, calls, total_time/calls as avg_time
      FROM pg_stat_statements
      ORDER BY total_time DESC LIMIT 10;"

# Check Redis latency
docker exec ai-system-redis redis-cli --latency

# Check API metrics
curl http://localhost:8000/metrics | grep http_request_duration
```

#### Solutions

**Database optimization:**
```sql
-- Add missing indices
CREATE INDEX CONCURRENTLY idx_audit_event_session
  ON audit_event((context->>'session_id'));

CREATE INDEX CONCURRENTLY idx_job_session_status
  ON job(session_id, status);

-- Vacuum and analyze
VACUUM ANALYZE;
```

**Redis optimization:**
```bash
# Check for slow commands
docker exec ai-system-redis redis-cli SLOWLOG GET 10

# Increase Redis memory
# See "Redis Connection Issues" section above
```

**Scale horizontally:**
```bash
# Add more API instances
docker-compose up -d --scale api=3

# Add more workers
docker-compose up -d --scale worker=5
```

---

### 7. Disk Space Full

#### Symptoms
- "No space left on device" errors
- Database insert failures
- Container crashes

#### Diagnosis

```bash
# Check disk usage
df -h

# Check Docker disk usage
docker system df

# Find large files
du -sh /var/lib/docker/* | sort -h
```

#### Solutions

**Clean Docker resources:**
```bash
# Remove unused containers
docker container prune -f

# Remove unused images
docker image prune -a -f

# Remove unused volumes
docker volume prune -f

# Complete cleanup (use with caution)
docker system prune -a --volumes -f
```

**Clean logs:**
```bash
# Limit log size in docker-compose.yml
services:
  api:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

# Rotate logs manually
find /var/lib/docker/containers/ -name "*.log" -exec truncate -s 0 {} \;
```

**Archive old data:**
```sql
-- Archive old audit events
DELETE FROM audit_event WHERE timestamp < now() - interval '90 days';

-- Archive completed jobs
DELETE FROM job WHERE status = 'COMPLETED' AND created_at < now() - interval '30 days';

-- Vacuum
VACUUM FULL;
```

---

### 8. Memory Leaks

#### Symptoms
- Gradually increasing memory usage
- OOM kills
- Degraded performance over time

#### Diagnosis

```bash
# Monitor memory over time
watch -n 5 docker stats --no-stream

# Check Python memory usage (if psutil installed)
docker exec ai-system-api python3 -c "
import psutil
process = psutil.Process()
print(f'Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB')
"

# Enable memory profiling (add to main.py)
# import tracemalloc
# tracemalloc.start()
```

#### Solutions

**Restart services regularly:**
```bash
# Add to cron
0 3 * * * docker restart ai-system-api
0 3 * * * docker restart ai-system-worker
```

**Configure memory limits:**
```yaml
# docker-compose.yml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M
```

**Profile memory usage:**
```python
# Add to problematic endpoint
import tracemalloc

tracemalloc.start()

# ... your code ...

snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

---

### 9. Authentication Failures

#### Symptoms
- 401 Unauthorized errors
- JWT validation failures
- User sync issues

#### Diagnosis

```bash
# Check Keycloak is running
docker ps | grep keycloak

# Test OIDC endpoint
curl http://localhost:8080/realms/ai-system/.well-known/openid-configuration

# Check JWT token
# Use jwt.io to decode and inspect token

# Check API logs
docker logs ai-system-api | grep "\[UserSyncManager\]"
```

#### Solutions

**Restart Keycloak:**
```bash
docker restart ai-system-keycloak
```

**Check OIDC configuration:**
```bash
# Verify environment variables
docker exec ai-system-api env | grep OIDC

# Should see:
# OIDC_ISSUER=http://keycloak:8080/realms/ai-system
# OIDC_JWKS_URL=http://keycloak:8080/realms/ai-system/protocol/openid-connect/certs
# OIDC_AUDIENCE=ai-system-api
```

**Clear JWKS cache:**
```python
# In Python shell or add to admin endpoint
from agents.user_sync_manager import UserSyncManager
UserSyncManager._jwks_cache.clear()
UserSyncManager._jwks_cache_time.clear()
```

---

### 10. Audit Log Issues

#### Symptoms
- Missing audit events
- Audit queries slow
- Disk space consumed by audit table

#### Diagnosis

```bash
# Check audit table size
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT pg_size_pretty(pg_total_relation_size('audit_event'));"

# Count events
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*) FROM audit_event;"

# Check recent events
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT * FROM audit_event ORDER BY timestamp DESC LIMIT 10;"
```

#### Solutions

**Archive old events:**
```sql
-- Create archive table
CREATE TABLE audit_event_archive (LIKE audit_event INCLUDING ALL);

-- Move old events
INSERT INTO audit_event_archive
SELECT * FROM audit_event WHERE timestamp < now() - interval '90 days';

DELETE FROM audit_event WHERE timestamp < now() - interval '90 days';

-- Vacuum
VACUUM FULL audit_event;
```

**Optimize audit queries:**
```sql
-- Add indices if missing
CREATE INDEX CONCURRENTLY idx_audit_event_timestamp
  ON audit_event(timestamp);

CREATE INDEX CONCURRENTLY idx_audit_event_session
  ON audit_event((context->>'session_id'));

-- Analyze table
ANALYZE audit_event;
```

---

## Emergency Procedures

### Full System Restart

```bash
# Stop all services
docker-compose down

# Clean up (optional, removes data)
docker volume rm ai-system-postgres-data
docker volume rm ai-system-redis-data

# Start fresh
docker-compose up -d

# Run migrations
docker-compose exec api alembic upgrade head

# Verify health
curl http://localhost:8000/health | jq
```

### Database Restore from Backup

```bash
# Stop API and workers
docker-compose stop api worker

# Restore database
gunzip < backup.sql.gz | docker exec -i ai-system-postgres \
  psql -U ai_user -d ai_system

# Restart services
docker-compose start api worker
```

### Rollback Deployment

```bash
# Docker Compose
docker-compose down
git checkout previous-tag
docker-compose up -d

# Kubernetes
kubectl rollout undo deployment/ai-system-api -n ai-system
```

---

## Monitoring & Alerts

### Set Up Alerts

**Prometheus Alert Example:**
```yaml
- alert: APIDown
  expr: up{job="api"} == 0
  for: 1m
  annotations:
    summary: "API is down"

- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
  for: 5m
  annotations:
    summary: "High error rate: {{ $value }}"
```

### Watch Key Metrics

```bash
# Real-time metrics
watch -n 2 'curl -s http://localhost:8000/metrics | grep -E "(http_requests_total|sessions_active_total|jobs_total)"'

# Database connections
watch -n 5 'docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"'

# Redis queue length
watch -n 2 'docker exec ai-system-redis redis-cli LLEN "job_queue:llm_call"'
```

---

## Getting Help

### Collect Diagnostic Information

```bash
#!/bin/bash
# collect-diagnostics.sh

OUTDIR="diagnostics-$(date +%Y%m%d-%H%M%S)"
mkdir -p $OUTDIR

# System info
uname -a > $OUTDIR/system-info.txt
df -h > $OUTDIR/disk-usage.txt
free -h > $OUTDIR/memory-usage.txt

# Docker info
docker ps > $OUTDIR/docker-ps.txt
docker stats --no-stream > $OUTDIR/docker-stats.txt
docker logs ai-system-api --tail=500 > $OUTDIR/api-logs.txt
docker logs ai-system-worker --tail=500 > $OUTDIR/worker-logs.txt
docker logs ai-system-postgres --tail=500 > $OUTDIR/postgres-logs.txt
docker logs ai-system-redis --tail=500 > $OUTDIR/redis-logs.txt

# Health check
curl http://localhost:8000/health > $OUTDIR/health-check.json
curl http://localhost:8000/metrics > $OUTDIR/metrics.txt

# Database info
docker exec ai-system-postgres psql -U ai_user -d ai_system \
  -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;" \
  > $OUTDIR/db-connections.txt

echo "Diagnostics collected in $OUTDIR/"
tar -czf $OUTDIR.tar.gz $OUTDIR/
echo "Archive created: $OUTDIR.tar.gz"
```

### Contact Support

When contacting support, include:
1. Diagnostic archive (see above)
2. Description of issue
3. Steps to reproduce
4. When issue started
5. Any recent changes

---

## Preventive Maintenance

### Daily Tasks
- Monitor error rates in Grafana
- Check disk space: `df -h`
- Review audit logs for anomalies

### Weekly Tasks
- Database vacuum: `VACUUM ANALYZE`
- Review slow queries
- Check SSL certificate expiry
- Update container images

### Monthly Tasks
- Security updates
- Performance review
- Archive old data
- Cost optimization review

---

**Last Updated:** 2024-03-20
**Version:** 1.0
