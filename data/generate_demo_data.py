import csv
from datetime import date
from pathlib import Path

OUT = Path(__file__).parent
CASH_TODAY = 6_000_000
AWS = {6: 180_000, 7:180_000, 8:180_000, 9:190_000, 10:250_000, 11:250_000}
INFLOW = {6: 2_700_000, 7: 2_700_000, 8: 2_700_000, 9: 2_700_000, 10: 2_700_000}

def build_transactions():
    tx = []
    for m in range(6, 12):
        tx.append((date(2026, m, 1), "Office Rent", -400_000))
        tx.append((date(2026, m, 1), "AWS Cloud", -AWS[m]))
        if m <= 10:
            tx.append((date(2026, m, 10), "Operating Expenses", -520_000))
            tx.append((date(2026, m, 12), "Customer Payment -  Beta Retail", 600_000))
            tx.append((date(2026, m, 20), "Customer Payment -  Gulf Mart",  INFLOW[m] - 400_000))
            tx.append((date(2026, m, 29), "Payroll", -3_100_000))
        else:
            tx.append((date(2026, 11, 12), "Customer Payment -  Beta Retail", 1_200_000))
    return sorted(tx)

def write_bank():
    tx = build_transactions()
    balance = CASH_TODAY - sum(t[2] for t in tx)
    with open(OUT / "bank.csv", "w", newline = "") as f:
        w = csv.writer(f)
        w.writerow(["date", "description", "amount", "balance"])
        for d, desc, amt in tx:
            balance += amt
            w.writerow([d.isoformat(), desc, amt, balance])

def write_invoices():
    rows = [
        ["INV-001", "Beta Retail", 600_000, "2026-08-01", "2026-08-31", "paid"],
        ["INV-002", "Gulf Mart", 2_100_000, "2026-09-01", "2026-09-30", "paid"],
        ["INV-003", "Beta Retail", 600_000, "2026-10-01", "2026-10-31", "paid"],
        ["INV-004", "Acme Traders", 2_000_000, "2026-09-28", "2026-10-28", "unpaid"],
    ]
    with open(OUT / "invoices.csv", "w", newline="") as f:
        w =csv.writer(f)
        w.writerow(["invoice_id", "customer", "amount", "issue_date", "due_date", "status"])
        w.writerows(rows)


def write_payroll():
    with open(OUT / "payroll.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pay_date", "amount"])
        for m in range(6, 11):
            w.writerow([date(2026, m, 29).isoformat(), 3_100_000])
        w.writerow(["2026-11-29", 3_100_000])


if __name__ == "__main__":
    write_bank()
    write_invoices()
    write_payroll()
    print("Demo data written to", OUT)