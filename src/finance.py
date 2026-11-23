from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

def load_bank(path: str | Path) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Bank CSV Not Found: {file_path.resolve()}")

    df = pd.read_csv(file_path, parse_dates=["date"])
    # df["date"] = pd.to_datetime(df["date"])
    required = {"date", "description", "amount", "balance"}
    missing = required - set(df.columns)

    if(missing):
        raise ValueError(f"Missing Required Columns: {sorted(missing)}")
    return df



def load_invoices(path: str | Path) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Invoice CSV Not Found:{file_path.resolve()}")

    df = pd.read_csv(file_path, parse_dates=["issue_date", "due_date"])

    required = {"invoice_id", "customer", "amount", "issue_date", "due_date", "status"}
    missing = required - set(df.columns)

    if(missing):
        raise ValueError(f"Missing Required Columns: {sorted(missing)}")
    return df

def load_payroll(path: str | Path) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Payroll CSV Not Found:{file_path.resolve()}")

    df = pd.read_csv(file_path, parse_dates=["pay_date"])

    required = {"pay_date", "amount"}
    missing = required - set(df.columns)

    if(missing):
        raise ValueError(f"Missing Required Columns: {sorted(missing)}")
    return df


def calculate_runway(bank_df: pd.DataFrame) -> dict:
    df = bank_df.sort_values("date")
    cash = float(df["balance"].iloc[-1])
    monthly_net = df.groupby(df["date"].dt.to_period("M"))["amount"].sum()
    last_full = _last_full_month(bank_df)
    monthly_net = monthly_net[monthly_net.index <= last_full]
    last_3 = monthly_net.tail(3)
    burn = float(-last_3.mean())

    if burn <= 0:
        runway = None
    else:
        runway = round(cash / burn, 2)

    return {
        "cash" : cash,
        "burn" : burn,
        "runway" : runway,
    }

def find_overdue_invoices(invoices_df: pd.DataFrame, today: pd.Timestamp) -> list[dict]:
    today_ts = pd.Timestamp(today)
    overdue = invoices_df[(invoices_df["status"] == "unpaid") & (invoices_df["due_date"] < today_ts)].copy()
    overdue["days_overdue"] = (today_ts - overdue["due_date"]).dt.days
    return overdue.to_dict("records")

def check_payroll_risk(cash, payroll_df: pd.DataFrame, today: pd.Timestamp, burn: float | None = None) -> dict:
    today_ts = pd.Timestamp(today)
    upcoming = payroll_df.sort_values("pay_date")
    upcoming = upcoming[upcoming["pay_date"] > today_ts]

    if upcoming.empty:
        return {
            "has_upcoming_payroll": False,
            "pay_date": None,
            "payroll_amount": None,
            "cash_after_payroll": float(cash),
            "risky": False,
        }

    next_pay = upcoming.iloc[0]
    payroll_amount = float(next_pay["amount"])
    cash_after_payroll = float(cash) - payroll_amount

    if burn is not None and burn > 0:
        risky = cash_after_payroll < (2 * burn)
    else:
        risky = cash_after_payroll < 0

    return {
        "has_upcoming_payroll": True,
        "pay_date": next_pay["pay_date"],
        "payroll_amount": payroll_amount,
        "cash_after_payroll": cash_after_payroll,
        "risky": risky,
    }

def detect_expense_spikes(bank_df: pd.DataFrame) -> list[dict]:
    outflows = bank_df[bank_df["amount"] < 0].copy()
    outflows["month"] = outflows["date"].dt.to_period("M")
    outflows["spend"] = outflows["amount"].abs()

    monthly_spend = (
        outflows.groupby(["description", "month"])["spend"].sum().unstack(fill_value = 0)
    )

    latest_month = _last_full_month(bank_df)
    monthly_spend = monthly_spend.loc[:, monthly_spend.columns <= latest_month]
    prev_3_months = [latest_month - 3, latest_month - 2, latest_month -1]

    if latest_month not in monthly_spend.columns or not all(
        m in monthly_spend.columns for m in prev_3_months
    ):
        return[]

    spikes = []

    for vendor, row in monthly_spend.iterrows():
        latest_val = float(row[latest_month])
        baseline_avg = float(row[prev_3_months].mean())

        if baseline_avg > 0:
            pct_increase = (latest_val - baseline_avg) / baseline_avg
            if pct_increase > 0.20:
                spikes.append({
                    "description" : vendor,
                    "latest_month" : str(latest_month),
                    "latest_spend" : latest_val,
                    "prior_3m_avg" : round(baseline_avg, 2),
                    "pct_increase" : round(pct_increase * 100, 1),
                })
    return spikes


def _last_full_month(bank_df: pd.DataFrame) -> pd.Period:
    max_date = pd.to_datetime(bank_df['date']).max()

    period = max_date.to_period('M')

    if max_date.is_month_end:
        return period
    else:
        return period - 1

def build_risk_report(
    bank_df: pd.DataFrame,
    invoices_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
    today: pd.Timestamp | str,
        ) -> dict:
    runway_info = calculate_runway(bank_df)
    overdue_invoices = find_overdue_invoices(invoices_df, today)
    payroll_risk = check_payroll_risk(
        cash=runway_info["cash"],
        payroll_df=payroll_df,
        today=today,
        burn=runway_info["burn"],
    )
    expense_spikes = detect_expense_spikes(bank_df)

    return {
        "runway": runway_info,
        "overdue_invoices": overdue_invoices,
        "payroll_risk": payroll_risk,
        "expense_spikes": expense_spikes,
    }

if __name__ == "__main__":
    bank_df = load_bank(BASE_DIR / "data"  /"bank.csv")
    invoices_df = load_invoices(BASE_DIR / "data" / "invoices.csv")
    payroll_df = load_payroll(BASE_DIR / "data" / "payroll.csv")
    today = pd.Timestamp("2026-11-20")
    print(build_risk_report(bank_df, invoices_df, payroll_df, today))

    # for name, df in [("bank", bank_df), ("invoices", invoices_df), ("payroll", payroll_df)]:
    #     print(f"=== {name} ===")
    #     print(df.head())
    #     print(df.dtypes)
    #     print()