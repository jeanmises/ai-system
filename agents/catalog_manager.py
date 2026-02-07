"""
Catalog Manager Agent - Versioned catalog for agents, instructions, and job types.

This agent manages the immutable versioned catalog of system components.

Based on: SYSTEM_FOUNDATION.md Catalog System
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
import logging

from sqlalchemy.orm import Session as DBSession

from models import Agent, Instruction, JobType
from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class CatalogManager:
    """
    Catalog Manager Agent - Versioned catalog management.

    Responsibilities:
    - Register agents with semantic versioning
    - Register instruction templates with versioning
    - Register job types with versioning
    - Query catalog entries
    - Manage catalog entry status (active/deprecated)
    - Generate audit events for catalog operations

    Critical Rules:
    1. All catalog entries are immutable once published
    2. Versions follow semantic versioning (major.minor.patch)
    3. Only one version can be 'active' status per ID
    4. Published entries cannot be deleted, only deprecated
    5. All operations logged via Audit Logger
    """

    def __init__(
        self,
        db: DBSession,
        audit_logger: Optional[AuditLogger] = None
    ):
        """
        Initialize Catalog Manager.

        Args:
            db: SQLAlchemy database session
            audit_logger: Optional AuditLogger instance
        """
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

    # =========================================================================
    # AGENT CATALOG
    # =========================================================================

    def register_agent(
        self,
        agent_id: str,
        version: str,
        description: str,
        config: Dict[str, Any],
        status: str = "active"
    ) -> Dict[str, Any]:
        """
        Register a new agent version.

        Args:
            agent_id: Agent identifier (e.g., "session_manager")
            version: Semantic version (e.g., "1.0.0")
            description: Human-readable description
            config: Agent configuration (JSONB)
            status: Status (active, deprecated)

        Returns:
            Dict with agent info

        Raises:
            ValueError: If agent+version already exists
        """
        # Check if already exists
        existing = self.db.query(Agent).filter_by(
            id=agent_id,
            version=version
        ).first()

        if existing:
            raise ValueError(f"Agent {agent_id} version {version} already exists")

        # Create new agent entry
        agent = Agent(
            id=agent_id,
            version=version,
            description=description,
            config=config,
            status=status,
            created_at=datetime.utcnow()
        )

        if status == "active":
            agent.published_at = datetime.utcnow()

        self.db.add(agent)
        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type="catalog.agent_registered",
            actor_type="system",
            actor_id="catalog_manager",
            action_verb="registered",
            entity_type="agent",
            entity_id=f"{agent_id}@{version}",
            context={"agent_id": agent_id, "version": version},
            result_status="success"
        )

        logger.info(f"[CatalogManager] Registered agent {agent_id}@{version}")

        return self._agent_to_dict(agent)

    def list_agents(
        self,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List agents.

        Args:
            status: Optional filter by status
            limit: Max results

        Returns:
            List of agent dicts
        """
        query = self.db.query(Agent)

        if status:
            query = query.filter_by(status=status)

        query = query.order_by(Agent.id, Agent.created_at.desc())
        agents = query.limit(limit).all()

        return [self._agent_to_dict(a) for a in agents]

    # =========================================================================
    # JOB TYPE CATALOG
    # =========================================================================

    def register_job_type(
        self,
        job_type_id: str,
        version: str,
        description: str,
        input_schema: Dict[str, Any],
        output_schema: Dict[str, Any],
        timeout_seconds: int = 300,
        max_retries: int = 3,
        status: str = "active"
    ) -> Dict[str, Any]:
        """
        Register a new job type version.

        Args:
            job_type_id: Job type identifier (e.g., "llm_call")
            version: Semantic version
            description: Human-readable description
            input_schema: JSON Schema for input validation
            output_schema: JSON Schema for output validation
            timeout_seconds: Default timeout
            max_retries: Default max retries
            status: Status (active, deprecated)

        Returns:
            Dict with job type info

        Raises:
            ValueError: If job_type+version already exists
        """
        # Check if already exists
        existing = self.db.query(JobType).filter_by(
            id=job_type_id,
            version=version
        ).first()

        if existing:
            raise ValueError(f"JobType {job_type_id} version {version} already exists")

        # Create new job type entry
        job_type = JobType(
            id=job_type_id,
            version=version,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            status=status,
            created_at=datetime.utcnow()
        )

        if status == "active":
            job_type.published_at = datetime.utcnow()

        self.db.add(job_type)
        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type="catalog.job_type_registered",
            actor_type="system",
            actor_id="catalog_manager",
            action_verb="registered",
            entity_type="job_type",
            entity_id=f"{job_type_id}@{version}",
            context={"job_type_id": job_type_id, "version": version},
            result_status="success"
        )

        logger.info(f"[CatalogManager] Registered job_type {job_type_id}@{version}")

        return self._job_type_to_dict(job_type)

    def list_job_types(
        self,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List job types.

        Args:
            status: Optional filter by status
            limit: Max results

        Returns:
            List of job type dicts
        """
        query = self.db.query(JobType)

        if status:
            query = query.filter_by(status=status)

        query = query.order_by(JobType.id, JobType.created_at.desc())
        job_types = query.limit(limit).all()

        return [self._job_type_to_dict(jt) for jt in job_types]

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _agent_to_dict(self, agent: Agent) -> Dict[str, Any]:
        """Convert Agent model to dict."""
        return {
            "agent_id": agent.id,
            "version": agent.version,
            "description": agent.description,
            "config": agent.config,
            "status": agent.status,
            "created_at": agent.created_at.isoformat(),
            "published_at": agent.published_at.isoformat() if agent.published_at else None
        }

    def _job_type_to_dict(self, job_type: JobType) -> Dict[str, Any]:
        """Convert JobType model to dict."""
        return {
            "job_type_id": job_type.id,
            "version": job_type.version,
            "description": job_type.description,
            "input_schema": job_type.input_schema,
            "output_schema": job_type.output_schema,
            "timeout_seconds": job_type.timeout_seconds,
            "max_retries": job_type.max_retries,
            "status": job_type.status,
            "created_at": job_type.created_at.isoformat(),
            "published_at": job_type.published_at.isoformat() if job_type.published_at else None
        }
