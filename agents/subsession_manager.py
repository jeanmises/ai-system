"""
SubSession Manager Agent - Isolated work unit management.

SubSessions provide isolated contexts for parallel work with deterministic snapshots.

Based on: SYSTEM_FOUNDATION.md SubSession Architecture
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
import logging
import json

from sqlalchemy.orm import Session as DBSession

from models import SubSession, Session
from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class SubSessionManager:
    """
    SubSession Manager Agent - Isolated work unit management.

    Responsibilities:
    - Create subsessions with snapshot-based input
    - Manage subsession lifecycle
    - Enforce isolation between subsessions
    - Track parent-child relationships
    - Generate audit events

    Critical Rules:
    1. SubSessions are immutable after creation (snapshot-based)
    2. Each subsession has deterministic input snapshot
    3. SubSessions can run in parallel (isolated)
    4. Output is merged back to parent session
    5. All operations logged via Audit Logger
    """

    # Valid subsession status
    VALID_TRANSITIONS = {
        "created": ["active", "cancelled"],
        "active": ["completed", "failed", "cancelled"],
        "completed": ["archived"],
        "failed": ["retrying", "archived"],
        "retrying": ["active", "failed"],
        "cancelled": ["archived"],
        "archived": []  # Terminal
    }

    def __init__(
        self,
        db: DBSession,
        audit_logger: Optional[AuditLogger] = None
    ):
        """
        Initialize SubSession Manager.

        Args:
            db: SQLAlchemy database session
            audit_logger: Optional AuditLogger instance
        """
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

    def create_subsession(
        self,
        parent_session_id: UUID,
        objective: str,
        input_snapshot: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a new subsession.

        Args:
            parent_session_id: UUID of parent session
            objective: What this subsession should accomplish
            input_snapshot: Deterministic input data (immutable)
            config: Optional configuration (model, temperature, etc.)

        Returns:
            Dict with subsession info

        Raises:
            ValueError: If parent session doesn't exist
        """
        # Validate parent session exists
        parent = self.db.query(Session).filter_by(id=parent_session_id).first()
        if not parent:
            raise ValueError(f"Parent session {parent_session_id} not found")

        # Create subsession
        subsession_id = uuid4()

        subsession = SubSession(
            id=subsession_id,
            parent_session_id=parent_session_id,
            objective=objective,
            status="created",
            input_snapshot=input_snapshot,
            config=config or {},
            created_at=datetime.utcnow()
        )

        self.db.add(subsession)
        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type="subsession.created",
            actor_type="agent",
            actor_id="subsession_manager",
            action_verb="created",
            entity_type="subsession",
            entity_id=str(subsession_id),
            context={
                "parent_session_id": str(parent_session_id),
                "objective": objective[:100]  # Truncate for log
            },
            result_status="success"
        )

        logger.info(f"[SubSessionManager] Created subsession {subsession_id} for session {parent_session_id}")

        return self._subsession_to_dict(subsession)

    def get_subsession(self, subsession_id: UUID) -> Optional[Dict[str, Any]]:
        """Get subsession by ID."""
        subsession = self.db.query(SubSession).filter_by(id=subsession_id).first()

        if not subsession:
            return None

        return self._subsession_to_dict(subsession)

    def update_subsession_status(
        self,
        subsession_id: UUID,
        new_status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Update subsession status.

        Args:
            subsession_id: UUID of subsession
            new_status: New status
            output_data: Optional output data (for completed)
            error_data: Optional error data (for failed)

        Returns:
            Updated subsession dict

        Raises:
            ValueError: If invalid transition
        """
        subsession = self.db.query(SubSession).filter_by(id=subsession_id).first()

        if not subsession:
            raise ValueError(f"SubSession {subsession_id} not found")

        # Validate transition
        old_status = subsession.status
        self._validate_status_transition(old_status, new_status)

        # Update status
        subsession.status = new_status
        subsession.updated_at = datetime.utcnow()

        if new_status == "active":
            subsession.started_at = datetime.utcnow()
        elif new_status in ["completed", "failed", "cancelled"]:
            subsession.completed_at = datetime.utcnow()

        if output_data:
            subsession.output_data = output_data

        if error_data:
            subsession.error_data = error_data

        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type=f"subsession.{new_status}",
            actor_type="agent",
            actor_id="subsession_manager",
            action_verb=new_status,
            entity_type="subsession",
            entity_id=str(subsession_id),
            context={
                "parent_session_id": str(subsession.parent_session_id),
                "old_status": old_status,
                "new_status": new_status
            },
            result_status="success" if new_status == "completed" else ("failure" if new_status == "failed" else "success")
        )

        logger.info(f"[SubSessionManager] SubSession {subsession_id} status: {old_status} → {new_status}")

        return self._subsession_to_dict(subsession)

    def list_subsessions(
        self,
        parent_session_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List subsessions with filters.

        Args:
            parent_session_id: Optional filter by parent
            status: Optional filter by status
            limit: Max results
            offset: Pagination offset

        Returns:
            List of subsession dicts
        """
        if limit > 100:
            limit = 100

        query = self.db.query(SubSession)

        if parent_session_id:
            query = query.filter_by(parent_session_id=parent_session_id)

        if status:
            query = query.filter_by(status=status)

        query = query.order_by(SubSession.created_at.desc())
        subsessions = query.limit(limit).offset(offset).all()

        return [self._subsession_to_dict(ss) for ss in subsessions]

    def _validate_status_transition(self, old_status: str, new_status: str):
        """Validate status transition."""
        if old_status not in self.VALID_TRANSITIONS:
            raise ValueError(f"Invalid status: {old_status}")

        allowed = self.VALID_TRANSITIONS[old_status]
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {old_status} → {new_status}. "
                f"Allowed: {', '.join(allowed) if allowed else 'none'}"
            )

    def _subsession_to_dict(self, subsession: SubSession) -> Dict[str, Any]:
        """Convert SubSession model to dict."""
        return {
            "subsession_id": str(subsession.id),
            "parent_session_id": str(subsession.parent_session_id),
            "objective": subsession.objective,
            "status": subsession.status,
            "input_snapshot": subsession.input_snapshot,
            "output_data": subsession.output_data,
            "error_data": subsession.error_data,
            "config": subsession.config,
            "created_at": subsession.created_at.isoformat(),
            "started_at": subsession.started_at.isoformat() if subsession.started_at else None,
            "completed_at": subsession.completed_at.isoformat() if subsession.completed_at else None,
            "updated_at": subsession.updated_at.isoformat() if subsession.updated_at else None
        }
