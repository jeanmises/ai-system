"""
Prometheus Metrics for AI System.

Exports application metrics in Prometheus format.
"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time
from functools import wraps

# ==============================================================================
# METRIC DEFINITIONS
# ==============================================================================

# HTTP Request Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'path', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'path']
)

# Session Metrics
sessions_active_total = Gauge(
    'sessions_active_total',
    'Number of active sessions'
)

sessions_created_total = Counter(
    'sessions_created_total',
    'Total sessions created'
)

sessions_archived_total = Counter(
    'sessions_archived_total',
    'Total sessions archived'
)

# Job Metrics
jobs_total = Counter(
    'jobs_total',
    'Total jobs created',
    ['job_type']
)

jobs_completed_total = Counter(
    'jobs_completed_total',
    'Total jobs completed',
    ['job_type']
)

jobs_failed_total = Counter(
    'jobs_failed_total',
    'Total jobs failed',
    ['job_type']
)

job_duration_seconds = Histogram(
    'job_duration_seconds',
    'Job execution duration',
    ['job_type']
)

redis_job_queue_length = Gauge(
    'redis_job_queue_length',
    'Current job queue length',
    ['queue']
)

# LLM Metrics
llm_calls_total = Counter(
    'llm_calls_total',
    'Total LLM API calls',
    ['model', 'status']
)

llm_tokens_total = Counter(
    'llm_tokens_total',
    'Total tokens used',
    ['model', 'type']  # type: input or output
)

llm_call_duration_seconds = Histogram(
    'llm_call_duration_seconds',
    'LLM API call duration',
    ['model']
)

# Database Metrics
db_connections_active = Gauge(
    'db_connections_active',
    'Active database connections'
)

db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration',
    ['query_type']
)

# Audit Metrics
audit_events_total = Counter(
    'audit_events_total',
    'Total audit events',
    ['event_type']
)

# Meta-Proposal Metrics
meta_proposals_total = Counter(
    'meta_proposals_total',
    'Total meta-proposals',
    ['category', 'status']
)

# Sandbox Metrics
sandbox_runs_total = Counter(
    'sandbox_runs_total',
    'Total sandbox executions',
    ['execution_type', 'status']
)

sandbox_duration_seconds = Histogram(
    'sandbox_duration_seconds',
    'Sandbox execution duration',
    ['execution_type']
)


# ==============================================================================
# METRIC HELPERS
# ==============================================================================

def track_request(method: str, path: str, status: int, duration: float):
    """Track HTTP request metrics."""
    http_requests_total.labels(method=method, path=path, status=status).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(duration)


def track_job_created(job_type: str):
    """Track job creation."""
    jobs_total.labels(job_type=job_type).inc()


def track_job_completed(job_type: str, duration: float):
    """Track job completion."""
    jobs_completed_total.labels(job_type=job_type).inc()
    job_duration_seconds.labels(job_type=job_type).observe(duration)


def track_job_failed(job_type: str):
    """Track job failure."""
    jobs_failed_total.labels(job_type=job_type).inc()


def track_llm_call(model: str, status: str, duration: float, input_tokens: int, output_tokens: int):
    """Track LLM API call."""
    llm_calls_total.labels(model=model, status=status).inc()
    llm_call_duration_seconds.labels(model=model).observe(duration)
    llm_tokens_total.labels(model=model, type='input').inc(input_tokens)
    llm_tokens_total.labels(model=model, type='output').inc(output_tokens)


def track_audit_event(event_type: str):
    """Track audit event."""
    audit_events_total.labels(event_type=event_type).inc()


def track_meta_proposal(category: str, status: str):
    """Track meta-proposal."""
    meta_proposals_total.labels(category=category, status=status).inc()


def track_sandbox_run(execution_type: str, status: str, duration: float):
    """Track sandbox execution."""
    sandbox_runs_total.labels(execution_type=execution_type, status=status).inc()
    sandbox_duration_seconds.labels(execution_type=execution_type).observe(duration)


def metrics_endpoint():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus exposition format.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ==============================================================================
# DECORATORS
# ==============================================================================

def track_time(metric: Histogram, labels: dict = None):
    """
    Decorator to track execution time.

    Usage:
        @track_time(job_duration_seconds, {'job_type': 'llm_call'})
        def process_job():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)

        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
