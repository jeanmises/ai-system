"""
Authentication dependencies for FastAPI.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import os

from database import get_db
from agents.user_sync_manager import UserSyncManager
from agents.audit_logger import AuditLogger

# Security scheme
security = HTTPBearer()

# OIDC Configuration
OIDC_CONFIG = {
    "issuer": os.getenv("OIDC_ISSUER", "http://localhost:8080/realms/ai-system"),
    "audience": os.getenv("OIDC_AUDIENCE", "ai-system-api"),
    "jwks_url": os.getenv(
        "OIDC_JWKS_URL",
        "http://localhost:8080/realms/ai-system/protocol/openid-connect/certs"
    )
}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    FastAPI dependency to get current authenticated user.

    Validates JWT token and syncs user from OIDC provider.

    Usage in endpoint:
        @app.get("/protected")
        async def protected_endpoint(user=Depends(get_current_user)):
            # user is dict with user_id, email, etc.
            pass

    Raises:
        HTTPException 401: If token is invalid or expired
        HTTPException 403: If user is disabled

    Returns:
        Dict with user info (user_id, email, display_name, etc.)
    """
    token = credentials.credentials

    # Initialize managers
    audit_logger = AuditLogger(db)
    user_sync_manager = UserSyncManager(db, audit_logger)

    try:
        # Verify token and sync user
        user = user_sync_manager.verify_token(token, OIDC_CONFIG)

        # Commit user sync
        db.commit()

        # Check if user is active
        if not user.get("is_active"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled"
            )

        return user

    except ValueError as e:
        # Invalid token
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        # Unexpected error
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )
