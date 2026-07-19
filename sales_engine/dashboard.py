from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

PIPELINE_STATUSES = [
    "DISCOVERED",
    "SCRAPED",
    "ENRICHED",
    "EMAIL_GENERATED",
    "WAITING_APPROVAL",
    "APPROVED",
    "SENT",
    "FAILED",
]
PRIMARY_METRICS = ["WAITING_APPROVAL", "APPROVED", "SENT", "FAILED"]
STATUS_LABELS = {
    "WAITING_APPROVAL": "Pending",
    "APPROVED": "Approved",
    "SENT": "Sent",
    "FAILED": "Failed",
}


@dataclass(frozen=True)
class LeadRow:
    id: int
    company: str
    website: str
    contact: str
    industry: str
    status: str
    updated: str


@dataclass(frozen=True)
class ActivityRow:
    time: str
    lead_id: int | None
    event: str
    detail: str


@dataclass(frozen=True)
class DashboardData:
    counts: dict[str, int]
    leads: list[LeadRow]
    activity: list[ActivityRow]
    logs: str


def _load_optional_module(module_name: str) -> Any | None:
    root = module_name.split(".", 1)[0]
    if importlib.util.find_spec(root) is None:
        return None
    if importlib.util.find_spec(module_name) is None:
        return None
    return importlib.import_module(module_name)


st = _load_optional_module("streamlit")
pd = _load_optional_module("pandas")
px = _load_optional_module("plotly.express")


def _require_streamlit() -> Any:
    if st is None:
        raise RuntimeError("Streamlit is not installed. Install requirements and run: streamlit run sales_engine/app.py")
    return st


def _status_value(status: Any) -> str:
    return getattr(status, "value", str(status))


def _format_time(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def _records(rows: Iterable[dict[str, Any]]) -> Any:
    rows = list(rows)
    if pd is not None:
        return pd.DataFrame(rows)
    return rows


def _read_logs(log_path: str | None = None, max_lines: int = 100) -> str:
    path = log_path or os.getenv("LOG_PATH", "logs/sales_engine.log")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return "".join(handle.readlines()[-max_lines:])
    except FileNotFoundError:
        return ""


def load_dashboard_data(session: Any, log_path: str | None = None) -> DashboardData:
    from sales_engine.models import ActivityLog, Lead
    from sqlalchemy import desc, func, select

    counts = {status: 0 for status in PIPELINE_STATUSES}
    for status, count in session.execute(select(Lead.status, func.count(Lead.id)).group_by(Lead.status)).all():
        counts[_status_value(status)] = int(count)

    leads = [
        LeadRow(
            id=lead.id,
            company=lead.company_name,
            website=lead.website_url,
            contact=lead.contact_email or "",
            industry=lead.industry or "",
            status=_status_value(lead.status),
            updated=_format_time(lead.updated_at),
        )
        for lead in session.scalars(select(Lead).order_by(desc(Lead.updated_at))).all()
    ]

    activity = [
        ActivityRow(
            time=_format_time(log.created_at),
            lead_id=log.lead_id,
            event=log.event,
            detail=log.detail or "",
        )
        for log in session.scalars(select(ActivityLog).order_by(desc(ActivityLog.created_at)).limit(25)).all()
    ]
    return DashboardData(counts=counts, leads=leads, activity=activity, logs=_read_logs(log_path))


def render_metric_cards(data: DashboardData | Any) -> None:
    ui = _require_streamlit()
    dashboard_data = data if isinstance(data, DashboardData) else load_dashboard_data(data)
    cols = ui.columns(4)
    for col, status in zip(cols, PRIMARY_METRICS):
        col.metric(STATUS_LABELS[status], dashboard_data.counts.get(status, 0))


def render_status_chart(data: DashboardData | Any) -> None:
    ui = _require_streamlit()
    dashboard_data = data if isinstance(data, DashboardData) else load_dashboard_data(data)
    rows = [{"Status": status, "Leads": dashboard_data.counts.get(status, 0)} for status in PIPELINE_STATUSES]
    if sum(row["Leads"] for row in rows) == 0:
        ui.info("No leads yet. Add companies to begin the pipeline.")
        return
    frame = _records(rows)
    if px is not None and pd is not None:
        ui.plotly_chart(px.bar(frame, x="Status", y="Leads", title="Lead Pipeline Status", text_auto=True), use_container_width=True)
    else:
        ui.bar_chart(frame, x="Status", y="Leads")


def render_recent_activity(data: DashboardData | Any) -> None:
    ui = _require_streamlit()
    dashboard_data = data if isinstance(data, DashboardData) else load_dashboard_data(data)
    if not dashboard_data.activity:
        ui.caption("No activity has been recorded yet.")
        return
    ui.dataframe(
        _records([asdict(row) for row in dashboard_data.activity]),
        use_container_width=True,
        hide_index=True,
    )


def render_leads_table(data: DashboardData | Any) -> None:
    ui = _require_streamlit()
    dashboard_data = data if isinstance(data, DashboardData) else load_dashboard_data(data)
    if not dashboard_data.leads:
        ui.caption("No leads have been created yet.")
        return
    ui.dataframe(
        _records([asdict(row) for row in dashboard_data.leads]),
        use_container_width=True,
        hide_index=True,
    )


def render_file_logs(data: DashboardData | None = None) -> None:
    ui = _require_streamlit()
    logs = data.logs if isinstance(data, DashboardData) else _read_logs()
    if not logs:
        ui.caption("No application log file has been created yet.")
        return
    ui.code(logs, language="text")


def render_dashboard_page(session: Any) -> None:
    ui = _require_streamlit()
    data = load_dashboard_data(session)
    ui.title("Analytics Dashboard")
    render_metric_cards(data)
    render_status_chart(data)
    ui.subheader("Recent Activity")
    render_recent_activity(data)
    ui.subheader("Application Logs")
    render_file_logs(data)
    ui.subheader("Lead Table")
    render_leads_table(data)


def demo_dashboard_data() -> DashboardData:
    now = datetime.now(UTC)
    return DashboardData(
        counts={"DISCOVERED": 2, "SCRAPED": 1, "ENRICHED": 1, "EMAIL_GENERATED": 1, "WAITING_APPROVAL": 3, "APPROVED": 2, "SENT": 5, "FAILED": 1},
        leads=[
            LeadRow(1, "Acme Automation", "https://acme.example", "buyer@acme.example", "SaaS", "WAITING_APPROVAL", _format_time(now)),
            LeadRow(2, "Northstar Clinic", "https://northstar.example", "ops@northstar.example", "Healthcare", "SENT", _format_time(now - timedelta(hours=2))),
        ],
        activity=[
            ActivityRow(_format_time(now), 1, "Approval requested", "Lead is waiting for human approval"),
            ActivityRow(_format_time(now - timedelta(hours=2)), 2, "Email sent", "Sent to ops@northstar.example"),
        ],
        logs="INFO Dashboard demo loaded successfully\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate dashboard data shaping without launching Streamlit.")
    parser.add_argument("--json", action="store_true", help="Print demo dashboard data as JSON")
    args = parser.parse_args()
    data = demo_dashboard_data()
    if args.json:
        print(json.dumps(asdict(data), indent=2, ensure_ascii=False))
    else:
        print(f"Dashboard demo: {len(data.leads)} leads, {sum(data.counts.values())} total lifecycle events represented.")


if __name__ == "__main__":
    main()
