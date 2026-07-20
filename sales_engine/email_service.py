from __future__ import annotations

import smtplib
from email.message import EmailMessage

from loguru import logger

from models import Lead, LeadStatus
from utils import get_settings


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send_lead_email(self, lead: Lead) -> None:
        if lead.status != LeadStatus.APPROVED or not lead.approved_email:
            raise ValueError("Only approved leads with approved email content can be sent")
        if not lead.contact_email:
            raise ValueError("Lead has no contact email")
        if not self.settings.gmail_username or not self.settings.gmail_app_password:
            raise ValueError("Gmail credentials are not configured")

        msg = EmailMessage()
        msg["Subject"] = f"Idea for {lead.company_name}"
        msg["From"] = f"{self.settings.sender_name} <{self.settings.gmail_username}>"
        msg["To"] = lead.contact_email
        msg.set_content(lead.approved_email)

        logger.info("Sending email for lead {} to {}", lead.id, lead.contact_email)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(self.settings.gmail_username, self.settings.gmail_app_password)
            smtp.send_message(msg)
