"""
Session Manager Agent - CRUD operations for user sessions.

This agent manages the lifecycle of user sessions (mother sessions).

Based on: SYSTEM_FOUNDATION.md Section 11 (Agent 3: Session Manager)
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
import logging

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.exc import IntegrityError

from models import Session, AppUser
from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Session Manager Agent - Session lifecycle management.

    Responsibilities:
    - Create new user sessions (mother sessions)
    - Read session details
    - Update session status and metadata
    - List sessions by user or filters
    - Validate session transitions
    - Generate audit events for all operations

    Critical Rules:
    1. Sessions must belong to an existing user
    2. Sessions must have an objective (what user wants to accomplish)
    3. Sessions must have LLM model locked at creation for reproducibility
    4. Status transitions: active ↔ paused → archived
    5. All operations logged via Audit Logger
    6. User can only access their own sessions (enforced by caller)
    """

    # Valid status transitions
    VALID_TRANSITIONS = {
        "active": ["paused", "archived"],
        "paused": ["active", "archived"],
        "archived": []  # Terminal status
    }

    def __init__(self, db: DBSession, audit_logger: Optional[AuditLogger] = None):
        """
        Initialize Session Manager.

        Args:
            db: SQLAlchemy database session
            audit_logger: Optional AuditLogger instance (will create if not provided)
        """
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

    def create_session(
        self,
        user_id: UUID,
        objective: str,
        llm_id: str,
        llm_version: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a new user session.

        Args:
            user_id: UUID of the user creating the session
            objective: What the user wants to accomplish (required)
            llm_id: LLM model identifier (e.g., "claude-3-sonnet")
            llm_version: LLM version (locked for reproducibility, e.g., "20240229")
            title: Optional human-readable title
            metadata: Optional additional metadata (JSONB)

        Returns:
            Dict with session info:
                - session_id: UUID
                - owner_user_id: UUID
                - objective: str
                - llm_id: str
                - llm_version: str
                - status: "active"
                - created_at: ISO timestamp
                - title, metadata if provided

        Raises:
            ValueError: If user doesn't exist or objective is empty
        """
        # Validate user exists
        user = self.db.query(AppUser).filter_by(id=user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Validate objective
        if not objective or not objective.strip():
            raise ValueError("Objective is required and cannot be empty")

        # Validate LLM info
        if not llm_id or not llm_version:
            raise ValueError("llm_id and llm_version are required")

        # Create session
        session_id = uuid4()

        new_session = Session(
            id=session_id,
            owner_user_id=user_id,
            objective=objective.strip(),
            title=title,
            status="active",
            llm_id=llm_id,
            llm_version=llm_version,
            session_metadata=metadata or {}
        )

        self.db.add(new_session)
        self.db.flush()

        logger.info(f"[SessionManager] Created session {session_id} for user {user_id}")

        # Log audit event
        self.audit_logger.log(
            event_type="session.created",
            actor_type="user",
            actor_id=str(user_id),
            action_verb="created",
            entity_type="session",
            entity_id=str(session_id),
            context={
                "session_id": str(session_id),
                "llm_id": llm_id,
                "llm_version": llm_version
            },
            result_status="success"
        )

        return self._session_to_dict(new_session)

    def get_session(
        self,
        session_id: UUID,
        user_id: Optional[UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get session by ID.

        Args:
            session_id: UUID of the session
            user_id: Optional user_id for authorization check

        Returns:
            Dict with session info, or None if not found

        Raises:
            ValueError: If session exists but belongs to different user
        """
        session = self.db.query(Session).filter_by(id=session_id).first()

        if not session:
            return None

        # Authorization check
        if user_id and session.owner_user_id != user_id:
            raise ValueError(f"Session {session_id} does not belong to user {user_id}")

        return self._session_to_dict(session)

    def update_session(
        self,
        session_id: UUID,
        user_id: UUID,
        new_status: Optional[str] = None,
        title: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Update session status, title, and/or metadata.

        Args:
            session_id: UUID of the session
            user_id: UUID of the user (for authorization)
            new_status: Optional new status (must be valid transition)
            title: Optional new title
            metadata_updates: Optional metadata updates (merged with existing)

        Returns:
            Dict with updated session info

        Raises:
            ValueError: If session not found, unauthorized, or invalid status transition
        """
        session = self.db.query(Session).filter_by(id=session_id).first()

        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Authorization check
        if session.owner_user_id != user_id:
            raise ValueError(f"Session {session_id} does not belong to user {user_id}")

        # Update status if provided
        old_status = session.status
        if new_status:
            self._validate_status_transition(old_status, new_status)
            session.status = new_status
            logger.info(f"[SessionManager] Session {session_id} status: {old_status} → {new_status}")

        # Update title if provided
        if title is not None:
            session.title = title

        # Update metadata if provided
        if metadata_updates:
            current_metadata = session.session_metadata or {}
            current_metadata.update(metadata_updates)
            session.session_metadata = current_metadata

        session.updated_at = datetime.utcnow()
        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type="session.updated",
            actor_type="user",
            actor_id=str(user_id),
            action_verb="updated",
            entity_type="session",
            entity_id=str(session_id),
            context={
                "session_id": str(session_id),
                "old_status": old_status,
                "new_status": new_status or old_status
            },
            result_status="success",
            metadata=metadata_updates
        )

        return self._session_to_dict(session)

    def list_sessions(
        self,
        user_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List sessions with optional filters.

        Args:
            user_id: Optional filter by user
            status: Optional filter by status (active, paused, archived)
            limit: Max number of results (default 50, max 100)
            offset: Pagination offset

        Returns:
            List of session dicts
        """
        if limit > 100:
            limit = 100

        query = self.db.query(Session)

        if user_id:
            query = query.filter_by(owner_user_id=user_id)

        if status:
            query = query.filter_by(status=status)

        # Order by most recent first
        query = query.order_by(Session.created_at.desc())

        # Pagination
        sessions = query.limit(limit).offset(offset).all()

        return [self._session_to_dict(s) for s in sessions]

    def delete_session(
        self,
        session_id: UUID,
        user_id: UUID
    ) -> Dict[str, str]:
        """
        Delete a session (only if status is not archived).

        Args:
            session_id: UUID of the session
            user_id: UUID of the user (for authorization)

        Returns:
            Dict with success message

        Raises:
            ValueError: If session not found, unauthorized, or already archived
        """
        session = self.db.query(Session).filter_by(id=session_id).first()

        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Authorization check
        if session.owner_user_id != user_id:
            raise ValueError(f"Session {session_id} does not belong to user {user_id}")

        # Cannot delete archived sessions (permanent record)
        if session.status == "archived":
            raise ValueError(f"Cannot delete archived session (permanent record)")

        # Delete session (CASCADE will handle related records)
        self.db.delete(session)
        self.db.flush()

        logger.info(f"[SessionManager] Deleted session {session_id}")

        # Log audit event
        self.audit_logger.log(
            event_type="session.deleted",
            actor_type="user",
            actor_id=str(user_id),
            action_verb="deleted",
            entity_type="session",
            entity_id=str(session_id),
            context={"session_id": str(session_id)},
            result_status="success"
        )

        return {"message": f"Session {session_id} deleted successfully"}

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

    def _session_to_dict(self, session: Session) -> Dict[str, Any]:
        """
        Convert Session model to dict.

        Args:
            session: Session model instance

        Returns:
            Dict representation
        """
        return {
            "session_id": str(session.id),
            "owner_user_id": str(session.owner_user_id),
            "objective": session.objective,
            "title": session.title,
            "status": session.status,
            "llm_id": session.llm_id,
            "llm_version": session.llm_version,
            "metadata": session.session_metadata,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat() if session.updated_at else None
        }
