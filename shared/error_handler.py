import logging
import functools
import time
from typing import Callable, TypeVar, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(max_attempts: int = 3, min_wait: float = 2.0, max_wait: float = 16.0) -> Callable[[F], F]:
    """Decorator: retry on any exception with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def notify_failure(stage_name: str, error: Exception) -> None:
    """Send a WhatsApp alert to Zach when a stage fails. Imported lazily to avoid circular deps."""
    try:
        from shared.whatsapp_client import send_whatsapp  # noqa: PLC0415

        message = (
            f"⚠️ Pipeline failure in *{stage_name}*\n\n"
            f"Error: {type(error).__name__}: {str(error)[:300]}\n\n"
            f"Check server logs for full details."
        )
        send_whatsapp(message)
    except Exception as notify_err:
        logger.error("Failed to send failure notification: %s", notify_err)


def stage_handler(stage_name: str) -> Callable[[F], F]:
    """Decorator: catch unhandled exceptions, log them, and notify Zach via WhatsApp."""
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                logger.exception("Unhandled error in stage %s", stage_name)
                notify_failure(stage_name, exc)
                raise
        return wrapper  # type: ignore[return-value]
    return decorator
