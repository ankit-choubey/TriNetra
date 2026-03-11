"""
Agent 5: Bank Reconciliation Agent
Approach: Data Filtering & Deterministic Math
Tools: pandas (for transaction manipulation)

Trigger: parsing_completed
Reads: documents (bank stmts), gst_analysis, financials
Writes: bank_reconciliation
Logic: Sum annual credit turnover (excluding transfers). Compare bank vs GST vs ITR.
       Detect round-trip transactions. Count bounces.
Errors: BANK_PARSE_FAIL → set reconciliation_verdict=UNKNOWN. Do not block pipeline.
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase


# Keywords to exclude from credit turnover (inter-account transfers & non-revenue)
EXCLUDE_KEYWORDS = [
    "TRF", "NEFT TRF", "RTGS TRF", "IMPS TRF", "OWN ACCOUNT",
    "SELF TRANSFER", "INTERNAL TRANSFER", "FD REDEMPTION",
    "CONTRA", "CASH DEPOSIT", "LOAN DISB", "TAX REFUND", "GST REFUND", "REVERSAL"
]


def sum_credit_turnover(bank_statements: list) -> float:
    """
    Sum all bank credit entries excluding inter-account transfers.
    Uses strict string exclusion logic per blueprint.
    """
    total = 0.0
    for stmt in bank_statements:
        for entry in stmt.get("transactions", []):
            if entry.get("type") != "CREDIT":
                continue
            narration = entry.get("narration", "").upper()
            if any(kw in narration for kw in EXCLUDE_KEYWORDS):
                continue
            total += entry.get("credit_amount", 0.0)
    return total


def detect_round_trips(bank_statements: list, window_days: int = 3) -> list:
    """
    Detect round-trip transactions: same amount credited and debited within N days.
    This indicates potential money laundering or artificial turnover inflation.
    """
    round_trips = []
    all_txns = []

    for stmt in bank_statements:
        for entry in stmt.get("transactions", []):
            txn_date_str = entry.get("date", "")
            try:
                txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            all_txns.append({
                "date": txn_date,
                "type": entry.get("type"),
                "amount": entry.get("credit_amount", 0) or entry.get("debit_amount", 0),
                "narration": entry.get("narration", ""),
            })

    # Sort by date
    all_txns.sort(key=lambda x: x["date"])

    # For each credit, find a matching debit within window
    credits = [t for t in all_txns if t["type"] == "CREDIT" and t["amount"] > 0]
    debits = [t for t in all_txns if t["type"] == "DEBIT" and t["amount"] > 0]

    for credit in credits:
        for debit in debits:
            if abs(credit["amount"] - debit["amount"]) < 1.0:  # Same amount (±₹1)
                days_diff = abs((credit["date"] - debit["date"]).days)
                if 0 < days_diff <= window_days:
                    round_trips.append({
                        "amount": credit["amount"],
                        "credit_date": credit["date"].strftime("%Y-%m-%d"),
                        "debit_date": debit["date"].strftime("%Y-%m-%d"),
                        "days_gap": days_diff,
                    })

    return round_trips


def count_bounces(bank_statements: list) -> int:
    """Count cheque bounces / returns from narration keywords."""
    count = 0
    for stmt in bank_statements:
        for t in stmt.get("transactions", []):
            narration = t.get("narration", "").upper()
            if "BOUNCE" in narration or "RETURN" in narration or "DISHONOUR" in narration:
                count += 1
    return count


def compute_avg_monthly_balance(bank_statements: list) -> float:
    """Compute average monthly closing balance across all statements."""
    balances = []
    for stmt in bank_statements:
        monthly_bal = stmt.get("closing_balance", None)
        if monthly_bal is not None:
            balances.append(monthly_bal)
    return round(sum(balances) / len(balances), 2) if balances else 0.0


class BankReconciliationAgent(AgentBase):
    AGENT_NAME = "bank-recon-agent"
    LISTEN_TOPICS = ["parsing_completed"]
    OUTPUT_NAMESPACE = "bank_reconciliation"
    OUTPUT_EVENT = "bank_recon_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Cross-reference bank credit entries vs GST turnover vs ITR income.
        Detect revenue inflation, round-trip transactions, and bounces.
        """
        documents = ucso.get("documents", {}).get("files", [])
        gst_analysis = ucso.get("gst_analysis", {})
        financials = ucso.get("financials", {})

        # Extract bank statement data from parsed documents
        bank_statements = []
        for doc in documents:
            if doc.get("type") == "BANK_STMT" and doc.get("parsed"):
                extracted = doc.get("extracted_fields", {})
                bank_statements.append(extracted)

        if not bank_statements:
            self.logger.warning(
                f"No parsed bank statements for {application_id}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
            return {
                "bank_credit_turnover": 0.0,
                "gst_reported_turnover": 0.0,
                "itr_reported_income": 0.0,
                "turnover_divergence_pct": 0.0,
                "revenue_inflation_flag": False,
                "round_trip_transactions": [],
                "avg_monthly_balance": 0.0,
                "bounce_count_last_12m": 0,
                "reconciliation_verdict": "UNKNOWN",
            }

        # Step 1: Sum credit turnover (excluding transfers)
        bank_credit_total = sum_credit_turnover(bank_statements)

        # Step 2: Get GST reported turnover
        gst_turnover = gst_analysis.get("gst_reported_turnover", 0.0)
        # Fallback: use revenue from financials
        if gst_turnover == 0.0:
            revenue_list = financials.get("revenue_annual", [])
            gst_turnover = revenue_list[-1] if revenue_list else 0.0

        # Step 3: Get ITR reported income
        itr_income = financials.get("itr_taxable_income", 0.0)

        # Step 4: Divergence calculation
        if gst_turnover > 0:
            divergence = abs(bank_credit_total - gst_turnover) / gst_turnover
        else:
            divergence = 1.0

        # Step 5: Revenue inflation flag (bank > GST × 1.3)
        inflation_flag = bank_credit_total > gst_turnover * 1.3

        # Step 6: Round-trip detection
        round_trips = detect_round_trips(bank_statements, window_days=3)

        # Step 7: Bounce count
        bounces = count_bounces(bank_statements)

        # Step 8: Average monthly balance
        avg_balance = compute_avg_monthly_balance(bank_statements)

        # Verdict
        if divergence > 0.30 or inflation_flag:
            verdict = "INFLATION_SUSPECTED"
        elif divergence > 0.15:
            verdict = "MISMATCH"
        else:
            verdict = "OK"

        return {
            "bank_credit_turnover": round(bank_credit_total, 2),
            "gst_reported_turnover": round(gst_turnover, 2),
            "itr_reported_income": round(itr_income, 2),
            "turnover_divergence_pct": round(divergence * 100, 2),
            "revenue_inflation_flag": inflation_flag,
            "round_trip_transactions": round_trips,
            "avg_monthly_balance": avg_balance,
            "bounce_count_last_12m": bounces,
            "reconciliation_verdict": verdict,
        }


if __name__ == "__main__":
    agent = BankReconciliationAgent()
    agent.run()
