"""
Job Manager Agent - Async job queue management with Redis.

This agent manages asynchronous jobs for the AI system.

Based on: EXECUTION_PLAN.md Phase 1 Step 5
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
import logging
import json
import os

from sqlalchemy.orm import Session as DBSession
import redis

from models import Job, Session
from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class JobManager:
    """
    Job Manager Agent - Async job management.

    Responsibilities:
    - Create jobs and enqueue to Redis
    - Update job status (pending, running, completed, failed)
    - Query jobs by session or status
    - Handle job timeouts
    - Generate audit events for job lifecycle

    Critical Rules:
    1. Jobs must belong to a valid session
    2. Job state transitions: pending → running → completed/failed
    3. Job results stored in JSONB for flexibility
    4. All operations logged via Audit Logger
    5. Redis used as message queue for async processing
    """

    # Valid job status transitions
    VALID_TRANSITIONS = {
        "PENDING": ["SCHEDULED", "RUNNING", "FAILED"],
        "SCHEDULED": ["RUNNING", "FAILED"],
        "RUNNING": ["COMPLETED", "FAILED"],
        "COMPLETED": [],  # Terminal
        "FAILED": []  # Terminal
    }

    def __init__(
        self,
        db: DBSession,
        audit_logger: Optional[AuditLogger] = None,
        redis_client: Optional[redis.Redis] = None
    ):
        """
        Initialize Job Manager.

        Args:
            db: SQLAlchemy database session
            audit_logger: Optional AuditLogger instance
            redis_client: Optional Redis client (will create default if not provided)
        """
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

        # Initialize Redis client
        if redis_client:
            self.redis = redis_client
        else:
            redis_password = os.getenv('REDIS_PASSWORD')
            self.redis = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', '6379')),
                password=redis_password if redis_password else None,
                db=0,
                decode_responses=True
            )

    def create_job(
        self,
        session_id: UUID,
        job_type: str,
        payload: Dict[str, Any],
        timeout_seconds: int = 300,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Create a new job and enqueue it.

        Args:
            session_id: UUID of the session
            job_type: Type of job (e.g., "llm_call", "analysis", "report")
            payload: Input payload for the job (JSONB)
            timeout_seconds: Job timeout in seconds (default 300)
            max_retries: Max retry attempts (default 3)

        Returns:
            Dict with job info:
                - job_id: UUID
                - session_id: UUID
                - job_type: str
                - status: "PENDING"
                - created_at: ISO timestamp

        Raises:
            ValueError: If session doesn't exist or input invalid
        """
        # Validate session exists
        session = self.db.query(Session).filter_by(id=session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Validate input
        if not job_type:
            raise ValueError("job_type is required")

        # Create job
        job_id = uuid4()

        new_job = Job(
            id=job_id,
            session_id=session_id,
            job_type=job_type,
            status="PENDING",
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            attempt_count=0
        )

        self.db.add(new_job)
        self.db.flush()

        # Enqueue to Redis
        queue_name = f"job_queue:{job_type}"
        job_message = {
            "job_id": str(job_id),
            "session_id": str(session_id),
            "job_type": job_type,
            "created_at": datetime.utcnow().isoformat()
        }

        try:
            self.redis.rpush(queue_name, json.dumps(job_message))
            logger.info(f"[JobManager] Job {job_id} enqueued to {queue_name}")
        except Exception as e:
            logger.error(f"[JobManager] Failed to enqueue job {job_id}: {e}")
            # Continue anyway - job is in DB, can be retried

        # Log audit event
        self.audit_logger.log(
            event_type="job.created",
            actor_type="agent",
            actor_id="job_manager",
            action_verb="created",
            entity_type="job",
            entity_id=str(job_id),
            context={
                "session_id": str(session_id),
                "job_type": job_type
            },
            result_status="success"
        )

        logger.info(f"[JobManager] Created job {job_id} for session {session_id}")

        return self._job_to_dict(new_job)

    def get_job(self, job_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get job by ID.

        Args:
            job_id: UUID of the job

        Returns:
            Dict with job info, or None if not found
        """
        job = self.db.query(Job).filter_by(id=job_id).first()

        if not job:
            return None

        return self._job_to_dict(job)

    def update_job_status(
        self,
        job_id: UUID,
        new_status: str,
        result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Update job status.

        Args:
            job_id: UUID of the job
            new_status: New status (SCHEDULED, RUNNING, COMPLETED, FAILED)
            result: Optional result data (JSONB)

        Returns:
            Dict with updated job info

        Raises:
            ValueError: If job not found or invalid status transition
        """
        job = self.db.query(Job).filter_by(id=job_id).first()

        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Validate status transition
        old_status = job.status
        self._validate_status_transition(old_status, new_status)

        # Update job
        job.status = new_status

        if new_status == "RUNNING":
            job.started_at = datetime.utcnow()
            job.attempt_count += 1
        elif new_status in ["COMPLETED", "FAILED"]:
            job.completed_at = datetime.utcnow()

        if result:
            job.result = result

        self.db.flush()

        # Log audit event
        # Determine result status for audit (only success/failure allowed)
        if new_status == "COMPLETED":
            audit_result = "success"
        elif new_status == "FAILED":
            audit_result = "failure"
        else:
            # For intermediate states (RUNNING, SCHEDULED), log as success (transition succeeded)
            audit_result = "success"

        self.audit_logger.log(
            event_type=f"job.{new_status.lower()}",
            actor_type="agent",
            actor_id="job_manager",
            action_verb=new_status.lower(),
            entity_type="job",
            entity_id=str(job_id),
            context={
                "session_id": str(job.session_id),
                "job_type": job.job_type,
                "old_status": old_status,
                "new_status": new_status,
                "attempt": job.attempt_count
            },
            result_status=audit_result
        )

        logger.info(f"[JobManager] Job {job_id} status: {old_status} → {new_status} (attempt {job.attempt_count})")

        return self._job_to_dict(job)

    def list_jobs(
        self,
        session_id: Optional[UUID] = None,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List jobs with optional filters.

        Args:
            session_id: Optional filter by session
            status: Optional filter by status
            job_type: Optional filter by job type
            limit: Max number of results (default 50, max 100)
            offset: Pagination offset

        Returns:
            List of job dicts
        """
        if limit > 100:
            limit = 100

        query = self.db.query(Job)

        if session_id:
            query = query.filter_by(session_id=session_id)

        if status:
            query = query.filter_by(status=status)

        if job_type:
            query = query.filter_by(job_type=job_type)

        # Order by created_at (desc) - most recent first
        query = query.order_by(Job.created_at.desc())

        # Pagination
        jobs = query.limit(limit).offset(offset).all()

        return [self._job_to_dict(j) for j in jobs]

    def dequeue_job(self, priority: int = 5, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Dequeue next job from Redis queue (for worker).

        Args:
            priority: Queue priority to check (1-10)
            timeout: Timeout in seconds for blocking pop

        Returns:
            Dict with job message, or None if no jobs
        """
        queue_name = f"job_queue:priority_{priority}"

        try:
            # Blocking left pop with timeout
            result = self.redis.blpop(queue_name, timeout=timeout)

            if result:
                _, job_json = result
                job_message = json.loads(job_json)
                logger.info(f"[JobManager] Dequeued job {job_message['job_id']} from {queue_name}")
                return job_message

            return None

        except Exception as e:
            logger.error(f"[JobManager] Failed to dequeue job: {e}")
            return None

    def _validate_status_transition(self, old_status: str, new_status: str):
        """
        Validate that status transition is allowed.

        Args:
            old_status: Current status
            new_status: Desired new status

        Raises:
            ValueError: If transition is invalid
        """
        if old_status not in self.VALID_TRANSITIONS:
            raise ValueError(f"Invalid status: {old_status}")

        allowed_statuses = self.VALID_TRANSITIONS[old_status]
        if new_status not in allowed_statuses:
            raise ValueError(
                f"Invalid status transition: {old_status} → {new_status}. "
                f"Allowed: {', '.join(allowed_statuses) if allowed_statuses else 'none (terminal status)'}"
            )

    def _job_to_dict(self, job: Job) -> Dict[str, Any]:
        """
        Convert Job model to dict.

        Args:
            job: Job model instance

        Returns:
            Dict representation
        """
        return {
            "job_id": str(job.id),
            "session_id": str(job.session_id),
            "subsession_id": str(job.subsession_id) if job.subsession_id else None,
            "job_type": job.job_type,
            "status": job.status,
            "payload": job.payload,
            "result": job.result,
            "timeout_seconds": job.timeout_seconds,
            "max_retries": job.max_retries,
            "attempt_count": job.attempt_count,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None
        }
