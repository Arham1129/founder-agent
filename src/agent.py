"""Cash Radar agent logic.

Rule of the project: CODE does all the math (see finance.py).
The AI only explains the risks and drafts actions.
The founder approves, edits or rejects every action in the UI.

This file accepts the report exactly as finance.build_risk_report() returns it:
{
  "runway": {"cash": ..., "burn": ..., "runway": ...},
  "overdue_invoices": [{"invoice_id", "customer", "amount", "days_overdue", ...}],
  "payroll_risk": {"has_upcoming_payroll", "pay_date", "payroll_amount",
                   "cash_after_payroll", "risky"},
  "expense_spikes": [{"description", "pct_increase", ...}]
}
It first converts that into a simpler "flat" report (see _normalize_report).
"""

import json
from datetime import date

try:
    from src.llm import ask_llm_json
except ImportError:  # llm.py is not finished yet, the rule-based fallback still works
    ask_llm_json = None

MAX_ACTIONS = 3
CURRENCY = "$"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _money(value) -> str:
    try:
        return f"{CURRENCY}{float(value):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _date_text(value) -> str:
    if value is None:
        return "?"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _runway_text(report: dict) -> str:
    runway = report.get("runway_months")
    if runway is None:
        return "no net cash burn (cash is not shrinking)"
    try:
        return f"{float(runway):.1f} months"
    except (TypeError, ValueError):
        return "n/a"


def _normalize_report(report: dict) -> dict:
    """Convert finance.py's report into a simple flat shape.

    If the report is already flat, it is returned unchanged.
    """
    if not isinstance(report.get("runway"), dict):
        return report

    runway = report["runway"]

    overdue = []
    for inv in report.get("overdue_invoices") or []:
        overdue.append(
            {
                "invoice_id": inv.get("invoice_id", ""),
                "customer": inv.get("customer", ""),
                "amount": inv.get("amount", 0),
                "days_late": inv.get("days_overdue", inv.get("days_late", "?")),
            }
        )

    payroll_in = report.get("payroll_risk") or {}
    payroll = {}
    if payroll_in.get("has_upcoming_payroll"):
        after = payroll_in.get("cash_after_payroll")
        shortfall = max(0.0, -float(after)) if after is not None else 0.0
        payroll = {
            "next_pay_date": _date_text(payroll_in.get("pay_date")),
            "amount": payroll_in.get("payroll_amount"),
            "cash_after_payroll": after,
            "shortfall": shortfall,
            "risky": bool(payroll_in.get("risky")),
        }

    spikes = []
    for spike in report.get("expense_spikes") or []:
        spikes.append(
            {
                "category": spike.get("description", spike.get("category", "")),
                "increase_pct": spike.get("pct_increase", spike.get("increase_pct", 0)),
            }
        )

    return {
        "cash": runway.get("cash"),
        "monthly_burn": runway.get("burn"),
        "runway_months": runway.get("runway"),
        "overdue_invoices": overdue,
        "payroll_risk": payroll,
        "expense_spikes": spikes,
    }


# ---------------------------------------------------------------------------
# Step 1: AI suggests actions (with a rule-based fallback)
# ---------------------------------------------------------------------------

def _build_prompt(report: dict) -> str:
    return f"""You are a careful finance assistant for a startup founder.
Below is a cash report. All numbers were calculated by code, so they are correct.

RULES:
- Use ONLY the facts in the report. Never invent numbers, names or dates.
- Suggest at most {MAX_ACTIONS} specific actions, most urgent first.
- For each action, write a short "draft" the founder can edit (for example a
  polite payment reminder email, or a note to the team).
- You are not a financial advisor. Do not promise results.
- Reply with JSON only, no extra text, in exactly this shape:
{{"actions": [{{"title": "...", "reason": "...", "draft": "..."}}]}}

REPORT:
{json.dumps(report, indent=2, default=str)}
"""


def _clean_actions(raw, source: str) -> list[dict]:
    """Accept {"actions": [...]} or a plain list, keep only valid items."""
    if isinstance(raw, dict):
        raw = raw.get("actions", [])
    if not isinstance(raw, list):
        return []

    actions = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        reason = str(item.get("reason", "")).strip()
        draft = str(item.get("draft", "")).strip()
        if not title or not reason:
            continue
        actions.append(
            {
                "id": len(actions) + 1,
                "title": title,
                "reason": reason,
                "draft": draft,
                "source": source,
            }
        )
        if len(actions) == MAX_ACTIONS:
            break
    return actions


def _fallback_actions(report: dict) -> list[dict]:
    """Simple rules, used when the AI is unavailable or returns bad output."""
    raw = []

    overdue = report.get("overdue_invoices") or []
    if overdue:
        biggest = max(overdue, key=lambda inv: inv.get("amount", 0))
        raw.append(
            {
                "title": f"Send a payment reminder to {biggest.get('customer', 'the customer')}",
                "reason": (
                    f"Invoice {biggest.get('invoice_id', '')} for "
                    f"{_money(biggest.get('amount'))} is {biggest.get('days_late', '?')} days late."
                ),
                "draft": (
                    f"Hi {biggest.get('customer', '')},\n\n"
                    f"A friendly reminder that invoice {biggest.get('invoice_id', '')} "
                    f"for {_money(biggest.get('amount'))} is now overdue. "
                    "Could you let me know when we can expect payment?\n\nThank you!"
                ),
            }
        )

    payroll = report.get("payroll_risk") or {}
    if payroll and (payroll.get("risky") or (payroll.get("shortfall") or 0) > 0):
        raw.append(
            {
                "title": "Prepare for the next payroll",
                "reason": (
                    f"Payroll of {_money(payroll.get('amount'))} is due on "
                    f"{payroll.get('next_pay_date', 'the next pay date')}. "
                    f"Cash after payroll would be {_money(payroll.get('cash_after_payroll'))}, "
                    "which is too tight."
                ),
                "draft": (
                    "Chase the largest overdue invoices first and consider delaying "
                    "non-essential spending until payroll is safely covered."
                ),
            }
        )

    spikes = report.get("expense_spikes") or []
    if spikes:
        top = max(spikes, key=lambda s: s.get("increase_pct", 0))
        raw.append(
            {
                "title": f"Review spending on {top.get('category', 'rising expenses')}",
                "reason": f"This expense rose by about {top.get('increase_pct', 0)}% compared with the previous 3 months.",
                "draft": "Check recent charges for this vendor and cancel or pause anything that is not essential.",
            }
        )

    return _clean_actions(raw, source="rules")


def suggest_actions(report: dict) -> list[dict]:
    """Return up to 3 actions: {"id", "title", "reason", "draft", "source"}.

    Tries the AI first. If the AI is missing, fails or returns nonsense,
    falls back to simple rules so the app never crashes in a demo.
    """
    report = _normalize_report(report)

    if ask_llm_json is not None:
        try:
            actions = _clean_actions(ask_llm_json(_build_prompt(report)), source="ai")
            if actions:
                return actions
        except Exception as error:  # keep the demo alive whatever happens
            print(f"[agent] AI call failed, using fallback rules: {error}")

    return _fallback_actions(report)


# ---------------------------------------------------------------------------
# Step 2: Weekly brief (built by code, so numbers are always correct)
# ---------------------------------------------------------------------------

def build_weekly_brief(report: dict, approved_actions: list[dict], today: date | None = None) -> str:
    """Return the one-page Weekly Cash Brief as markdown."""
    report = _normalize_report(report)
    today = today or date.today()

    lines = [
        f"# Weekly Cash Brief ({today.isoformat()})",
        "",
        "## Snapshot",
        f"- Cash on hand: {_money(report.get('cash'))}",
        f"- Monthly burn: {_money(report.get('monthly_burn'))}",
        f"- Estimated runway: {_runway_text(report)}",
        "",
    ]

    overdue = report.get("overdue_invoices") or []
    lines.append("## Overdue invoices")
    if overdue:
        for inv in overdue:
            lines.append(
                f"- {inv.get('customer', '?')} ({inv.get('invoice_id', '?')}): "
                f"{_money(inv.get('amount'))}, {inv.get('days_late', '?')} days late"
            )
    else:
        lines.append("- None")
    lines.append("")

    payroll = report.get("payroll_risk") or {}
    lines.append("## Payroll")
    if payroll:
        lines.append(
            f"- Next payroll: {_money(payroll.get('amount'))} on {payroll.get('next_pay_date', '?')}"
        )
        shortfall = payroll.get("shortfall", 0) or 0
        if shortfall > 0:
            lines.append(f"- Shortfall: {_money(shortfall)}")
        elif payroll.get("risky"):
            lines.append(
                f"- Cash after payroll: {_money(payroll.get('cash_after_payroll'))} (tight, below 2 months of burn)"
            )
        else:
            lines.append("- Cash covers the next payroll comfortably")
    else:
        lines.append("- No upcoming payroll found")
    lines.append("")

    spikes = report.get("expense_spikes") or []
    lines.append("## Rising expenses")
    if spikes:
        for spike in spikes:
            lines.append(f"- {spike.get('category', '?')}: up about {spike.get('increase_pct', 0)}%")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Actions approved by the founder")
    if approved_actions:
        for number, action in enumerate(approved_actions, start=1):
            lines.append(f"{number}. **{action.get('title', '')}**")
            lines.append(f"   - Why: {action.get('reason', '')}")
            if action.get("draft"):
                lines.append(f"   - Draft: {action['draft']}")
    else:
        lines.append("- No actions approved this week")
    lines.append("")

    lines.append("---")
    lines.append(
        "_This brief is a planning aid, not financial advice. "
        "Every action above was reviewed and approved by the founder._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick test: run `python -m src.agent` from the project root
# ---------------------------------------------------------------------------

def _load_real_report():
    """Use Hassan's real CSVs if they exist, otherwise return None."""
    try:
        import pandas as pd
        from src import finance

        data = finance.BASE_DIR / "data"
        return finance.build_risk_report(
            finance.load_bank(data / "bank.csv"),
            finance.load_invoices(data / "invoices.csv"),
            finance.load_payroll(data / "payroll.csv"),
            pd.Timestamp("2026-11-20"),
        )
    except Exception as error:
        print(f"[test] Real data not used ({error}). Using the sample report.\n")
        return None


if __name__ == "__main__":
    # Sample in the same shape that finance.build_risk_report returns
    sample_report = {
        "runway": {"cash": 42000.0, "burn": 18000.0, "runway": 2.33},
        "overdue_invoices": [
            {"invoice_id": "INV-102", "customer": "Acme Ltd", "amount": 9000, "days_overdue": 21}
        ],
        "payroll_risk": {
            "has_upcoming_payroll": True,
            "pay_date": "2026-12-01",
            "payroll_amount": 15000.0,
            "cash_after_payroll": 27000.0,
            "risky": True,
        },
        "expense_spikes": [{"description": "Cloud hosting", "pct_increase": 35.0}],
    }

    test_report = _load_real_report() or sample_report
    actions = suggest_actions(test_report)
    print(json.dumps(actions, indent=2, default=str))
    print()
    print(build_weekly_brief(test_report, actions))