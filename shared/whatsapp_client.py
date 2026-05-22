import logging
from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)


@with_retry(max_attempts=3)
def send_whatsapp(message: str) -> str:
    """Send a WhatsApp message to Zach via Twilio. Returns the message SID."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] WhatsApp to %s:\n%s", config.ZACH_WHATSAPP_NUMBER, message)
        return "dry-run-sid"

    from twilio.rest import Client  # noqa: PLC0415

    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    msg = client.messages.create(
        from_=f"whatsapp:{config.TWILIO_WHATSAPP_FROM}",
        to=f"whatsapp:{config.ZACH_WHATSAPP_NUMBER}",
        body=message,
    )
    logger.info("WhatsApp sent, SID=%s", msg.sid)
    return msg.sid
