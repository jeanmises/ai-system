"""
Rate Limiter - Prevent API abuse and ensure fair usage.

Implements token bucket algorithm with Redis backend.
"""

import time
import logging
from typing import Optional, Tuple
import redis
from fastapi import Request, HTTPException, status
from datetime import datetime

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter with Redis backend.

    Features:
    - Per-user rate limiting
    - Per-IP rate limiting
    - Configurable limits per endpoint
    - Sliding window implementation
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        default_requests: int = 100,
        default_window: int = 60
    ):
        """
        Initialize rate limiter.

        Args:
            redis_client: Redis client for distributed rate limiting
            default_requests: Default max requests per window
            default_window: Default time window in seconds
        """
        self.redis = redis_client
        self.default_requests = default_requests
        self.default_window = default_window

        # Endpoint-specific limits
        self.endpoint_limits = {
            "/api/llm/call": (10, 60),  # 10 req/min for LLM calls
            "/api/sessions": (50, 60),  # 50 req/min for session ops
            "/api/jobs": (100, 60),  # 100 req/min for job ops
        }

    async def check_rate_limit(
        self,
        request: Request,
        user_id: Optional[str] = None
    ) -> Tuple[bool, dict]:
        """
        Check if request is within rate limit.

        Args:
            request: FastAPI request object
            user_id: Optional user ID for per-user limiting

        Returns:
            Tuple of (allowed: bool, info: dict)

        Raises:
            HTTPException: If rate limit exceeded
        """
        # Determine rate limit key
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        if user_id:
            key = f"rate_limit:user:{user_id}:{path}"
        else:
            key = f"rate_limit:ip:{client_ip}:{path}"

        # Get limits for this endpoint
        max_requests, window_seconds = self.endpoint_limits.get(
            path,
            (self.default_requests, self.default_window)
        )

        # Check rate limit using sliding window
        current_time = time.time()
        window_start = current_time - window_seconds

        try:
            # Add current request timestamp
            self.redis.zadd(key, {str(current_time): current_time})

            # Remove old entries outside window
            self.redis.zremrangebyscore(key, 0, window_start)

            # Count requests in current window
            request_count = self.redis.zcard(key)

            # Set expiry on key
            self.redis.expire(key, window_seconds)

            # Check if limit exceeded
            allowed = request_count <= max_requests

            info = {
                "limit": max_requests,
                "remaining": max(0, max_requests - request_count),
                "reset": int(current_time + window_seconds),
                "window_seconds": window_seconds
            }

            if not allowed:
                logger.warning(
                    f"[RateLimiter] Rate limit exceeded for {key}: "
                    f"{request_count}/{max_requests} in {window_seconds}s"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": max_requests,
                        "window_seconds": window_seconds,
                        "retry_after": window_seconds
                    },
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(info["reset"]),
                        "Retry-After": str(window_seconds)
                    }
                )

            return allowed, info

        except redis.RedisError as e:
            logger.error(f"[RateLimiter] Redis error: {e}")
            # Fail open: allow request if Redis is down
            return True, {
                "limit": max_requests,
                "remaining": max_requests,
                "reset": int(current_time + window_seconds),
                "error": "rate_limiter_unavailable"
            }


class CircuitBreaker:
    """
    Circuit breaker for external service calls.

    Prevents cascading failures by temporarily blocking calls
    to failing services.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests blocked immediately
    - HALF_OPEN: Testing if service recovered
    """

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        redis_client: redis.Redis,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        """
        Initialize circuit breaker.

        Args:
            redis_client: Redis for distributed state
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before trying half-open
            expected_exception: Exception type to track
        """
        self.redis = redis_client
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

    def _get_state_key(self, service_name: str) -> str:
        """Get Redis key for circuit breaker state."""
        return f"circuit_breaker:{service_name}:state"

    def _get_failure_key(self, service_name: str) -> str:
        """Get Redis key for failure count."""
        return f"circuit_breaker:{service_name}:failures"

    def _get_last_failure_key(self, service_name: str) -> str:
        """Get Redis key for last failure time."""
        return f"circuit_breaker:{service_name}:last_failure"

    def get_state(self, service_name: str) -> str:
        """Get current circuit breaker state."""
        state = self.redis.get(self._get_state_key(service_name))
        if not state:
            return self.STATE_CLOSED

        state = state.decode('utf-8') if isinstance(state, bytes) else state

        # Check if should transition from OPEN to HALF_OPEN
        if state == self.STATE_OPEN:
            last_failure = self.redis.get(self._get_last_failure_key(service_name))
            if last_failure:
                last_failure_time = float(last_failure)
                if time.time() - last_failure_time >= self.recovery_timeout:
                    self._set_state(service_name, self.STATE_HALF_OPEN)
                    return self.STATE_HALF_OPEN

        return state

    def _set_state(self, service_name: str, state: str):
        """Set circuit breaker state."""
        self.redis.set(self._get_state_key(service_name), state)
        logger.info(f"[CircuitBreaker] {service_name} → {state.upper()}")

    def record_success(self, service_name: str):
        """Record successful call."""
        state = self.get_state(service_name)

        if state == self.STATE_HALF_OPEN:
            # Service recovered, close circuit
            self._set_state(service_name, self.STATE_CLOSED)
            self.redis.delete(self._get_failure_key(service_name))
            logger.info(f"[CircuitBreaker] {service_name} recovered")

        elif state == self.STATE_CLOSED:
            # Reset failure count on success
            self.redis.delete(self._get_failure_key(service_name))

    def record_failure(self, service_name: str):
        """Record failed call."""
        state = self.get_state(service_name)

        if state == self.STATE_HALF_OPEN:
            # Service still failing, reopen circuit
            self._set_state(service_name, self.STATE_OPEN)
            self.redis.set(
                self._get_last_failure_key(service_name),
                str(time.time())
            )

        elif state == self.STATE_CLOSED:
            # Increment failure count
            failures = self.redis.incr(self._get_failure_key(service_name))

            if failures >= self.failure_threshold:
                # Threshold exceeded, open circuit
                self._set_state(service_name, self.STATE_OPEN)
                self.redis.set(
                    self._get_last_failure_key(service_name),
                    str(time.time())
                )
                logger.warning(
                    f"[CircuitBreaker] {service_name} circuit opened "
                    f"after {failures} failures"
                )

    async def call(self, service_name: str, func, *args, **kwargs):
        """
        Execute function with circuit breaker protection.

        Args:
            service_name: Name of service being called
            func: Function to execute
            *args, **kwargs: Arguments for function

        Returns:
            Function result if successful

        Raises:
            HTTPException: If circuit is open
            Exception: Original exception from function
        """
        state = self.get_state(service_name)

        if state == self.STATE_OPEN:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "Service temporarily unavailable",
                    "service": service_name,
                    "circuit_state": "open",
                    "retry_after": self.recovery_timeout
                }
            )

        try:
            # Execute function
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            self.record_success(service_name)
            return result

        except self.expected_exception as e:
            self.record_failure(service_name)
            raise


import asyncio
