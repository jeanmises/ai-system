"""
Database models for AI System.
Based on SYSTEM_FOUNDATION.md Section 10: Database Entities.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


# ==============================================================================
# CORE TABLES
# ==============================================================================


class AppUser(Base):
    """User table synchronized from OIDC provider."""

    __tablename__ = "app_user"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id = Column(String(255), nullable=False, comment="OIDC sub claim")
    provider = Column(String(255), nullable=False, comment="OIDC iss claim")
    email = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_app_user_provider_external_id"),
        Index("idx_app_user_email", "email"),
        Index("idx_app_user_active", "is_active"),
    )


class Session(Base):
    """Mother session - user's persistent work session."""

    __tablename__ = "session"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id = Column(PG_UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    objective = Column(Text, nullable=False)
    title = Column(String(255), nullable=True)
    status = Column(String(50), default="active", nullable=False, comment="active | paused | archived")
    llm_id = Column(String(100), nullable=False, comment="LLM model identifier")
    llm_version = Column(String(50), nullable=False, comment="Locked at creation for reproducibility")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    session_metadata = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_session_owner", "owner_user_id"),
        Index("idx_session_status", "status"),
        Index("idx_session_created", "created_at"),
    )


class SubSession(Base):
    """Child subsession - isolated work unit."""

    __tablename__ = "subsession"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    parent_session_id = Column(PG_UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"), nullable=False)
    objective = Column(Text, nullable=False)
    agent_id = Column(String(100), nullable=False, comment="From catalog")
    agent_version = Column(String(50), nullable=False, comment="Semantic version")
    status = Column(String(50), default="running", nullable=False, comment="running | completed | failed")
    input_snapshot = Column(JSONB, nullable=False, comment="Read-only input data snapshot")
    output = Column(JSONB, nullable=True, comment="Structured output")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_subsession_parent", "parent_session_id"),
        Index("idx_subsession_status", "status"),
        Index("idx_subsession_agent", "agent_id", "agent_version"),
    )


class Job(Base):
    """Asynchronous job queue entry."""

    __tablename__ = "job"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_type = Column(String(100), nullable=False, comment="From catalog")
    session_id = Column(PG_UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"), nullable=False)
    subsession_id = Column(PG_UUID(as_uuid=True), ForeignKey("subsession.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="PENDING", nullable=False, comment="PENDING | SCHEDULED | RUNNING | COMPLETED | FAILED")
    payload = Column(JSONB, nullable=False)
    result = Column(JSONB, nullable=True)
    timeout_seconds = Column(Integer, nullable=False)
    max_retries = Column(Integer, nullable=False)
    attempt_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_job_status", "status"),
        Index("idx_job_session", "session_id"),
        Index("idx_job_type", "job_type"),
        Index("idx_job_created", "created_at"),
    )


# ==============================================================================
# CATALOG TABLES
# ==============================================================================


class Agent(Base):
    """Agent catalog - versioned operational agents."""

    __tablename__ = "agent"

    id = Column(String(100), primary_key=True, comment="e.g., 'llm-proxy'")
    version = Column(String(50), primary_key=True, comment="Semantic version")
    role = Column(Text, nullable=False)
    capabilities = Column(JSONB, nullable=False, comment="Array of capabilities")
    input_schema = Column(JSONB, nullable=False, comment="JSON Schema")
    output_schema = Column(JSONB, nullable=False, comment="JSON Schema")
    status = Column(String(50), default="draft", nullable=False, comment="draft | review | published | deprecated | retired")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    extra_metadata = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_agent_status", "status"),
        Index("idx_agent_published", "published_at"),
    )


class Instruction(Base):
    """Instruction catalog - reusable instruction templates."""

    __tablename__ = "instruction"

    id = Column(String(100), primary_key=True)
    version = Column(String(50), primary_key=True, comment="Semantic version")
    template = Column(Text, nullable=False, comment="Template with placeholders")
    parameters = Column(JSONB, nullable=False, comment="Array of parameter names")
    applicable_agents = Column(JSONB, nullable=False, comment="Array of agent IDs")
    status = Column(String(50), default="draft", nullable=False, comment="draft | review | published | deprecated | retired")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_instruction_status", "status"),)


class JobType(Base):
    """Job type catalog - specifications for async jobs."""

    __tablename__ = "job_type"

    id = Column(String(100), primary_key=True)
    version = Column(String(50), primary_key=True, comment="Semantic version")
    description = Column(Text, nullable=False)
    input_schema = Column(JSONB, nullable=False, comment="JSON Schema")
    output_schema = Column(JSONB, nullable=False, comment="JSON Schema")
    timeout_seconds = Column(Integer, nullable=False)
    max_retries = Column(Integer, nullable=False)
    status = Column(String(50), default="draft", nullable=False, comment="draft | review | published | deprecated | retired")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_job_type_status", "status"),)


# ==============================================================================
# META-EVOLUTION TABLES
# ==============================================================================


class MetaProposal(Base):
    """Meta-proposal for system evolution."""

    __tablename__ = "meta_proposal"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_by_user_id = Column(PG_UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(PG_UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"), nullable=False)
    original_request = Column(Text, nullable=False, comment="User's meta: request")
    scope = Column(String(50), nullable=False, comment="workflow | catalog | parameters")
    changes = Column(JSONB, nullable=False, comment="Array of proposed changes")
    unchanged = Column(JSONB, nullable=False, comment="Array of things that stay same")
    expected_impact = Column(Text, nullable=False)
    risks = Column(JSONB, nullable=False, comment="Array of risk objects")
    status = Column(
        String(50),
        default="pending",
        nullable=False,
        comment="pending | user_confirmed | sandbox_running | sandbox_passed | sandbox_failed | production_deployed | rejected",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_meta_proposal_status", "status"),
        Index("idx_meta_proposal_user", "created_by_user_id"),
        Index("idx_meta_proposal_session", "session_id"),
    )


class SandboxRun(Base):
    """Sandbox execution results."""

    __tablename__ = "sandbox_run"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    proposal_id = Column(PG_UUID(as_uuid=True), ForeignKey("meta_proposal.id", ondelete="CASCADE"), nullable=False)
    checklist_version = Column(String(50), nullable=False)
    execution_status = Column(String(50), nullable=False, comment="success | failure")
    checklist_results = Column(JSONB, nullable=False, comment="Array of check results")
    logs = Column(Text, nullable=True)
    metrics = Column(JSONB, nullable=True)
    promotion_decision = Column(String(50), nullable=False, comment="approve | reject | iterate")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_sandbox_run_proposal", "proposal_id"),
        Index("idx_sandbox_run_status", "execution_status"),
    )


# ==============================================================================
# AUDIT TABLE (APPEND-ONLY)
# ==============================================================================


class AuditEvent(Base):
    """Append-only audit event log.

    CRITICAL: No UPDATE or DELETE allowed on this table.
    """

    __tablename__ = "audit_event"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    event_type = Column(String(100), nullable=False, comment="namespace.action")
    actor_type = Column(String(50), nullable=False, comment="user | agent | system")
    actor_id = Column(String(255), nullable=False)
    action_verb = Column(String(50), nullable=False, comment="created | updated | deleted | ...")
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(255), nullable=False)
    context = Column(JSONB, nullable=False, comment="session_id, request_id, trace_id")
    result_status = Column(String(50), nullable=False, comment="success | failure")
    result_error = Column(Text, nullable=True)
    extra_metadata = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp", postgresql_ops={"timestamp": "DESC"}),
        Index("idx_audit_event_type", "event_type"),
        Index("idx_audit_actor", "actor_type", "actor_id"),
        # GIN index for JSONB context field for fast querying
        Index("idx_audit_context", "context", postgresql_using="gin"),
    )
