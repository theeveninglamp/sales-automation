from __future__ import annotations

import argparse
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_SSL_PORT = 465
DEFAULT_SENDER_NAME = "Sales Team"
DEFAULT_TIMEOUT_SECONDS = 30


class LeadLike(Protocol):
    id: int | None
    company_name: str
    contact_email: str | None
    status: object
    approved_email: str | None


@dataclass(frozen=True)
class EmailSettings:
    gmail_username: str | None
    gmail_app_password: str | None
    sender_name: str
    smtp_host: str = GMAIL_SMTP_HOST
    smtp_port: int = GMAIL_SMTP_SSL_PORT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> EmailSettings:
        return cls(
            gmail_username=os.getenv("GMAIL_USERNAME") or None,
            gmail_app_password=os.getenv("GMAIL_APP_PASSWORD") or None,
            sender_name=os.getenv("SENDER_NAME", DEFAULT_SENDER_NAME),
            smtp_host=os.getenv("GMAIL_SMTP_HOST", GMAIL_SMTP_HOST),
            smtp_port=int(os.getenv("GMAIL_SMTP_PORT", str(GMAIL_SMTP_SSL_PORT))),
            timeout_seconds=int(os.getenv("EMAIL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
        )


@dataclass(frozen=True)
class SendResult:
    recipient: str
    subject: str
    message_id: str


def _status_value(status: object) -> str:
    return getattr(status, "value", str(status))


def _validate_email_address(address: str | None, field_name: str) -> str:
    value = (address or "").strip()
    if not value or "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError(f"{field_name} must be a valid email address")
    return value


class EmailService:
    def __init__(self, settings: EmailSettings | None = None) -> None:
        self.settings = settings or EmailSettings.from_environment()

    def build_message(self, to_email: str, company_name: str, body: str, subject: str | None = None) -> EmailMessage:
        sender = _validate_email_address(self.settings.gmail_username, "GMAIL_USERNAME")
        recipient = _validate_email_address(to_email, "Recipient email")
        clean_body = body.strip()
        if not clean_body:
            raise ValueError("Email body cannot be empty")

        msg = EmailMessage()
        msg["Subject"] = subject or f"Idea for {company_name}"
        msg["From"] = formataddr((self.settings.sender_name, sender))
        msg["To"] = recipient
        msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
        msg.set_content(clean_body)
        return msg

    def send_message(self, message: EmailMessage) -> SendResult:
        if not self.settings.gmail_app_password:
            raise ValueError("GMAIL_APP_PASSWORD is not configured")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=self.settings.timeout_seconds,
            context=context,
        ) as smtp:
            smtp.login(_validate_email_address(self.settings.gmail_username, "GMAIL_USERNAME"), self.settings.gmail_app_password)
            refused = smtp.send_message(message)
        if refused:
            raise RuntimeError(f"SMTP refused recipients: {refused}")
        return SendResult(
            recipient=str(message["To"]),
            subject=str(message["Subject"]),
            message_id=str(message["Message-ID"]),
        )

    def send_email(self, to_email: str, company_name: str, body: str, subject: str | None = None) -> SendResult:
        return self.send_message(self.build_message(to_email, company_name, body, subject))

    def send_lead_email(self, lead: LeadLike) -> SendResult:
        if _status_value(lead.status) != "APPROVED" or not lead.approved_email:
            raise ValueError("Only approved leads with approved email content can be sent")
        return self.send_email(
            to_email=lead.contact_email,
            company_name=lead.company_name,
            body=lead.approved_email,
            subject=f"Idea for {lead.company_name}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a Gmail SMTP test email using .env/environment credentials.")
    parser.add_argument("--to", default=os.getenv("TEST_EMAIL"), help="Recipient test email address; defaults to TEST_EMAIL")
    parser.add_argument("--company", default="Test Company", help="Company name for the subject line")
    parser.add_argument("--subject", default="AI Sales Automation Engine SMTP Test", help="Email subject")
    parser.add_argument(
        "--body",
        default="This is a delivery test from the AI Sales Automation Engine Gmail SMTP integration.",
        help="Plain-text email body",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build and validate the message without sending")
    args = parser.parse_args()

    settings = EmailSettings.from_environment()
    if args.dry_run and not settings.gmail_username:
        settings = EmailSettings(
            gmail_username="dry-run@example.com",
            gmail_app_password=settings.gmail_app_password,
            sender_name=settings.sender_name,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            timeout_seconds=settings.timeout_seconds,
        )
    service = EmailService(settings)
    try:
        message = service.build_message(args.to, args.company, args.body, args.subject)
        if args.dry_run:
            print(message.as_string())
            return
        result = service.send_message(message)
    except (ValueError, OSError, smtplib.SMTPException, RuntimeError) as exc:
        raise SystemExit(f"Email delivery failed: {exc}") from exc
    print(f"Sent {result.message_id} to {result.recipient} with subject {result.subject!r}")


if __name__ == "__main__":
    main()
