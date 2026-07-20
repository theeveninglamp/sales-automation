from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from models import ActivityLog, Lead, LeadStatus
from utils import get_settings


def render_metric_cards(session: Session) -> None:
    counts = dict(session.execute(select(Lead.status, func.count(Lead.id)).group_by(Lead.status)).all())
    cols = st.columns(4)
    metrics = [
        ("Pending", counts.get(LeadStatus.WAITING_APPROVAL, 0)),
        ("Approved", counts.get(LeadStatus.APPROVED, 0)),
        ("Sent", counts.get(LeadStatus.SENT, 0)),
        ("Failed", counts.get(LeadStatus.FAILED, 0)),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)


def render_status_chart(session: Session) -> None:
    rows = session.execute(select(Lead.status, func.count(Lead.id)).group_by(Lead.status)).all()
    if not rows:
        st.info("No leads yet. Add companies to begin the pipeline.")
        return
    df = pd.DataFrame([{"Status": status.value, "Leads": count} for status, count in rows])
    st.plotly_chart(px.bar(df, x="Status", y="Leads", title="Lead Pipeline Status", text_auto=True), use_container_width=True)


def render_recent_activity(session: Session) -> None:
    logs = session.scalars(select(ActivityLog).order_by(desc(ActivityLog.created_at)).limit(25)).all()
    if not logs:
        st.caption("No activity has been recorded yet.")
        return
    st.dataframe(
        pd.DataFrame([
            {"Time": log.created_at, "Lead ID": log.lead_id, "Event": log.event, "Detail": log.detail or ""} for log in logs
        ]),
        use_container_width=True,
        hide_index=True,
    )


def render_leads_table(session: Session) -> None:
    leads = session.scalars(select(Lead).order_by(desc(Lead.updated_at))).all()
    if not leads:
        return
    st.dataframe(
        pd.DataFrame([
            {
                "ID": lead.id,
                "Company": lead.company_name,
                "Website": lead.website_url,
                "Contact": lead.contact_email or "",
                "Industry": lead.industry or "",
                "Status": lead.status.value,
                "Updated": lead.updated_at,
            }
            for lead in leads
        ]),
        use_container_width=True,
        hide_index=True,
    )


def render_file_logs() -> None:
    log_path = get_settings().log_path
    try:
        with open(log_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-100:]
    except FileNotFoundError:
        st.caption("No application log file has been created yet.")
        return
    st.code("".join(lines) or "No log entries yet.", language="text")
