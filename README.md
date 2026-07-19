# AI Sales Automation Engine

A production-oriented Streamlit application that runs a human-in-the-loop outbound sales pipeline:

Company Input → Website Extraction → SQLite Database → AI Personalization → Human Approval → Gmail Dispatch → Analytics Dashboard.

## Features

- Manual lead entry and CSV upload with duplicate prevention by website URL.
- Homepage scraping with Requests, BeautifulSoup, and Trafilatura.
- Extraction of page title, meta description, visible text, and rule-based industry inference.
- SQLite persistence through SQLAlchemy models.
- Lead lifecycle states: `DISCOVERED`, `SCRAPED`, `ENRICHED`, `EMAIL_GENERATED`, `WAITING_APPROVAL`, `APPROVED`, `SENT`, `FAILED`.
- Google Gemini personalization for company summary, pain points, and sales emails.
- Deterministic fallback personalization when Gemini credentials are not configured, keeping local demos functional.
- Editable human approval workflow with approve, reject, and regenerate actions.
- Gmail SMTP dispatch that only sends approved emails.
- Plotly dashboard with status counts, activity feed, and lead table.
- Loguru file logging and activity logs stored in SQLite.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your Gemini API key and Gmail app password. Gmail requires an app password for SMTP access when two-factor authentication is enabled.

## Run

```bash
streamlit run sales_engine/app.py
```

## CSV Format

CSV uploads must include:

```csv
company_name,website_url,contact_email
Example Inc,https://example.com,buyer@example.com
```

`contact_email` is optional during import but required before email dispatch.

## Workflow

1. Add companies on **Company Upload**.
2. Scrape and generate outreach on **Pipeline**.
3. Review, edit, approve, reject, or regenerate on **Human Approval**.
4. Send approved emails on **Email Dispatch**.
5. Monitor counts, charts, recent activity, and logs on **Dashboard**.

## Safety Notes

- The app never sends generated emails automatically; only `APPROVED` leads can be dispatched.
- Duplicate website URLs are skipped during manual and CSV import.
- Failed sends store the failure reason and mark the lead `FAILED`.
