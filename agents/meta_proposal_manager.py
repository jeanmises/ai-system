"""
Meta-Proposal Manager - System self-evolution proposals.

Manages proposals for system improvements and evolution.

Based on: SYSTEM_FOUNDATION.md Meta-Evolution
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
import logging

from sqlalchemy.orm import Session as DBSession

from models import MetaProposal, Session
from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class MetaProposalManager:
    """
    Meta-Proposal Manager - System evolution proposals.

    Responsibilities:
    - Create improvement proposals
    - Review and validate proposals
    - Track proposal lifecycle
    - Enforce governance rules
    - Generate audit events

    Critical Rules:
    1. All proposals require explicit approval
    2. Proposals are versioned and immutable
    3. Safety checks before execution
    4. Rollback capability required
    5. All changes audited
    """

    VALID_TRANSITIONS = {
        "draft": ["submitted", "cancelled"],
        "submitted": ["under_review", "rejected"],
        "under_review": ["approved", "rejected", "needs_revision"],
        "needs_revision": ["submitted", "cancelled"],
        "approved": ["scheduled", "rejected"],
        "scheduled": ["executing", "cancelled"],
        "executing": ["completed", "failed"],
        "completed": ["archived"],
        "failed": ["needs_revision", "archived"],
        "rejected": ["archived"],
        "cancelled": ["archived"],
        "archived": []
    }

    def __init__(
        self,
        db: DBSession,
        audit_logger: Optional[AuditLogger] = None
    ):
        """Initialize Meta-Proposal Manager."""
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

    def create_proposal(
        self,
        session_id: UUID,
        title: str,
        description: str,
        category: str,
        proposed_changes: Dict[str, Any],
        impact_assessment: Dict[str, Any],
        rollback_plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a new meta-proposal.

        Args:
            session_id: Session that generated this proposal
            title: Short title
            description: Detailed description
            category: Category (agent_improvement, catalog_update, config_change, etc.)
            proposed_changes: What to change (structured data)
            impact_assessment: Expected impact analysis
            rollback_plan: How to rollback if needed

        Returns:
            Dict with proposal info

        Raises:
            ValueError: If validation fails
        """
        # Validate session exists
        session = self.db.query(Session).filter_by(id=session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Create proposal
        proposal_id = uuid4()

        proposal = MetaProposal(
            id=proposal_id,
            session_id=session_id,
            title=title,
            description=description,
            category=category,
            status="draft",
            proposed_changes=proposed_changes,
            impact_assessment=impact_assessment,
            rollback_plan=rollback_plan,
            created_at=datetime.utcnow()
        )

        self.db.add(proposal)
        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type="meta_proposal.created",
            actor_type="agent",
            actor_id="meta_proposal_manager",
            action_verb="created",
            entity_type="meta_proposal",
            entity_id=str(proposal_id),
            context={
                "session_id": str(session_id),
                "category": category,
                "title": title[:100]
            },
            result_status="success"
        )

        logger.info(f"[MetaProposalManager] Created proposal {proposal_id}: {title}")

        return self._proposal_to_dict(proposal)

    def update_proposal_status(
        self,
        proposal_id: UUID,
        new_status: str,
        reviewer_notes: Optional[str] = None,
        execution_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Update proposal status."""
        proposal = self.db.query(MetaProposal).filter_by(id=proposal_id).first()

        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")

        # Validate transition
        old_status = proposal.status
        self._validate_transition(old_status, new_status)

        # Update
        proposal.status = new_status
        proposal.updated_at = datetime.utcnow()

        if reviewer_notes:
            proposal.reviewer_notes = reviewer_notes

        if execution_result:
            proposal.execution_result = execution_result

        if new_status == "approved":
            proposal.approved_at = datetime.utcnow()
        elif new_status in ["completed", "failed"]:
            proposal.executed_at = datetime.utcnow()

        self.db.flush()

        # Log audit event
        self.audit_logger.log(
            event_type=f"meta_proposal.{new_status}",
            actor_type="agent",
            actor_id="meta_proposal_manager",
            action_verb=new_status,
            entity_type="meta_proposal",
            entity_id=str(proposal_id),
            context={
                "old_status": old_status,
                "new_status": new_status,
                "category": proposal.category
            },
            result_status="success" if new_status == "completed" else ("failure" if new_status == "failed" else "success")
        )

        logger.info(f"[MetaProposalManager] Proposal {proposal_id} status: {old_status} → {new_status}")

        return self._proposal_to_dict(proposal)

    def list_proposals(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List proposals with filters."""
        query = self.db.query(MetaProposal)

        if status:
            query = query.filter_by(status=status)

        if category:
            query = query.filter_by(category=category)

        query = query.order_by(MetaProposal.created_at.desc())
        proposals = query.limit(limit).all()

        return [self._proposal_to_dict(p) for p in proposals]

    def _validate_transition(self, old_status: str, new_status: str):
        """Validate status transition."""
        if old_status not in self.VALID_TRANSITIONS:
            raise ValueError(f"Invalid status: {old_status}")

        allowed = self.VALID_TRANSITIONS[old_status]
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {old_status} → {new_status}. "
                f"Allowed: {', '.join(allowed) if allowed else 'none'}"
            )

    def _proposal_to_dict(self, proposal: MetaProposal) -> Dict[str, Any]:
        """Convert MetaProposal to dict."""
        return {
            "proposal_id": str(proposal.id),
            "session_id": str(proposal.session_id),
            "title": proposal.title,
            "description": proposal.description,
            "category": proposal.category,
            "status": proposal.status,
            "proposed_changes": proposal.proposed_changes,
            "impact_assessment": proposal.impact_assessment,
            "rollback_plan": proposal.rollback_plan,
            "reviewer_notes": proposal.reviewer_notes,
            "execution_result": proposal.execution_result,
            "created_at": proposal.created_at.isoformat(),
            "approved_at": proposal.approved_at.isoformat() if proposal.approved_at else None,
            "executed_at": proposal.executed_at.isoformat() if proposal.executed_at else None,
            "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None
        }
