"""
User Sync Manager Agent - OIDC authentication and user synchronization.

This agent syncs users from OIDC provider (Keycloak) to app_user table.

Based on: SYSTEM_FOUNDATION.md Section 11 (Agent 1: User Sync Manager)
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from uuid import uuid4
import logging

from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
import requests
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models import AppUser
from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class UserSyncManager:
    """
    User Sync Manager Agent - OIDC integration.

    Responsibilities:
    - Verify JWT bearer tokens from OIDC provider
    - Fetch and cache JWKS (JSON Web Key Set)
    - Extract user claims from JWT
    - Create or update app_user records
    - Generate audit events for authentication

    Critical Rules:
    1. JWKS cached for 1 hour (reduce provider load)
    2. JWT signature must be valid
    3. User sync is idempotent (same token → same user)
    4. All auth events logged via Audit Logger
    """

    # JWKS cache (class-level for sharing across instances)
    _jwks_cache: Dict[str, Any] = {}
    _jwks_cache_time: Dict[str, datetime] = {}
    JWKS_CACHE_TTL = timedelta(hours=1)

    def __init__(self, db: Session, audit_logger: Optional[AuditLogger] = None):
        """
        Initialize User Sync Manager.

        Args:
            db: SQLAlchemy database session
            audit_logger: Optional AuditLogger instance (will create if not provided)
        """
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

    def verify_token(
        self,
        bearer_token: str,
        oidc_config: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Verify JWT token and sync user.

        Args:
            bearer_token: JWT token from Authorization header (without 'Bearer' prefix)
            oidc_config: OIDC configuration dict with:
                - issuer: OIDC issuer URL
                - audience: Expected audience (client_id)
                - jwks_url: URL to fetch JWKS

        Returns:
            Dict with user info:
                - user_id: UUID from database
                - external_id: sub claim from JWT
                - provider: issuer from JWT
                - email: email from JWT
                - display_name: name from JWT
                - is_active: boolean
                - synced: True if user was synced

        Raises:
            ValueError: If token is invalid or config is missing
            JWTError: If JWT verification fails
        """
        # Validate config
        if not oidc_config.get("issuer"):
            raise ValueError("oidc_config.issuer is required")
        if not oidc_config.get("jwks_url"):
            raise ValueError("oidc_config.jwks_url is required")

        issuer = oidc_config["issuer"]
        jwks_url = oidc_config["jwks_url"]
        audience = oidc_config.get("audience")

        try:
            # Fetch JWKS (with caching)
            jwks = self._get_jwks(jwks_url)

            # Decode token header to get kid (key ID)
            unverified_header = jwt.get_unverified_header(bearer_token)
            kid = unverified_header.get("kid")

            # Find matching key in JWKS
            signing_key = None
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    signing_key = key
                    break

            if not signing_key:
                self._log_auth_event("auth.token_invalid", "system", "system", None, "failure", "Key ID not found in JWKS")
                raise ValueError(f"Key ID '{kid}' not found in JWKS")

            # Verify JWT signature and decode
            try:
                payload = jwt.decode(
                    bearer_token,
                    signing_key,
                    algorithms=["RS256"],
                    issuer=issuer,
                    audience=audience if audience else None,
                    options={"verify_aud": bool(audience)}
                )
            except ExpiredSignatureError:
                self._log_auth_event("auth.token_expired", "system", "system", None, "failure", "Token expired")
                raise ValueError("Token has expired")
            except JWTError as e:
                self._log_auth_event("auth.token_invalid", "system", "system", None, "failure", str(e))
                raise ValueError(f"Invalid token: {e}")

            # Extract claims
            external_id = payload.get("sub")
            email = payload.get("email")
            name = payload.get("name") or payload.get("preferred_username")

            if not external_id:
                raise ValueError("Token missing 'sub' claim")

            # Sync user to database
            user = self._sync_user(
                external_id=external_id,
                provider=issuer,
                email=email,
                display_name=name
            )

            # Log successful auth
            self._log_auth_event(
                "auth.user_authenticated",
                "user",
                str(user.id),
                user.id,
                "success",
                None
            )

            return {
                "user_id": str(user.id),
                "external_id": user.external_id,
                "provider": user.provider,
                "email": user.email,
                "display_name": user.display_name,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat(),
                "synced": True
            }

        except Exception as e:
            logger.error(f"[UserSyncManager] Token verification failed: {e}")
            raise

    def _get_jwks(self, jwks_url: str) -> Dict[str, Any]:
        """
        Get JWKS from OIDC provider (with 1-hour cache).

        Args:
            jwks_url: URL to fetch JWKS from

        Returns:
            JWKS dict with 'keys' array
        """
        # Check cache
        if jwks_url in self._jwks_cache:
            cache_time = self._jwks_cache_time.get(jwks_url)
            if cache_time and datetime.utcnow() - cache_time < self.JWKS_CACHE_TTL:
                logger.debug(f"[UserSyncManager] Using cached JWKS for {jwks_url}")
                return self._jwks_cache[jwks_url]

        # Fetch fresh JWKS
        logger.info(f"[UserSyncManager] Fetching JWKS from {jwks_url}")
        try:
            response = requests.get(jwks_url, timeout=10)
            response.raise_for_status()
            jwks = response.json()

            # Cache it
            self._jwks_cache[jwks_url] = jwks
            self._jwks_cache_time[jwks_url] = datetime.utcnow()

            return jwks

        except requests.RequestException as e:
            logger.error(f"[UserSyncManager] Failed to fetch JWKS: {e}")
            raise ValueError(f"Failed to fetch JWKS: {e}")

    def _sync_user(
        self,
        external_id: str,
        provider: str,
        email: Optional[str],
        display_name: Optional[str]
    ) -> AppUser:
        """
        Create or update user in database.

        Args:
            external_id: OIDC sub claim
            provider: OIDC issuer
            email: User email
            display_name: User display name

        Returns:
            AppUser instance
        """
        # Try to find existing user
        user = self.db.query(AppUser).filter_by(
            provider=provider,
            external_id=external_id
        ).first()

        if user:
            # Update existing user
            updated = False
            if email and user.email != email:
                user.email = email
                updated = True
            if display_name and user.display_name != display_name:
                user.display_name = display_name
                updated = True

            if updated:
                user.updated_at = datetime.utcnow()
                self.db.flush()
                logger.info(f"[UserSyncManager] Updated user: {user.email}")
                self._log_auth_event("auth.user_updated", "system", "system", user.id, "success", None)

            else:
                logger.info(f"[UserSyncManager] User already synced: {user.email}")
                self._log_auth_event("auth.user_synced", "system", "system", user.id, "success", None)

        else:
            # Create new user
            user = AppUser(
                id=uuid4(),
                external_id=external_id,
                provider=provider,
                email=email or f"{external_id}@unknown",
                display_name=display_name,
                is_active=True
            )
            self.db.add(user)
            self.db.flush()

            logger.info(f"[UserSyncManager] Created new user: {user.email}")
            self._log_auth_event("auth.user_created", "system", "system", user.id, "success", None)

        return user

    def _log_auth_event(
        self,
        event_type: str,
        actor_type: str,
        actor_id: str,
        user_id: Optional[uuid4],
        result_status: str,
        error: Optional[str]
    ):
        """
        Log authentication event via Audit Logger.

        Args:
            event_type: Event type (auth.*)
            actor_type: Actor type
            actor_id: Actor ID
            user_id: User UUID if available
            result_status: success or failure
            error: Error message if failure
        """
        try:
            self.audit_logger.log(
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                action_verb=event_type.split(".")[-1],  # e.g., "authenticated"
                entity_type="user",
                entity_id=str(user_id) if user_id else "unknown",
                context={
                    "session_id": "auth",
                    "request_id": f"auth-{datetime.utcnow().isoformat()}"
                },
                result_status=result_status,
                result_error=error
            )
        except Exception as e:
            logger.error(f"[UserSyncManager] Failed to log auth event: {e}")

    @classmethod
    def clear_jwks_cache(cls):
        """Clear JWKS cache (for testing)."""
        cls._jwks_cache.clear()
        cls._jwks_cache_time.clear()
