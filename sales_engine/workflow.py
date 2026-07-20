from __future__ import annotations

from datetime import datetime
from typing import Iterable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from email_service import EmailService
from gemini_service import GeminiService
from models import ActivityLog, Lead, LeadStatus
from scraper import WebsiteScraper
from utils import normalize_url


def log_activity(session: Session, event: str, detail: str | None = None, lead_id: int | None = None) -> None:
    session.add(ActivityLog(lead_id=lead_id, event=event, detail=detail))


def create_lead(session: Session, company_name: str, website_url: str, contact_email: str | None = None) -> tuple[Lead, bool]:
    name = company_name.strip()
    if not name:
        raise ValueError("Company name is required")
    url = normalize_url(website_url)
    existing = session.scalar(select(Lead).where(func.lower(Lead.website_url) == url.lower()))
    if existing:
        return existing, False
    lead = Lead(company_name=name, website_url=url, contact_email=(contact_email or None))
    session.add(lead)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Lead).where(func.lower(Lead.website_url) == url.lower()))
        if existing:
            return existing, False
        raise
    log_activity(session, "Lead discovered", f"Created {lead.company_name}", lead.id)
    return lead, True


def bulk_create_leads(session: Session, rows: Iterable[dict[str, str]]) -> dict[str, int]:
    created = duplicates = failed = 0
    for row in rows:
        try:
            lead, was_created = create_lead(session, row.get("company_name", ""), row.get("website_url", ""), row.get("contact_email") or None)
            created += int(was_created)
            duplicates += int(not was_created)
        except Exception as exc:
            failed += 1
            logger.error("Failed to import row {}: {}", row, exc)
    return {"created": created, "duplicates": duplicates, "failed": failed}


def scrape_lead(session: Session, lead: Lead) -> Lead:
    scraped = WebsiteScraper().scrape(lead.website_url)
    lead.title = scraped.title
    lead.meta_description = scraped.meta_description
    lead.visible_text = scraped.visible_text
    lead.industry = scraped.industry
    lead.status = LeadStatus.SCRAPED
    lead.failure_reason = None
    log_activity(session, "Website scraped", f"Industry inferred: {lead.industry}", lead.id)
    return lead


def enrich_lead(session: Session, lead: Lead) -> Lead:
    if lead.status == LeadStatus.DISCOVERED:
        scrape_lead(session, lead)
    result = GeminiService().generate(lead)
    lead.company_summary = result.company_summary
    lead.pain_points = "\n".join(result.pain_points)
    lead.status = LeadStatus.ENRICHED
    log_activity(session, "Lead enriched", "Company summary and pain points generated", lead.id)
    lead.generated_email = result.personalized_email
    lead.status = LeadStatus.EMAIL_GENERATED
    log_activity(session, "Email generated", "Personalized sales email generated", lead.id)
    lead.status = LeadStatus.WAITING_APPROVAL
    lead.failure_reason = None
    log_activity(session, "Approval requested", "Lead is waiting for human approval", lead.id)
    return lead


def approve_lead(session: Session, lead: Lead, email_body: str) -> Lead:
    lead.approved_email = email_body.strip()
    lead.status = LeadStatus.APPROVED
    log_activity(session, "Email approved", "Human approved outreach", lead.id)
    return lead


def reject_lead(session: Session, lead: Lead, reason: str) -> Lead:
    lead.status = LeadStatus.FAILED
    lead.failure_reason = reason or "Rejected by reviewer"
    log_activity(session, "Email rejected", lead.failure_reason, lead.id)
    return lead


def send_approved_email(session: Session, lead: Lead) -> Lead:
    try:
        EmailService().send_lead_email(lead)
        lead.status = LeadStatus.SENT
        lead.sent_at = datetime.utcnow()
        lead.failure_reason = None
        log_activity(session, "Email sent", f"Sent to {lead.contact_email}", lead.id)
    except Exception as exc:
        lead.status = LeadStatus.FAILED
        lead.failure_reason = str(exc)
        log_activity(session, "Email failed", str(exc), lead.id)
        raise
    return lead
