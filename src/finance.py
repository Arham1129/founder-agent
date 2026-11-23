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


if __name__ == "__main__":
    bank_df = load_bank(BASE_DIR / "data"  /"bank.csv")
    invoices_df = load_invoices(BASE_DIR / "data" / "invoices.csv")
    payroll_df = load_payroll(BASE_DIR / "data" / "payroll.csv")

    for name, df in [("bank", bank_df), ("invoices", invoices_df), ("payroll", payroll_df)]:
        print(f"=== {name} ===")
        print(df.head())
        print(df.dtypes)
        print()