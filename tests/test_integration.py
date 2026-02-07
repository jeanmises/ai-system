"""
Integration Tests - Complete system flow testing.

Tests the entire system from end-to-end.
"""

import pytest
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base
from agents.session_manager import SessionManager
from agents.job_manager import JobManager
from agents.llm_proxy import LLMProxy
from agents.subsession_manager import SubSessionManager
from agents.meta_proposal_manager import MetaProposalManager
from agents.sandbox_manager import SandboxManager
from agents.audit_logger import AuditLogger

# Test database
TEST_DATABASE_URL = "postgresql://ai_user:ai_password@localhost:5432/ai_system"


@pytest.fixture
def db_session():
    """Create test database session with transaction rollback."""
    engine = create_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def audit_logger(db_session):
    """Create audit logger instance."""
    return AuditLogger(db_session)


@pytest.fixture
def session_manager(db_session, audit_logger):
    """Create session manager instance."""
    return SessionManager(db_session, audit_logger)


@pytest.fixture
def job_manager(db_session, audit_logger):
    """Create job manager instance."""
    return JobManager(db_session, audit_logger)


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

def test_complete_workflow(session_manager, job_manager, db_session):
    """Test complete workflow: create session, create job, verify audit."""
    # 1. Create user (mock)
    from models import AppUser
    user = AppUser(
        id=uuid4(),
        external_id="test_user_integration",
        provider="test",
        email="integration@test.com",
        is_active=True
    )
    db_session.add(user)
    db_session.flush()

    # 2. Create session
    session = session_manager.create_session(
        user_id=user.id,
        objective="Integration test workflow",
        llm_id="claude-3-haiku-20240307",
        llm_version="20240307",
        title="Integration Test"
    )

    assert session["status"] == "active"
    assert session["objective"] == "Integration test workflow"

    # 3. Create job
    job = job_manager.create_job(
        session_id=uuid4(session["session_id"]),
        job_type="integration_test",
        payload={"test": "data"},
        timeout_seconds=60
    )

    assert job["status"] == "PENDING"
    assert job["job_type"] == "integration_test"

    # 4. Update job status
    updated_job = job_manager.update_job_status(
        job_id=uuid4(job["job_id"]),
        new_status="RUNNING"
    )

    assert updated_job["status"] == "RUNNING"
    assert updated_job["attempt_count"] == 1

    # 5. Complete job
    completed_job = job_manager.update_job_status(
        job_id=uuid4(job["job_id"]),
        new_status="COMPLETED",
        result={"success": True, "result": "Integration test passed"}
    )

    assert completed_job["status"] == "COMPLETED"
    assert completed_job["result"]["success"] is True

    # 6. Verify audit trail
    audit_logger = AuditLogger(db_session)
    events = audit_logger.query_events(
        session_id=session["session_id"],
        limit=10
    )

    # Should have events for: session.created, job.created, job.running, job.completed
    assert len(events) >= 4

    event_types = [e["event_type"] for e in events]
    assert "session.created" in event_types
    assert "job.created" in event_types
    assert "job.running" in event_types
    assert "job.completed" in event_types


def test_subsession_isolation(session_manager, db_session):
    """Test subsession creation and isolation."""
    # Create user
    from models import AppUser
    user = AppUser(
        id=uuid4(),
        external_id="test_subsession_user",
        provider="test",
        email="subsession@test.com",
        is_active=True
    )
    db_session.add(user)
    db_session.flush()

    # Create parent session
    session = session_manager.create_session(
        user_id=user.id,
        objective="Test subsessions",
        llm_id="test-model",
        llm_version="1.0.0"
    )

    # Create subsessions
    subsession_manager = SubSessionManager(db_session)

    subsession1 = subsession_manager.create_subsession(
        parent_session_id=uuid4(session["session_id"]),
        objective="Subtask 1",
        input_snapshot={"data": "input1"}
    )

    subsession2 = subsession_manager.create_subsession(
        parent_session_id=uuid4(session["session_id"]),
        objective="Subtask 2",
        input_snapshot={"data": "input2"}
    )

    # Verify isolation
    assert subsession1["subsession_id"] != subsession2["subsession_id"]
    assert subsession1["parent_session_id"] == subsession2["parent_session_id"]
    assert subsession1["input_snapshot"] != subsession2["input_snapshot"]

    # List subsessions
    subsessions = subsession_manager.list_subsessions(
        parent_session_id=uuid4(session["session_id"])
    )

    assert len(subsessions) == 2


def test_meta_proposal_workflow(session_manager, db_session):
    """Test meta-proposal creation and approval workflow."""
    # Create user and session
    from models import AppUser
    user = AppUser(
        id=uuid4(),
        external_id="test_meta_user",
        provider="test",
        email="meta@test.com",
        is_active=True
    )
    db_session.add(user)
    db_session.flush()

    session = session_manager.create_session(
        user_id=user.id,
        objective="Test meta-proposals",
        llm_id="test-model",
        llm_version="1.0.0"
    )

    # Create meta-proposal
    meta_manager = MetaProposalManager(db_session)

    proposal = meta_manager.create_proposal(
        session_id=uuid4(session["session_id"]),
        title="Improve job scheduling",
        description="Add priority-based scheduling to job manager",
        category="agent_improvement",
        proposed_changes={
            "agent": "job_manager",
            "changes": ["Add priority queue", "Update dequeue logic"]
        },
        impact_assessment={
            "risk": "low",
            "affected_components": ["job_manager", "worker"],
            "estimated_effort": "2 hours"
        },
        rollback_plan={
            "strategy": "revert_code",
            "backup_required": True
        }
    )

    assert proposal["status"] == "draft"

    # Submit for review
    proposal = meta_manager.update_proposal_status(
        proposal_id=uuid4(proposal["proposal_id"]),
        new_status="submitted"
    )

    assert proposal["status"] == "submitted"

    # Move through workflow
    proposal = meta_manager.update_proposal_status(
        proposal_id=uuid4(proposal["proposal_id"]),
        new_status="under_review"
    )

    proposal = meta_manager.update_proposal_status(
        proposal_id=uuid4(proposal["proposal_id"]),
        new_status="approved",
        reviewer_notes="Looks good, proceed with implementation"
    )

    assert proposal["status"] == "approved"
    assert proposal["reviewer_notes"] is not None


def test_sandbox_execution(db_session):
    """Test sandbox execution."""
    # Create mock proposal
    from models import MetaProposal, Session as SessionModel, AppUser

    user = AppUser(
        id=uuid4(),
        external_id="test_sandbox_user",
        provider="test",
        email="sandbox@test.com",
        is_active=True
    )
    db_session.add(user)
    db_session.flush()

    session = SessionModel(
        id=uuid4(),
        owner_user_id=user.id,
        objective="Test sandbox",
        llm_id="test-model",
        llm_version="1.0.0",
        status="active"
    )
    db_session.add(session)
    db_session.flush()

    proposal = MetaProposal(
        id=uuid4(),
        session_id=session.id,
        title="Test proposal",
        description="Testing sandbox",
        category="config_change",
        status="approved",
        proposed_changes={"test": "change"},
        impact_assessment={"risk": "low"},
        rollback_plan={"strategy": "revert"}
    )
    db_session.add(proposal)
    db_session.flush()

    # Execute in sandbox
    sandbox_manager = SandboxManager(db_session)

    sandbox_run = sandbox_manager.create_sandbox_run(
        meta_proposal_id=proposal.id,
        execution_type="integration_test",
        code_or_config={"test_code": "print('Hello from sandbox')"}
    )

    # Verify execution
    assert sandbox_run["status"] in ["completed", "running"]
    assert sandbox_run["meta_proposal_id"] == str(proposal.id)

    # If completed, verify output
    if sandbox_run["status"] == "completed":
        assert sandbox_run["output_data"] is not None
        assert "success" in sandbox_run["output_data"]


# ==============================================================================
# RUN TESTS
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
