"""
AI System - FastAPI Application
Phase 0: Base Setup with Health Check
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from database import get_db, check_database_connection, get_database_info
from agents.audit_logger import AuditLogger
from agents.session_manager import SessionManager
from agents.llm_proxy import LLMProxy
from agents.job_manager import JobManager
from agents.catalog_manager import CatalogManager
from agents.subsession_manager import SubSessionManager
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="AI System API",
    description="Deterministic AI System with Governance and Self-Evolution",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# LIFECYCLE EVENTS
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info("🚀 AI System API starting up...")
    logger.info("📊 Phase 0: Base Setup")
    logger.info("✅ FastAPI initialized")

    # Test database connection
    if check_database_connection():
        db_info = get_database_info()
        logger.info(f"✅ Database connected: {db_info.get('tables', 0)} tables")
    else:
        logger.warning("⚠️  Database connection failed - some endpoints may not work")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("👋 AI System API shutting down...")


# =============================================================================
# PUBLIC ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": "AI System API",
        "version": "0.1.0",
        "phase": "Phase 0 - Base Setup",
        "status": "operational",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns system health status including:
    - API status
    - Database connectivity
    - Services status
    """
    # Check database
    db_connected = check_database_connection()
    db_info = get_database_info() if db_connected else {}

    return {
        "status": "healthy" if db_connected else "degraded",
        "phase": "0.2",
        "services": {
            "api": "operational",
            "database": "connected" if db_connected else "disconnected",
            "redis": "not_checked",
            "keycloak": "not_checked"
        },
        "database": db_info if db_connected else {"connected": False},
        "message": "AI System API is running"
    }


# =============================================================================
# AUDIT ENDPOINTS (Phase 0 - Step 1)
# =============================================================================

@app.post("/audit/test")
async def test_audit_logger(db: Session = Depends(get_db)):
    """
    Test endpoint for Audit Logger.
    Creates a test audit event and returns confirmation.
    """
    audit_logger = AuditLogger(db)

    result = audit_logger.log(
        event_type="api.test_audit",
        actor_type="system",
        actor_id="api_test",
        action_verb="tested",
        entity_type="audit_logger",
        entity_id="test-1",
        context={
            "session_id": "test-session",
            "request_id": "test-request",
            "endpoint": "/audit/test"
        },
        result_status="success",
        metadata={"test": True, "message": "Audit logger test successful"}
    )

    db.commit()

    return {
        "message": "Audit event logged successfully",
        "event": result
    }


@app.get("/audit/events")
async def get_audit_events(
    session_id: str = None,
    event_type: str = None,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Get recent audit events (for debugging/monitoring).

    Query parameters:
    - session_id: Filter by session_id
    - event_type: Filter by event_type
    - limit: Max number of events (default 10, max 100)
    """
    if limit > 100:
        limit = 100

    audit_logger = AuditLogger(db)
    events = audit_logger.query_events(
        session_id=session_id,
        event_type=event_type,
        limit=limit
    )

    return {
        "count": len(events),
        "events": events
    }


# =============================================================================
# PROTECTED ENDPOINTS (Require Authentication)
# =============================================================================

@app.get("/me")
async def get_current_user_info(user=Depends(get_current_user)):
    """
    Get current authenticated user information.

    Requires: Bearer token in Authorization header

    Returns user info from token + database.
    """
    return {
        "message": "Authentication successful",
        "user": user
    }


@app.get("/protected/test")
async def protected_test(user=Depends(get_current_user)):
    """
    Test endpoint that requires authentication.

    Requires: Bearer token in Authorization header
    """
    return {
        "message": f"Hello {user['display_name'] or user['email']}!",
        "user_id": user["user_id"],
        "email": user["email"],
        "authenticated": True
    }


# =============================================================================
# PYDANTIC MODELS (Request/Response schemas)
# =============================================================================

class SessionCreate(BaseModel):
    """Request body for creating a session."""
    objective: str
    llm_id: str
    llm_version: str
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionUpdate(BaseModel):
    """Request body for updating a session."""
    status: Optional[str] = None
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LLMCallRequest(BaseModel):
    """Request body for LLM call."""
    session_id: str
    messages: List[Dict[str, str]]
    model_id: Optional[str] = None
    llm_config: Optional[Dict[str, Any]] = None
    timeout_ms: Optional[int] = None


class JobCreate(BaseModel):
    """Request body for creating a job."""
    session_id: str
    job_type: str
    payload: Dict[str, Any]
    timeout_seconds: Optional[int] = 300
    max_retries: Optional[int] = 3


class JobStatusUpdate(BaseModel):
    """Request body for updating job status."""
    status: str
    result: Optional[Dict[str, Any]] = None


# =============================================================================
# SESSION ENDPOINTS (Phase 0.3)
# =============================================================================

@app.post("/sessions")
async def create_session(
    request: SessionCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new session.

    Requires: Bearer token in Authorization header

    Body:
        - objective: What you want to accomplish (required)
        - llm_id: LLM model identifier (e.g., "claude-3-sonnet")
        - llm_version: LLM version (locked for reproducibility)
        - title: Optional human-readable title
        - metadata: Optional additional metadata

    Returns:
        Session info with session_id
    """
    session_manager = SessionManager(db)

    try:
        session = session_manager.create_session(
            user_id=UUID(user["user_id"]),
            objective=request.objective,
            llm_id=request.llm_id,
            llm_version=request.llm_version,
            title=request.title,
            metadata=request.metadata
        )

        db.commit()

        return {
            "message": "Session created successfully",
            "session": session
        }

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")


@app.get("/sessions")
async def list_sessions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List user's sessions.

    Requires: Bearer token in Authorization header

    Query parameters:
        - status: Optional filter by status (active, paused, archived)
        - limit: Max results (default 50, max 100)
        - offset: Pagination offset

    Returns:
        List of sessions for the authenticated user
    """
    session_manager = SessionManager(db)

    sessions = session_manager.list_sessions(
        user_id=UUID(user["user_id"]),
        status=status,
        limit=limit,
        offset=offset
    )

    return {
        "count": len(sessions),
        "sessions": sessions
    }


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get session by ID.

    Requires: Bearer token in Authorization header

    Returns:
        Session info
    """
    session_manager = SessionManager(db)

    try:
        session = session_manager.get_session(
            session_id=UUID(session_id),
            user_id=UUID(user["user_id"])
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {"session": session}

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session")


@app.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    request: SessionUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update session status, title and/or metadata.

    Requires: Bearer token in Authorization header

    Body:
        - status: Optional new status (must be valid transition: active↔paused→archived)
        - title: Optional new title
        - metadata: Optional metadata updates (merged with existing)

    Returns:
        Updated session info
    """
    session_manager = SessionManager(db)

    try:
        session = session_manager.update_session(
            session_id=UUID(session_id),
            user_id=UUID(user["user_id"]),
            new_status=request.status,
            title=request.title,
            metadata_updates=request.metadata
        )

        db.commit()

        return {
            "message": "Session updated successfully",
            "session": session
        }

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating session: {e}")
        raise HTTPException(status_code=500, detail="Failed to update session")


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a session (only if in draft state).

    Requires: Bearer token in Authorization header

    Returns:
        Success message
    """
    session_manager = SessionManager(db)

    try:
        result = session_manager.delete_session(
            session_id=UUID(session_id),
            user_id=UUID(user["user_id"])
        )

        db.commit()

        return result

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")


# =============================================================================
# LLM ENDPOINTS (Phase 1)
# =============================================================================

@app.post("/llm/call")
async def call_llm(
    request: LLMCallRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Call LLM API with retry and tracking.

    Requires: Bearer token in Authorization header

    Body:
        - session_id: UUID of the session
        - messages: List of message dicts with 'role' and 'content'
        - model_id: Optional model identifier (default: claude-3-sonnet-20240229)
        - model_config: Optional config (temperature, max_tokens, etc.)
        - timeout_ms: Optional timeout in milliseconds

    Returns:
        LLM response with content, usage, and metadata
    """
    llm_proxy = LLMProxy(db)

    try:
        # Verify session belongs to user
        session_manager = SessionManager(db)
        session = session_manager.get_session(
            session_id=UUID(request.session_id),
            user_id=UUID(user["user_id"])
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Call LLM
        response = llm_proxy.call(
            session_id=UUID(request.session_id),
            messages=request.messages,
            model_id=request.model_id,
            model_config=request.llm_config,
            timeout_ms=request.timeout_ms
        )

        db.commit()

        return {
            "message": "LLM call successful",
            "response": response
        }

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error calling LLM: {e}")
        raise HTTPException(status_code=500, detail="Failed to call LLM")


# =============================================================================
# JOB ENDPOINTS (Phase 1)
# =============================================================================

@app.post("/jobs")
async def create_job(
    request: JobCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new async job.

    Requires: Bearer token in Authorization header

    Body:
        - session_id: UUID of the session
        - job_type: Type of job (e.g., "llm_call", "analysis")
        - input_data: Input data for the job
        - priority: Optional priority (1-10, default 5)

    Returns:
        Job info with job_id
    """
    job_manager = JobManager(db)

    try:
        # Verify session belongs to user
        session_manager = SessionManager(db)
        session = session_manager.get_session(
            session_id=UUID(request.session_id),
            user_id=UUID(user["user_id"])
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Create job
        job = job_manager.create_job(
            session_id=UUID(request.session_id),
            job_type=request.job_type,
            payload=request.payload,
            timeout_seconds=request.timeout_seconds or 300,
            max_retries=request.max_retries or 3
        )

        db.commit()

        return {
            "message": "Job created and enqueued successfully",
            "job": job
        }

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating job: {e}")
        raise HTTPException(status_code=500, detail="Failed to create job")


@app.get("/jobs")
async def list_jobs(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List jobs with optional filters.

    Requires: Bearer token in Authorization header

    Query parameters:
        - session_id: Optional filter by session
        - status: Optional filter by status (pending, running, completed, failed)
        - job_type: Optional filter by job type
        - limit: Max results (default 50, max 100)
        - offset: Pagination offset

    Returns:
        List of jobs
    """
    job_manager = JobManager(db)

    # If session_id provided, verify it belongs to user
    if session_id:
        session_manager = SessionManager(db)
        session = session_manager.get_session(
            session_id=UUID(session_id),
            user_id=UUID(user["user_id"])
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    jobs = job_manager.list_jobs(
        session_id=UUID(session_id) if session_id else None,
        status=status,
        job_type=job_type,
        limit=limit,
        offset=offset
    )

    return {
        "count": len(jobs),
        "jobs": jobs
    }


@app.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get job by ID.

    Requires: Bearer token in Authorization header

    Returns:
        Job info
    """
    job_manager = JobManager(db)

    job = job_manager.get_job(UUID(job_id))

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Verify session belongs to user
    session_manager = SessionManager(db)
    session = session_manager.get_session(
        session_id=UUID(job["session_id"]),
        user_id=UUID(user["user_id"])
    )

    if not session:
        raise HTTPException(status_code=403, detail="Access denied")

    return {"job": job}


@app.patch("/jobs/{job_id}")
async def update_job_status(
    job_id: str,
    request: JobStatusUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update job status (internal use or worker).

    Requires: Bearer token in Authorization header

    Body:
        - status: New status (running, completed, failed)
        - result_data: Optional result data (for completed)
        - error_message: Optional error message (for failed)

    Returns:
        Updated job info
    """
    job_manager = JobManager(db)

    try:
        # Get job first to verify permissions
        job = job_manager.get_job(UUID(job_id))

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Verify session belongs to user
        session_manager = SessionManager(db)
        session = session_manager.get_session(
            session_id=UUID(job["session_id"]),
            user_id=UUID(user["user_id"])
        )

        if not session:
            raise HTTPException(status_code=403, detail="Access denied")

        # Update job
        updated_job = job_manager.update_job_status(
            job_id=UUID(job_id),
            new_status=request.status,
            result=request.result
        )

        db.commit()

        return {
            "message": "Job status updated successfully",
            "job": updated_job
        }

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating job: {e}")
        raise HTTPException(status_code=500, detail="Failed to update job")


# =============================================================================
# CATALOG ENDPOINTS (Phase 1)
# =============================================================================

@app.get("/catalog/agents")
async def list_catalog_agents(
    status: Optional[str] = None,
    limit: int = 50,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List agents in catalog.

    Requires: Bearer token in Authorization header

    Query parameters:
        - status: Optional filter by status (active, deprecated)
        - limit: Max results (default 50)

    Returns:
        List of agents
    """
    catalog_manager = CatalogManager(db)

    agents = catalog_manager.list_agents(
        status=status,
        limit=limit
    )

    return {
        "count": len(agents),
        "agents": agents
    }


@app.get("/catalog/job-types")
async def list_catalog_job_types(
    status: Optional[str] = None,
    limit: int = 50,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List job types in catalog.

    Requires: Bearer token in Authorization header

    Query parameters:
        - status: Optional filter by status (active, deprecated)
        - limit: Max results (default 50)

    Returns:
        List of job types
    """
    catalog_manager = CatalogManager(db)

    job_types = catalog_manager.list_job_types(
        status=status,
        limit=limit
    )

    return {
        "count": len(job_types),
        "job_types": job_types
    }


# =============================================================================
# SUBSESSION ENDPOINTS (Phase 2)
# =============================================================================

@app.get("/sessions/{session_id}/subsessions")
async def list_subsessions(
    session_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List subsessions for a session."""
    # Verify session ownership
    session_manager = SessionManager(db)
    session = session_manager.get_session(
        session_id=UUID(session_id),
        user_id=UUID(user["user_id"])
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    subsession_manager = SubSessionManager(db)
    subsessions = subsession_manager.list_subsessions(
        parent_session_id=UUID(session_id),
        status=status,
        limit=limit
    )

    return {"count": len(subsessions), "subsessions": subsessions}


# =============================================================================
# FUTURE ENDPOINTS (Phase 3+)
# =============================================================================

# TODO: Add /agents endpoints (catalog management)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
