"""Cash Radar agent logic.

Rule of the project: CODE does all the math (see finance.py).
The AI only explains the risks and drafts actions.
The founder approves, edits or rejects every action in the UI.

Expected `report` shape (built by finance.build_risk_report):
{
  "cash": 42000.0,
  "monthly_burn": 18000.0,
  "runway_months": 2.3,
  "overdue_invoices": [{"invoice_id": "", "customer": "", "amount": 0, "days_late": 0}],
  "payroll_risk": {"next_pay_date": "", "amount": 0, "shortfall": 0},
  "expense_spikes": [{"category": "", "increase_pct": 0}]
}
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


def _runway_text(report: dict) -> str:
    runway = report.get("runway_months")
    try:
        return f"{float(runway):.1f} months"
    except (TypeError, ValueError):
        return "n/a"


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
    if payroll.get("shortfall", 0) and payroll.get("shortfall", 0) > 0:
        raw.append(
            {
                "title": "Prepare for the next payroll shortfall",
                "reason": (
                    f"Payroll of {_money(payroll.get('amount'))} is due on "
                    f"{payroll.get('next_pay_date', 'the next pay date')} and cash is short by "
                    f"{_money(payroll.get('shortfall'))}."
                ),
                "draft": "Chase the largest overdue invoices first and consider delaying non-essential spending until payroll is covered.",
            }
        )

    spikes = report.get("expense_spikes") or []
    if spikes:
        top = max(spikes, key=lambda s: s.get("increase_pct", 0))
        raw.append(
            {
                "title": f"Review spending on {top.get('category', 'rising expenses')}",
                "reason": f"This category rose by about {top.get('increase_pct', 0)}% recently.",
                "draft": "Check recent charges in this category and cancel or pause anything that is not essential.",
            }
        )

    return _clean_actions(raw, source="rules")


def suggest_actions(report: dict) -> list[dict]:
    """Return up to 3 actions: {"id", "title", "reason", "draft", "source"}.

    Tries the AI first. If the AI is missing, fails or returns nonsense,
    falls back to simple rules so the app never crashes in a demo.
    """
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
        lines.append(
            f"- Shortfall: {_money(shortfall)}" if shortfall > 0 else "- Cash covers the next payroll"
        )
    else:
        lines.append("- No payroll data")
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

if __name__ == "__main__":
    sample_report = {
        "cash": 42000.0,
        "monthly_burn": 18000.0,
        "runway_months": 2.3,
        "overdue_invoices": [
            {"invoice_id": "INV-102", "customer": "Acme Ltd", "amount": 9000, "days_late": 21}
        ],
        "payroll_risk": {"next_pay_date": "2026-12-01", "amount": 15000, "shortfall": 0},
        "expense_spikes": [{"category": "Cloud hosting", "increase_pct": 35}],
    }
    actions = suggest_actions(sample_report)
    print(json.dumps(actions, indent=2))
    print()
    print(build_weekly_brief(sample_report, actions))