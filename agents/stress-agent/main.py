"""
Agent 11: Stress Agent
Approach: Financial Projections Math
Tools: Standard Python Math

Trigger: risk_generated
Reads: derived_features, financials
Writes: stress_results
Logic: Run 3 scenarios: Revenue-20%, Rate+2%, Combined.
       Recalculate DSCR for each. Assign verdict per scenario.
Errors: STRESS_COMPUTE_FAIL → set all verdicts=UNKNOWN.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase


def compute_dscr(net_operating_income: float, total_debt_service: float) -> float:
    """
    DSCR = Net Operating Income / Total Debt Service
    Total Debt Service = Interest Expense + Principal Repayment
    """
    if total_debt_service == 0:
        return 99.0  # effectively infinite coverage
    return round(net_operating_income / total_debt_service, 4)


def compute_stressed_dscr(
    revenue: float,
    operating_expenses: float,
    interest_expense: float,
    principal_repayment: float,
    revenue_shock: float = 0.0,
    rate_shock_bps: float = 0.0,
    vacancy_factor: float = 0.05,
) -> float:
    """
    Compute DSCR under stress conditions according to PDF formulas.

    Args:
        revenue: Annual gross revenue (or rental income).
        operating_expenses: Fixed annual operating expenses.
        interest_expense: Annual interest expense.
        principal_repayment: Annual principal repayment.
        revenue_shock: Fractional decrease in revenue (e.g., -0.20 for -20%).
        rate_shock_bps: Absolute increase in interest rate in basis points (e.g., 200 for +2%).
        vacancy_factor: Baseline or stressed vacancy rate (e.g., 0.05 or 0.15).
    """
    # 1. Apply Revenue Shock and Vacancy
    gross_income = revenue * (1 + revenue_shock)
    effective_gross_income = gross_income * (1 - vacancy_factor)
    
    # 2. Subtract fixed operating expenses to get Stressed NOI
    stressed_noi = max(0.0, effective_gross_income - operating_expenses)

    # 3. Apply Interest Rate Shock (simplified approximation: (Current Interest) * (1 + (bps/10000)/base_rate))
    # Assuming a base rate of 10% (0.10) for calculation purposes if base rate is unknown
    base_rate = 0.10
    if interest_expense > 0 and rate_shock_bps > 0:
        rate_increase_pct = (rate_shock_bps / 10000) / base_rate
        stressed_interest = interest_expense * (1 + rate_increase_pct)
    else:
        stressed_interest = interest_expense

    total_debt_service = stressed_interest + principal_repayment
    return compute_dscr(stressed_noi, total_debt_service)


def assign_stress_verdict(dscr: float) -> str:
    """Assign verdict based on stressed DSCR."""
    if dscr >= 1.25:
        return "SURVIVES"
    elif dscr >= 1.0:
        return "VULNERABLE"
    else:
        return "CRITICAL"


class StressAgent(AgentBase):
    AGENT_NAME = "stress-agent"
    LISTEN_TOPICS = ["risk_generated"]
    OUTPUT_NAMESPACE = "stress_results"
    OUTPUT_EVENT = "stress_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Run 3 stress scenarios and report DSCR impact:
        1. Revenue drops 20%
        2. Interest rate rises 2%
        3. Combined (both simultaneously)
        """
        financials = ucso.get("financials", {})
        derived = ucso.get("derived_features", {})

        # Extract base financial data (from previous code)
        revenue_list = financials.get("revenue_annual", [])
        ebitda_list = financials.get("ebitda_annual", [])
        revenue = revenue_list[-1] if revenue_list else 0
        ebitda = ebitda_list[-1] if ebitda_list else 0
        interest_expense = financials.get("interest_expense", 0)
        principal_repayment = financials.get("principal_repayment", 0)

        # Estimate operating expenses based on ebitda if not provided directly
        operating_expenses = financials.get("operating_expenses", max(0, revenue - ebitda))

        # Base DSCR
        base_dscr = derived.get("dscr", compute_dscr(
            max(0, revenue - operating_expenses), interest_expense + principal_repayment
        ))

        try:
            # Scenario 1: Revenue drops 20%
            dscr_rev_shock = compute_stressed_dscr(
                revenue, operating_expenses, interest_expense, principal_repayment,
                revenue_shock=-0.20,
                vacancy_factor=0.15, # Stress vacancy factor
            )

            # Scenario 2: Interest rate rises 2% (200 bps)
            dscr_rate_shock = compute_stressed_dscr(
                revenue, operating_expenses, interest_expense, principal_repayment,
                rate_shock_bps=200,
            )

            # Scenario 3: Combined
            dscr_combined = compute_stressed_dscr(
                revenue, operating_expenses, interest_expense, principal_repayment,
                revenue_shock=-0.20,
                rate_shock_bps=200,
                vacancy_factor=0.15,
            )

            scenarios = [
                {
                    "name": "Revenue-20%",
                    "dscr": dscr_rev_shock,
                    "verdict": assign_stress_verdict(dscr_rev_shock),
                },
                {
                    "name": "Rate+2%",
                    "dscr": dscr_rate_shock,
                    "verdict": assign_stress_verdict(dscr_rate_shock),
                },
                {
                    "name": "Combined",
                    "dscr": dscr_combined,
                    "verdict": assign_stress_verdict(dscr_combined),
                },
            ]

            worst_dscr = min(s["dscr"] for s in scenarios)
            survival_verdict = assign_stress_verdict(worst_dscr)

            self.logger.info(
                f"Stress results for {application_id}: "
                f"Base DSCR={base_dscr}, "
                f"Rev-20%={dscr_rev_shock}, Rate+2%={dscr_rate_shock}, "
                f"Combined={dscr_combined} → {survival_verdict}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )

            return {
                "scenarios": scenarios,
                "worst_case_dscr": worst_dscr,
                "survival_verdict": survival_verdict,
            }

        except Exception as e:
            self.logger.error(
                f"Stress computation failed: {e}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
            return {
                "scenarios": [
                    {"name": "Revenue-20%", "dscr": 0.0, "verdict": "UNKNOWN"},
                    {"name": "Rate+2%", "dscr": 0.0, "verdict": "UNKNOWN"},
                    {"name": "Combined", "dscr": 0.0, "verdict": "UNKNOWN"},
                ],
                "worst_case_dscr": 0.0,
                "survival_verdict": "UNKNOWN",
            }


if __name__ == "__main__":
    agent = StressAgent()
    agent.run()
