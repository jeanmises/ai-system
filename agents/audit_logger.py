"""
Audit Logger Agent - CRITICAL for system governance.

This agent logs ALL system events in an append-only table.
NO UPDATE or DELETE operations are allowed on audit_event table.

Based on: SYSTEM_FOUNDATION.md Section 9 (Audit & Determinism)
Contract: 01_audit_logger_contract.json
"""

from datetime import datetime
from typing import Dict, Any, Optional
from uuid import uuid4
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from models import AuditEvent

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Audit Logger Agent - Append-only event logging.

    Responsibilities:
    - Log all system events in append-only audit_event table
    - Validate input schema
    - Ensure atomicity (event written in same transaction)
    - Return event confirmation with event_id and timestamp

    Critical Rules:
    1. APPEND-ONLY: Never UPDATE or DELETE audit events
    2. ATOMIC: Event must be written before action succeeds
    3. MANDATORY: All fields must be provided
    4. TIMESTAMPED: UTC timestamp with timezone
    """

    def __init__(self, db: Session):
        """
        Initialize Audit Logger.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def log(
        self,
        event_type: str,
        actor_type: str,
        actor_id: str,
        action_verb: str,
        entity_type: str,
        entity_id: str,
        context: Dict[str, Any],
        result_status: str,
        result_error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log an audit event.

        Args:
            event_type: Event type in format "namespace.action" (e.g., "session.created")
            actor_type: Type of actor ("user" | "agent" | "system")
            actor_id: ID of the actor (user_id, agent_id, or "system")
            action_verb: Action performed ("created" | "updated" | "deleted" | "read" | ...)
            entity_type: Type of entity affected ("session" | "user" | "job" | ...)
            entity_id: ID of the entity
            context: Context dict (must include session_id, request_id, etc.)
            result_status: Result status ("success" | "failure")
            result_error: Error message if status is failure
            metadata: Additional metadata (optional)

        Returns:
            Dict with:
                - event_id: UUID of created event
                - timestamp: ISO8601 timestamp
                - persisted: True if successfully written to DB

        Raises:
            ValueError: If required fields are missing or invalid
            SQLAlchemyError: If database write fails
        """
        # Validate required fields
        self._validate_input(
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            action_verb=action_verb,
            entity_type=entity_type,
            entity_id=entity_id,
            context=context,
            result_status=result_status
        )

        # Generate event ID
        event_id = uuid4()

        # Create audit event
        audit_event = AuditEvent(
            id=event_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            action_verb=action_verb,
            entity_type=entity_type,
            entity_id=entity_id,
            context=context,
            result_status=result_status,
            result_error=result_error,
            extra_metadata=metadata
        )

        try:
            # Write to database (APPEND-ONLY)
            self.db.add(audit_event)
            self.db.flush()  # Flush to get timestamp but don't commit yet

            # Get timestamp after flush
            timestamp = audit_event.timestamp

            logger.info(
                f"[AuditLogger] Event logged: {event_type} | "
                f"Actor: {actor_type}/{actor_id} | "
                f"Entity: {entity_type}/{entity_id} | "
                f"Result: {result_status}"
            )

            return {
                "event_id": str(event_id),
                "timestamp": timestamp.isoformat(),
                "persisted": True
            }

        except SQLAlchemyError as e:
            logger.error(f"[AuditLogger] Failed to write event: {e}")
            self.db.rollback()
            raise

    def _validate_input(
        self,
        event_type: str,
        actor_type: str,
        actor_id: str,
        action_verb: str,
        entity_type: str,
        entity_id: str,
        context: Dict[str, Any],
        result_status: str
    ):
        """
        Validate audit event input.

        Raises:
            ValueError: If validation fails
        """
        # Check required fields are not empty
        if not event_type or not event_type.strip():
            raise ValueError("event_type is required and cannot be empty")

        if not actor_type or not actor_type.strip():
            raise ValueError("actor_type is required and cannot be empty")

        if not actor_id or not actor_id.strip():
            raise ValueError("actor_id is required and cannot be empty")

        if not action_verb or not action_verb.strip():
            raise ValueError("action_verb is required and cannot be empty")

        if not entity_type or not entity_type.strip():
            raise ValueError("entity_type is required and cannot be empty")

        if not entity_id or not entity_id.strip():
            raise ValueError("entity_id is required and cannot be empty")

        # Validate actor_type
        valid_actor_types = ["user", "agent", "system"]
        if actor_type not in valid_actor_types:
            raise ValueError(
                f"actor_type must be one of {valid_actor_types}, got: {actor_type}"
            )

        # Validate result_status
        valid_statuses = ["success", "failure"]
        if result_status not in valid_statuses:
            raise ValueError(
                f"result_status must be one of {valid_statuses}, got: {result_status}"
            )

        # Validate context is dict
        if not isinstance(context, dict):
            raise ValueError(f"context must be a dict, got: {type(context)}")

        # Validate event_type format (should contain a dot)
        if "." not in event_type:
            raise ValueError(
                f"event_type should be in format 'namespace.action', got: {event_type}"
            )

    def query_events(
        self,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """
        Query audit events (for debugging/monitoring).

        Args:
            session_id: Filter by session_id in context
            event_type: Filter by event_type
            actor_id: Filter by actor_id
            limit: Maximum number of events to return

        Returns:
            List of audit event dicts
        """
        query = self.db.query(AuditEvent)

        # Apply filters
        if session_id:
            query = query.filter(AuditEvent.context["session_id"].astext == session_id)

        if event_type:
            query = query.filter(AuditEvent.event_type == event_type)

        if actor_id:
            query = query.filter(AuditEvent.actor_id == actor_id)

        # Order by timestamp descending (most recent first)
        query = query.order_by(AuditEvent.timestamp.desc())

        # Limit results
        query = query.limit(limit)

        # Execute and return
        events = query.all()

        return [
            {
                "event_id": str(event.id),
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "action_verb": event.action_verb,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "result_status": event.result_status,
                "result_error": event.result_error,
                "context": event.context,
                "metadata": event.extra_metadata
            }
            for event in events
        ]
