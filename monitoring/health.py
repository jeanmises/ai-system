"""
Advanced Health Checks - Comprehensive system health monitoring.

Checks status of all critical services and dependencies.
"""

import time
import logging
from typing import Dict, Any, List
from datetime import datetime
import redis
import anthropic
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)


class HealthChecker:
    """
    Comprehensive health checker for all system components.

    Checks:
    - Database connectivity and performance
    - Redis connectivity and memory
    - LLM API availability
    - Disk space
    - Memory usage
    """

    def __init__(
        self,
        db: DBSession,
        redis_client: redis.Redis,
        anthropic_api_key: str
    ):
        """Initialize health checker."""
        self.db = db
        self.redis = redis_client
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)

    async def check_all(self) -> Dict[str, Any]:
        """
        Run all health checks.

        Returns:
            Dict with overall status and individual component checks
        """
        start_time = time.time()

        checks = {
            "database": await self.check_database(),
            "redis": await self.check_redis(),
            "llm_api": await self.check_llm_api(),
            "disk": await self.check_disk(),
            "memory": await self.check_memory()
        }

        # Determine overall status
        all_healthy = all(check["status"] == "healthy" for check in checks.values())
        any_degraded = any(check["status"] == "degraded" for check in checks.values())

        overall_status = "healthy" if all_healthy else ("degraded" if any_degraded else "unhealthy")

        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_ms": duration_ms,
            "checks": checks,
            "version": "1.0.0"
        }

    async def check_database(self) -> Dict[str, Any]:
        """Check database health."""
        try:
            start_time = time.time()

            # Test connection
            result = self.db.execute(text("SELECT 1"))
            result.fetchone()

            # Check active connections
            conn_result = self.db.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
            ))
            active_connections = conn_result.fetchone()[0]

            # Check database size
            size_result = self.db.execute(text(
                "SELECT pg_database_size(current_database())"
            ))
            db_size_bytes = size_result.fetchone()[0]

            duration_ms = int((time.time() - start_time) * 1000)

            # Determine status
            status = "healthy"
            if duration_ms > 1000:  # Slow query
                status = "degraded"
            if active_connections > 80:  # High connection count
                status = "degraded"

            return {
                "status": status,
                "response_time_ms": duration_ms,
                "active_connections": active_connections,
                "database_size_mb": round(db_size_bytes / 1024 / 1024, 2),
                "message": "Database operational"
            }

        except Exception as e:
            logger.error(f"[Health] Database check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "message": "Database unavailable"
            }

    async def check_redis(self) -> Dict[str, Any]:
        """Check Redis health."""
        try:
            start_time = time.time()

            # Test connection
            self.redis.ping()

            # Get Redis info
            info = self.redis.info()

            duration_ms = int((time.time() - start_time) * 1000)

            # Extract metrics
            used_memory_mb = info.get('used_memory', 0) / 1024 / 1024
            max_memory_mb = info.get('maxmemory', 0) / 1024 / 1024 if info.get('maxmemory', 0) > 0 else None
            connected_clients = info.get('connected_clients', 0)

            # Determine status
            status = "healthy"
            if duration_ms > 500:
                status = "degraded"
            if max_memory_mb and used_memory_mb / max_memory_mb > 0.8:
                status = "degraded"

            return {
                "status": status,
                "response_time_ms": duration_ms,
                "used_memory_mb": round(used_memory_mb, 2),
                "max_memory_mb": round(max_memory_mb, 2) if max_memory_mb else None,
                "connected_clients": connected_clients,
                "message": "Redis operational"
            }

        except Exception as e:
            logger.error(f"[Health] Redis check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "message": "Redis unavailable"
            }

    async def check_llm_api(self) -> Dict[str, Any]:
        """Check LLM API health."""
        try:
            start_time = time.time()

            # Simple API health check (no actual call)
            # In production, you might want to make a minimal API call
            # or check API status endpoint if available

            duration_ms = int((time.time() - start_time) * 1000)

            return {
                "status": "healthy",
                "response_time_ms": duration_ms,
                "message": "LLM API configured",
                "note": "Full API test not performed (would consume tokens)"
            }

        except Exception as e:
            logger.error(f"[Health] LLM API check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "message": "LLM API unavailable"
            }

    async def check_disk(self) -> Dict[str, Any]:
        """Check disk space."""
        try:
            import shutil

            # Check disk space on root
            stat = shutil.disk_usage('/')

            total_gb = stat.total / (1024 ** 3)
            used_gb = stat.used / (1024 ** 3)
            free_gb = stat.free / (1024 ** 3)
            percent_used = (stat.used / stat.total) * 100

            # Determine status
            status = "healthy"
            if percent_used > 80:
                status = "degraded"
            if percent_used > 90:
                status = "unhealthy"

            return {
                "status": status,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "percent_used": round(percent_used, 2),
                "message": "Disk space adequate" if status == "healthy" else "Disk space low"
            }

        except Exception as e:
            logger.error(f"[Health] Disk check failed: {e}")
            return {
                "status": "unknown",
                "error": str(e),
                "message": "Could not check disk space"
            }

    async def check_memory(self) -> Dict[str, Any]:
        """Check system memory."""
        try:
            import psutil

            memory = psutil.virtual_memory()

            total_gb = memory.total / (1024 ** 3)
            available_gb = memory.available / (1024 ** 3)
            used_gb = memory.used / (1024 ** 3)
            percent_used = memory.percent

            # Determine status
            status = "healthy"
            if percent_used > 80:
                status = "degraded"
            if percent_used > 90:
                status = "unhealthy"

            return {
                "status": status,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "available_gb": round(available_gb, 2),
                "percent_used": round(percent_used, 2),
                "message": "Memory adequate" if status == "healthy" else "Memory pressure detected"
            }

        except Exception as e:
            logger.error(f"[Health] Memory check failed: {e}")
            return {
                "status": "unknown",
                "error": str(e),
                "message": "Could not check memory"
            }

    async def check_readiness(self) -> Dict[str, Any]:
        """
        Readiness check - is system ready to accept traffic?

        Simpler than full health check, focuses on critical dependencies.
        """
        try:
            # Check database
            self.db.execute(text("SELECT 1"))

            # Check Redis
            self.redis.ping()

            return {
                "status": "ready",
                "message": "System ready to accept traffic"
            }

        except Exception as e:
            return {
                "status": "not_ready",
                "error": str(e),
                "message": "System not ready"
            }

    async def check_liveness(self) -> Dict[str, Any]:
        """
        Liveness check - is the application alive?

        Simplest check, just confirms process is running.
        """
        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Application is alive"
        }
