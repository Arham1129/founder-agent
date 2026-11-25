"""Streamlit screens for Cash Radar.

Flow on the page:
  1. Add data (upload 3 CSVs, or use the demo data)
  2. Risk dashboard (numbers come from finance.py, never from the AI)
  3. Human checkpoint: the founder approves, edits or rejects every action
  4. Weekly Cash Brief (only contains approved actions) + download

app.py just calls render_app().
"""

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src import agent, finance

DEMO_DIR = finance.BASE_DIR / "data"
DEMO_FILES = {
    "bank": "bank.csv",
    "invoices": "invoices.csv",
    "payroll": "payroll.csv",
}

CURRENCY = agent.CURRENCY


def _money(value) -> str:
    try:
        return f"{CURRENCY}{float(value):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _save_upload(uploaded_file) -> Path:
    """finance.py loaders need a file path, so save the upload to a temp file."""
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    temp.write(uploaded_file.getvalue())
    temp.close()
    return Path(temp.name)


def _reset_review_state() -> None:
    """Forget old Approve/Reject choices when a new analysis starts."""
    for key in list(st.session_state.keys()):
        if key.startswith(("draft_", "decision_")):
            del st.session_state[key]


# ---------------------------------------------------------------------------
# 1. Upload screen
# ---------------------------------------------------------------------------

def render_upload():
    """Show the upload area. Returns (paths, report_date) when the user clicks Analyze, else None."""
    st.subheader("1. Add your data")

    use_demo = st.checkbox("Use demo data (fake startup, safe to show)", value=True)
    report_date = st.date_input("Report date", value=date.today())

    sources = None
    if use_demo:
        missing = [name for name in DEMO_FILES.values() if not (DEMO_DIR / name).is_file()]
        if missing:
            st.error(f"Demo files not found in the data/ folder: {', '.join(missing)}")
        else:
            sources = {key: DEMO_DIR / name for key, name in DEMO_FILES.items()}
    else:
        col1, col2, col3 = st.columns(3)
        bank = col1.file_uploader("Bank CSV", type="csv", help="Columns: date, description, amount, balance")
        invoices = col2.file_uploader(
            "Invoices CSV",
            type="csv",
            help="Columns: invoice_id, customer, amount, issue_date, due_date, status",
        )
        payroll = col3.file_uploader("Payroll CSV", type="csv", help="Columns: pay_date, amount")
        if bank and invoices and payroll:
            sources = {"bank": bank, "invoices": invoices, "payroll": payroll}

    if st.button("Analyze my cash", type="primary", disabled=sources is None):
        paths = {}
        for key, source in sources.items():
            paths[key] = source if isinstance(source, Path) else _save_upload(source)
        return paths, report_date
    return None


# ---------------------------------------------------------------------------
# 2. Risk dashboard
# ---------------------------------------------------------------------------

def render_risk_dashboard(report: dict) -> None:
    """Show the numbers calculated by finance.py."""
    flat = agent._normalize_report(report)

    st.subheader("2. Your cash picture")

    runway = flat.get("runway_months")
    col1, col2, col3 = st.columns(3)
    col1.metric("Cash on hand", _money(flat.get("cash")))
    col2.metric("Monthly burn", _money(flat.get("monthly_burn")))
    col3.metric("Runway", "No net burn" if runway is None else f"{float(runway):.1f} months")

    if runway is not None and float(runway) < 3:
        st.error("Runway is under 3 months. Cash problems could arrive soon.")
    elif runway is not None and float(runway) < 6:
        st.warning("Runway is under 6 months. Keep a close eye on cash.")

    st.markdown("**Overdue invoices**")
    overdue = flat.get("overdue_invoices") or []
    if overdue:
        table = pd.DataFrame(overdue)[["invoice_id", "customer", "amount", "days_late"]]
        table.columns = ["Invoice", "Customer", "Amount", "Days late"]
        st.dataframe(table, hide_index=True)
    else:
        st.success("No overdue invoices.")

    st.markdown("**Next payroll**")
    payroll = flat.get("payroll_risk") or {}
    if not payroll:
        st.info("No upcoming payroll found.")
    else:
        text = f"{_money(payroll.get('amount'))} due on {payroll.get('next_pay_date')}"
        if (payroll.get("shortfall") or 0) > 0:
            st.error(f"{text}. Cash is short by {_money(payroll.get('shortfall'))}.")
        elif payroll.get("risky"):
            st.warning(
                f"{text}. Cash after payroll would be {_money(payroll.get('cash_after_payroll'))}, "
                "which is less than 2 months of burn."
            )
        else:
            st.success(f"{text}. Cash covers it comfortably.")

    st.markdown("**Rising expenses**")
    spikes = flat.get("expense_spikes") or []
    if spikes:
        table = pd.DataFrame(spikes)[["category", "increase_pct"]]
        table.columns = ["Vendor / expense", "Increase vs previous 3 months (%)"]
        st.dataframe(table, hide_index=True)
    else:
        st.success("No unusual expense spikes.")


# ---------------------------------------------------------------------------
# 3. Human checkpoint
# ---------------------------------------------------------------------------

def render_action_review(actions: list[dict]):
    """Show each suggested action. Returns (approved_actions, pending_count).

    The founder must choose Approve or Reject for every action.
    Approved actions keep any edits the founder made to the draft.
    """
    st.subheader("3. You decide")
    st.caption(
        "The AI only suggests. Nothing goes into your brief unless you approve it. "
        "You can edit any draft before approving."
    )

    approved = []
    pending = 0

    if not actions:
        st.info("No actions suggested this week.")
        return approved, pending

    for action in actions:
        with st.container(border=True):
            st.markdown(f"**{action['id']}. {action['title']}**")
            st.write(action["reason"])
            origin = "AI suggestion" if action.get("source") == "ai" else "Rule-based suggestion"
            st.caption(origin)

            draft = st.text_area(
                "Draft (edit it if you like)",
                value=action.get("draft", ""),
                key=f"draft_{action['id']}",
                height=140,
            )
            choice = st.radio(
                "Your decision",
                ["Undecided", "Approve", "Reject"],
                horizontal=True,
                key=f"decision_{action['id']}",
            )

            if choice == "Approve":
                approved.append({**action, "draft": draft})
            elif choice == "Undecided":
                pending += 1

    return approved, pending


# ---------------------------------------------------------------------------
# 4. Weekly brief
# ---------------------------------------------------------------------------

def render_brief(brief_markdown: str) -> None:
    st.subheader("4. Your Weekly Cash Brief")
    with st.container(border=True):
        st.markdown(brief_markdown)
    st.download_button(
        "Download brief (.md)",
        data=brief_markdown,
        file_name="weekly-cash-brief.md",
        mime="text/markdown",
    )


# ---------------------------------------------------------------------------
# Whole page
# ---------------------------------------------------------------------------

def _build_report(paths: dict, report_date: date) -> dict:
    bank = finance.load_bank(paths["bank"])
    invoices = finance.load_invoices(paths["invoices"])
    payroll = finance.load_payroll(paths["payroll"])
    return finance.build_risk_report(bank, invoices, payroll, pd.Timestamp(report_date))


def render_app() -> None:
    st.title("Cash Radar")
    st.write(
        "Spot cash problems early. Our code does the math, the AI suggests actions, "
        "and **you** make every decision."
    )

    result = render_upload()
    if result:
        paths, report_date = result
        try:
            with st.spinner("Analyzing your cash..."):
                report = _build_report(paths, report_date)
                actions = agent.suggest_actions(report)
        except Exception as error:
            st.error(
                "Something went wrong while reading your files. "
                "Check the column names and date formats.\n\n"
                f"Details: {error}"
            )
            return
        _reset_review_state()
        st.session_state["report"] = report
        st.session_state["actions"] = actions
        st.session_state["report_date"] = report_date

    report = st.session_state.get("report")
    if report is None:
        st.info("Choose your data and click **Analyze my cash** to begin.")
        return

    st.divider()
    render_risk_dashboard(report)

    st.divider()
    approved, pending = render_action_review(st.session_state.get("actions", []))

    st.divider()
    if pending:
        st.info(f"{pending} action(s) still need your decision before the brief is created.")
    else:
        brief = agent.build_weekly_brief(
            report, approved, st.session_state.get("report_date")
        )
        render_brief(brief)

    st.caption(
        "Cash Radar is a planning aid, not financial advice. "
        "Demo data is fictional."
    )