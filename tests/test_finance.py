import pandas as pd
import pytest

from src.finance import (
    BASE_DIR,
    load_bank,
    load_invoices,
    load_payroll,
    calculate_runway,
    find_overdue_invoices,
    check_payroll_risk,
    detect_expense_spikes,
    build_risk_report,
)

DATA = BASE_DIR / "data"
TODAY = pd.Timestamp("2026-11-20")


@pytest.fixture
def bank_df():
    return load_bank(DATA / "bank.csv")


@pytest.fixture
def invoices_df():
    return load_invoices(DATA / "invoices.csv")


@pytest.fixture
def payroll_df():
    return load_payroll(DATA / "payroll.csv")


# ---------- main scenario (expected values hand-calculated) ----------

def test_runway(bank_df):
    r = calculate_runway(bank_df)
    assert r["cash"] == 6_000_000
    assert r["burn"] == pytest.approx(1_500_000)
    assert r["runway"] == pytest.approx(4.0)


def test_overdue_invoice_found(invoices_df):
    result = find_overdue_invoices(invoices_df, TODAY)
    assert len(result) == 1
    assert result[0]["customer"] == "Acme Traders"
    assert result[0]["amount"] == 2_000_000
    assert result[0]["days_overdue"] == 23


def test_payroll_risk_is_flagged(payroll_df):
    r = check_payroll_risk(6_000_000, payroll_df, TODAY, burn=1_500_000)
    assert r["has_upcoming_payroll"] is True
    assert r["payroll_amount"] == 3_100_000
    assert r["cash_after_payroll"] == 2_900_000
    assert r["risky"] is True


def test_aws_expense_spike(bank_df):
    spikes = detect_expense_spikes(bank_df)
    assert len(spikes) == 1
    assert spikes[0]["description"] == "AWS Cloud"
    assert spikes[0]["pct_increase"] == pytest.approx(36.4, abs=0.1)


def test_full_report(bank_df, invoices_df, payroll_df):
    report = build_risk_report(bank_df, invoices_df, payroll_df, TODAY)
    assert set(report) == {"runway", "overdue_invoices", "payroll_risk", "expense_spikes"}
    assert report["runway"]["runway"] == pytest.approx(4.0)
    assert report["payroll_risk"]["risky"] is True


# ---------- edge cases ----------

def test_no_overdue_invoices_early_september(invoices_df):
    assert find_overdue_invoices(invoices_df, pd.Timestamp("2026-09-01")) == []


def test_no_upcoming_payroll(payroll_df):
    r = check_payroll_risk(6_000_000, payroll_df, pd.Timestamp("2026-12-15"), burn=1_500_000)
    assert r["has_upcoming_payroll"] is False
    assert r["risky"] is False


def test_payroll_not_risky_when_cash_is_high(payroll_df):
    r = check_payroll_risk(20_000_000, payroll_df, TODAY, burn=1_500_000)
    assert r["risky"] is False


def test_zero_burn_gives_no_runway(bank_df):
    profitable = bank_df.copy()
    profitable["amount"] = profitable["amount"].abs()  # every transaction is money in
    assert calculate_runway(profitable)["runway"] is None


def test_load_bank_missing_column(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("date,description,amount\n2026-01-01,Test,100\n")
    with pytest.raises(ValueError):
        load_bank(bad)