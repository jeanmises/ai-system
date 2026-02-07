"""
Tests for Audit Logger Agent.

Based on EXECUTION_PLAN.md Step 1 acceptance criteria.
"""

import pytest
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from models import Base, AuditEvent
from agents.audit_logger import AuditLogger


# Test database URL (use same PostgreSQL as main app)
TEST_DATABASE_URL = "postgresql://ai_user:ai_password@localhost:5432/ai_system"


@pytest.fixture
def db_session():
    """
    Create a test database session.

    Uses PostgreSQL with transaction rollback for isolation.
    """
    engine = create_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    # Rollback transaction (test changes are not persisted)
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def audit_logger(db_session):
    """Create an AuditLogger instance."""
    return AuditLogger(db_session)


# ==============================================================================
# UNIT TESTS
# ==============================================================================

def test_audit_event_created(audit_logger, db_session):
    """Test that audit event is created successfully."""
    # Log an event
    result = audit_logger.log(
        event_type="test.created",
        actor_type="user",
        actor_id="user-123",
        action_verb="created",
        entity_type="test_entity",
        entity_id="entity-456",
        context={"session_id": "sess-789", "request_id": "req-abc"},
        result_status="success"
    )

    # Commit to save
    db_session.commit()

    # Verify result
    assert result["persisted"] is True
    assert "event_id" in result
    assert "timestamp" in result

    # Verify in database
    event = db_session.query(AuditEvent).filter_by(
        event_type="test.created"
    ).first()

    assert event is not None
    assert event.actor_type == "user"
    assert event.actor_id == "user-123"
    assert event.entity_type == "test_entity"
    assert event.result_status == "success"


def test_audit_validation_empty_event_type(audit_logger):
    """Test that validation fails for empty event_type."""
    with pytest.raises(ValueError, match="event_type is required"):
        audit_logger.log(
            event_type="",
            actor_type="user",
            actor_id="user-123",
            action_verb="created",
            entity_type="test",
            entity_id="123",
            context={},
            result_status="success"
        )


def test_audit_validation_invalid_actor_type(audit_logger):
    """Test that validation fails for invalid actor_type."""
    with pytest.raises(ValueError, match="actor_type must be one of"):
        audit_logger.log(
            event_type="test.created",
            actor_type="invalid_type",
            actor_id="user-123",
            action_verb="created",
            entity_type="test",
            entity_id="123",
            context={},
            result_status="success"
        )


def test_audit_validation_invalid_result_status(audit_logger):
    """Test that validation fails for invalid result_status."""
    with pytest.raises(ValueError, match="result_status must be one of"):
        audit_logger.log(
            event_type="test.created",
            actor_type="user",
            actor_id="user-123",
            action_verb="created",
            entity_type="test",
            entity_id="123",
            context={},
            result_status="invalid_status"
        )


def test_audit_validation_event_type_format(audit_logger):
    """Test that event_type must be in format 'namespace.action'."""
    with pytest.raises(ValueError, match="format 'namespace.action'"):
        audit_logger.log(
            event_type="invalid_format",  # Missing dot
            actor_type="user",
            actor_id="user-123",
            action_verb="created",
            entity_type="test",
            entity_id="123",
            context={},
            result_status="success"
        )


def test_audit_with_error(audit_logger, db_session):
    """Test logging an event with failure status and error."""
    result = audit_logger.log(
        event_type="test.failed",
        actor_type="system",
        actor_id="system",
        action_verb="attempted",
        entity_type="test",
        entity_id="123",
        context={"session_id": "sess-789"},
        result_status="failure",
        result_error="Test error message"
    )

    db_session.commit()

    # Verify error is stored
    event = db_session.query(AuditEvent).filter_by(
        event_type="test.failed"
    ).first()

    assert event is not None
    assert event.result_status == "failure"
    assert event.result_error == "Test error message"


def test_audit_with_metadata(audit_logger, db_session):
    """Test logging an event with additional metadata."""
    result = audit_logger.log(
        event_type="test.with_metadata",
        actor_type="agent",
        actor_id="agent-123",
        action_verb="processed",
        entity_type="test",
        entity_id="123",
        context={"session_id": "sess-789"},
        result_status="success",
        metadata={"custom_field": "custom_value", "count": 42}
    )

    db_session.commit()

    # Verify metadata is stored
    event = db_session.query(AuditEvent).filter_by(
        event_type="test.with_metadata"
    ).first()

    assert event is not None
    assert event.extra_metadata is not None
    assert event.extra_metadata["custom_field"] == "custom_value"
    assert event.extra_metadata["count"] == 42


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

def test_audit_query_by_session(audit_logger, db_session):
    """Test querying audit events by session_id."""
    session_id = "sess-test-123"

    # Log multiple events for same session
    for i in range(3):
        audit_logger.log(
            event_type=f"test.event_{i}",
            actor_type="user",
            actor_id="user-123",
            action_verb="created",
            entity_type="test",
            entity_id=f"entity-{i}",
            context={"session_id": session_id},
            result_status="success"
        )

    db_session.commit()

    # Query events for this session
    events = audit_logger.query_events(session_id=session_id)

    assert len(events) == 3
    assert all(e["context"]["session_id"] == session_id for e in events)


def test_audit_query_by_event_type(audit_logger, db_session):
    """Test querying audit events by event_type."""
    # Log different event types
    audit_logger.log(
        event_type="session.created",
        actor_type="user",
        actor_id="user-123",
        action_verb="created",
        entity_type="session",
        entity_id="sess-1",
        context={"session_id": "sess-1"},
        result_status="success"
    )

    audit_logger.log(
        event_type="session.updated",
        actor_type="user",
        actor_id="user-123",
        action_verb="updated",
        entity_type="session",
        entity_id="sess-1",
        context={"session_id": "sess-1"},
        result_status="success"
    )

    db_session.commit()

    # Query only 'created' events
    events = audit_logger.query_events(event_type="session.created")

    assert len(events) == 1
    assert events[0]["event_type"] == "session.created"


def test_audit_atomicity(audit_logger, db_session):
    """Test that audit event is written atomically."""
    # Log event
    result = audit_logger.log(
        event_type="test.atomic",
        actor_type="user",
        actor_id="user-123",
        action_verb="created",
        entity_type="test",
        entity_id="123",
        context={"session_id": "sess-789"},
        result_status="success"
    )

    # Event ID returned immediately after flush
    assert result["persisted"] is True

    # But not committed yet - rollback should remove it
    db_session.rollback()

    # Verify event NOT in database after rollback
    event = db_session.query(AuditEvent).filter_by(
        event_type="test.atomic"
    ).first()

    assert event is None


# ==============================================================================
# RUN TESTS
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
