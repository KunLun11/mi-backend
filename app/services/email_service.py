"""Отправка писем через SMTP (Mailhog в dev) с шаблонами Jinja2."""

import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_template_dir = Path(__file__).resolve().parent.parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class EmailDeliveryError(RuntimeError):
    """Письмо не удалось отправить."""


def render_verification_email(code: str) -> tuple[str, str]:
    """Отрендерить текстовую и HTML-версии письма с кодом."""
    context = {"code": code, "ttl_minutes": settings.email_code_ttl_minutes}
    text = _environment.get_template("email/verification_code.txt").render(**context)
    html = _environment.get_template("email/verification_code.html").render(**context)
    return text, html


async def send_verification_code(email: str, code: str) -> None:
    """Отправить код подтверждения на email."""
    text, html = render_verification_email(code)

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = "Подтверждение email — Mind IT"
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
            timeout=10,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        logger.exception("Failed to send verification email to %s", email)
        raise EmailDeliveryError("email_send_failed") from exc

    logger.info("Verification email sent to %s", email)
