"""
LLM Proxy Agent - Gateway for LLM API calls with retry, fallback, and tracking.

This agent provides a unified interface for calling LLM APIs with:
- Deterministic exponential backoff (NO jitter for reproducibility)
- Fallback to secondary models
- Token usage tracking
- Model version logging
- Audit events for all calls

Based on: EXECUTION_PLAN.md Phase 1 Step 4
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID
import logging
import time
import os

from sqlalchemy.orm import Session as DBSession
import anthropic

from agents.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class LLMProxy:
    """
    LLM Proxy Agent - Gateway for LLM API calls.

    Responsibilities:
    - Route requests to primary LLM endpoint
    - Implement deterministic retry with exponential backoff (NO JITTER)
    - Fallback to secondary LLM if primary fails
    - Track token usage and costs
    - Log model version for reproducibility
    - Generate audit events for all calls

    Critical Rules:
    1. Retry backoff MUST be deterministic: backoff_ms = min(60000, 1000 * (2 ** attempt))
    2. NO randomization/jitter in backoff (breaks reproducibility)
    3. Model version MUST be logged for every call
    4. All calls MUST generate audit events (start, success/failure)
    5. Timeout MUST be respected (default 30s)
    """

    # Configuration
    DEFAULT_TIMEOUT_MS = 30000  # 30 seconds
    MAX_RETRIES = 3
    MAX_BACKOFF_MS = 60000  # 60 seconds

    def __init__(
        self,
        db: DBSession,
        audit_logger: Optional[AuditLogger] = None,
        api_key: Optional[str] = None
    ):
        """
        Initialize LLM Proxy.

        Args:
            db: SQLAlchemy database session
            audit_logger: Optional AuditLogger instance (will create if not provided)
            api_key: Optional API key (will use ANTHROPIC_API_KEY env var if not provided)
        """
        self.db = db
        self.audit_logger = audit_logger or AuditLogger(db)

        # Initialize Anthropic client
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("[LLMProxy] No API key provided - calls will fail")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)

    def call(
        self,
        session_id: UUID,
        messages: List[Dict[str, str]],
        model_id: Optional[str] = None,
        model_config: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None,
        max_retries: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Call LLM API with retry and fallback.

        Args:
            session_id: UUID of the session making the call
            messages: List of message dicts with 'role' and 'content'
            model_id: Optional model identifier (default: claude-3-sonnet-20240229)
            model_config: Optional config dict with temperature, max_tokens, etc.
            timeout_ms: Optional timeout in milliseconds (default: 30000)
            max_retries: Optional max retry attempts (default: 3)

        Returns:
            Dict with:
                - content: Response text
                - model_id: Model identifier used
                - model_version: Model version used
                - usage: Token usage dict (input_tokens, output_tokens)
                - latency_ms: Call latency in milliseconds
                - attempt: Number of attempts made
                - finish_reason: Why the model stopped

        Raises:
            ValueError: If messages are invalid or API key missing
            RuntimeError: If all retry attempts fail
        """
        # Validate inputs
        if not messages:
            raise ValueError("messages cannot be empty")
        if not self.client:
            raise ValueError("No API key configured - cannot make LLM calls")

        # Set defaults
        model_id = model_id or "claude-3-sonnet-20240229"
        timeout_ms = timeout_ms or self.DEFAULT_TIMEOUT_MS
        max_retries = max_retries if max_retries is not None else self.MAX_RETRIES
        model_config = model_config or {}

        # Extract config parameters
        temperature = model_config.get("temperature", 1.0)
        max_tokens = model_config.get("max_tokens", 4096)

        # Log start
        call_start_time = time.time()
        self._log_llm_event(
            event_type="llm.call_started",
            session_id=session_id,
            model_id=model_id,
            result_status="pending",
            metadata={
                "message_count": len(messages),
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        )

        # Retry loop with deterministic exponential backoff
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # Make API call
                attempt_start = time.time()

                response = self.client.messages.create(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_ms / 1000.0  # Convert to seconds
                )

                attempt_latency = int((time.time() - attempt_start) * 1000)
                total_latency = int((time.time() - call_start_time) * 1000)

                # Extract response data
                result = {
                    "content": response.content[0].text if response.content else "",
                    "model_id": response.model,
                    "model_version": response.model,  # Anthropic returns full version in model field
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                    },
                    "latency_ms": total_latency,
                    "attempt": attempt + 1,
                    "finish_reason": response.stop_reason
                }

                # Log success
                self._log_llm_event(
                    event_type="llm.call_completed",
                    session_id=session_id,
                    model_id=model_id,
                    result_status="success",
                    metadata={
                        "model_version": result["model_version"],
                        "input_tokens": result["usage"]["input_tokens"],
                        "output_tokens": result["usage"]["output_tokens"],
                        "latency_ms": total_latency,
                        "attempts": attempt + 1,
                        "finish_reason": result["finish_reason"]
                    }
                )

                logger.info(
                    f"[LLMProxy] Call succeeded: session={session_id}, "
                    f"model={model_id}, tokens={result['usage']['total_tokens']}, "
                    f"latency={total_latency}ms, attempts={attempt + 1}"
                )

                return result

            except anthropic.RateLimitError as e:
                last_error = e
                logger.warning(f"[LLMProxy] Rate limit hit (attempt {attempt + 1}/{max_retries + 1}): {e}")

            except anthropic.APITimeoutError as e:
                last_error = e
                logger.warning(f"[LLMProxy] Timeout (attempt {attempt + 1}/{max_retries + 1}): {e}")

            except anthropic.APIConnectionError as e:
                last_error = e
                logger.warning(f"[LLMProxy] Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}")

            except anthropic.APIError as e:
                # Don't retry on client errors (4xx except 429)
                if hasattr(e, 'status_code') and 400 <= e.status_code < 500 and e.status_code != 429:
                    last_error = e
                    logger.error(f"[LLMProxy] Client error (no retry): {e}")
                    break
                last_error = e
                logger.warning(f"[LLMProxy] API error (attempt {attempt + 1}/{max_retries + 1}): {e}")

            except Exception as e:
                last_error = e
                logger.error(f"[LLMProxy] Unexpected error (attempt {attempt + 1}/{max_retries + 1}): {e}")
                break

            # Deterministic exponential backoff (NO JITTER)
            if attempt < max_retries:
                backoff_ms = min(self.MAX_BACKOFF_MS, 1000 * (2 ** attempt))
                logger.info(f"[LLMProxy] Waiting {backoff_ms}ms before retry...")
                time.sleep(backoff_ms / 1000.0)

        # All retries failed
        total_latency = int((time.time() - call_start_time) * 1000)

        self._log_llm_event(
            event_type="llm.call_failed",
            session_id=session_id,
            model_id=model_id,
            result_status="failure",
            error=str(last_error),
            metadata={
                "attempts": max_retries + 1,
                "latency_ms": total_latency
            }
        )

        raise RuntimeError(
            f"LLM call failed after {max_retries + 1} attempts: {last_error}"
        )

    def _log_llm_event(
        self,
        event_type: str,
        session_id: UUID,
        model_id: str,
        result_status: str,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log LLM event via Audit Logger.

        Args:
            event_type: Event type (llm.*)
            session_id: Session UUID
            model_id: Model identifier
            result_status: success, failure, or pending
            error: Error message if failure
            metadata: Additional metadata
        """
        try:
            self.audit_logger.log(
                event_type=event_type,
                actor_type="agent",
                actor_id="llm_proxy",
                action_verb=event_type.split(".")[-1],  # e.g., "call_completed"
                entity_type="llm_call",
                entity_id=str(session_id),
                context={
                    "session_id": str(session_id),
                    "model_id": model_id,
                    "timestamp": datetime.utcnow().isoformat()
                },
                result_status=result_status,
                result_error=error,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"[LLMProxy] Failed to log event: {e}")
