from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import desc, select

from sales_engine.dashboard import render_file_logs, render_leads_table, render_metric_cards, render_recent_activity, render_status_chart
from sales_engine.database import get_session, init_db
from sales_engine.models import Lead, LeadStatus
from sales_engine.workflow import approve_lead, bulk_create_leads, create_lead, enrich_lead, reject_lead, scrape_lead, send_approved_email

st.set_page_config(page_title="AI Sales Automation Engine", page_icon="🤖", layout="wide")

CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.5rem;}
[data-testid="stMetric"] {background: #ffffff; border: 1px solid #e7ecf3; border-radius: 16px; padding: 18px; box-shadow: 0 8px 24px rgba(16,24,40,.06);}
.stButton > button {border-radius: 10px; font-weight: 600;}
section[data-testid="stSidebar"] {background: linear-gradient(180deg,#0f172a,#1e293b);}
section[data-testid="stSidebar"] * {color: white;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
init_db()


def page_upload() -> None:
    st.title("Company Input")
    left, right = st.columns(2)
    with left:
        st.subheader("Manual Input")
        with st.form("manual_lead"):
            company = st.text_input("Company name")
            website = st.text_input("Website URL")
            email = st.text_input("Contact email (required before dispatch)")
            submitted = st.form_submit_button("Add Lead")
        if submitted:
            try:
                with get_session() as session:
                    lead, created = create_lead(session, company, website, email or None)
                    st.success(f"{'Created' if created else 'Already exists'} lead #{lead.id}: {lead.company_name}")
            except ValueError as exc:
                st.error(str(exc))
    with right:
        st.subheader("CSV Upload")
        st.caption("Required columns: company_name, website_url. Optional: contact_email.")
        file = st.file_uploader("Upload CSV", type=["csv"])
        if file is not None:
            df = pd.read_csv(file).fillna("")
            required = {"company_name", "website_url"}
            if not required.issubset(df.columns):
                st.error("CSV must include company_name and website_url columns.")
            elif st.button("Import CSV"):
                with get_session() as session:
                    result = bulk_create_leads(session, df.to_dict(orient="records"))
                    st.success(f"Imported {result['created']} leads; skipped {result['duplicates']} duplicates; {result['failed']} failed.")
    with get_session() as session:
        st.subheader("All Leads")
        render_leads_table(session)


def page_pipeline() -> None:
    st.title("Website Extraction & AI Personalization")
    with get_session() as session:
        leads = session.scalars(select(Lead).where(Lead.status.in_([LeadStatus.DISCOVERED, LeadStatus.SCRAPED, LeadStatus.FAILED])).order_by(desc(Lead.updated_at))).all()
        if not leads:
            st.info("No leads are ready for processing.")
            return
        lead_id = st.selectbox("Select lead", [lead.id for lead in leads], format_func=lambda lid: next(l.company_name for l in leads if l.id == lid))
        lead = session.get(Lead, lead_id)
        st.write(f"**Website:** {lead.website_url}")
        col1, col2 = st.columns(2)
        if col1.button("Scrape Website"):
            scrape_lead(session, lead)
            st.success("Website scraped and stored.")
            st.rerun()
        if col2.button("Generate / Regenerate AI Email"):
            enrich_lead(session, lead)
            st.success("Personalization generated and queued for approval.")
            st.rerun()
        if lead.visible_text:
            st.subheader("Extracted Data")
            st.write({"title": lead.title, "meta_description": lead.meta_description, "industry": lead.industry})
            st.text_area("Visible text", lead.visible_text, height=180)


def page_approval() -> None:
    st.title("Human Approval")
    with get_session() as session:
        leads = session.scalars(select(Lead).where(Lead.status == LeadStatus.WAITING_APPROVAL).order_by(Lead.created_at)).all()
        if not leads:
            st.info("No emails are waiting for approval.")
            return
        lead_id = st.selectbox("Review lead", [lead.id for lead in leads], format_func=lambda lid: next(l.company_name for l in leads if l.id == lid))
        lead = session.get(Lead, lead_id)
        st.subheader(lead.company_name)
        st.write(f"**Industry:** {lead.industry}")
        st.write(f"**Summary:** {lead.company_summary}")
        st.write(f"**Pain points:** {lead.pain_points}")
        email_body = st.text_area("Editable email", lead.generated_email or "", height=260)
        c1, c2, c3 = st.columns(3)
        if c1.button("Approve"):
            approve_lead(session, lead, email_body)
            st.success("Approved for sending.")
            st.rerun()
        if c2.button("Reject"):
            reject_lead(session, lead, "Rejected during human review")
            st.warning("Rejected.")
            st.rerun()
        if c3.button("Regenerate"):
            enrich_lead(session, lead)
            st.success("Regenerated.")
            st.rerun()


def page_dispatch() -> None:
    st.title("Email Dispatch")
    with get_session() as session:
        leads = session.scalars(select(Lead).where(Lead.status == LeadStatus.APPROVED).order_by(Lead.created_at)).all()
        if not leads:
            st.info("No approved emails are ready to send.")
            return
        for lead in leads:
            with st.expander(f"{lead.company_name} → {lead.contact_email or 'missing recipient'}", expanded=True):
                st.text(lead.approved_email)
                if st.button("Send Email", key=f"send-{lead.id}"):
                    try:
                        send_approved_email(session, lead)
                        st.success("Email sent.")
                    except Exception as exc:
                        st.error(f"Send failed: {exc}")
                    st.rerun()


def page_dashboard() -> None:
    st.title("Analytics Dashboard")
    with get_session() as session:
        render_metric_cards(session)
        render_status_chart(session)
        st.subheader("Recent Activity")
        render_recent_activity(session)
        st.subheader("Application Logs")
        render_file_logs()
        st.subheader("Lead Table")
        render_leads_table(session)


with st.sidebar:
    st.header("AI Sales Engine")
    page = st.radio("Navigation", ["Dashboard", "Company Upload", "Pipeline", "Human Approval", "Email Dispatch"])

if page == "Company Upload":
    page_upload()
elif page == "Pipeline":
    page_pipeline()
elif page == "Human Approval":
    page_approval()
elif page == "Email Dispatch":
    page_dispatch()
else:
    page_dashboard()
