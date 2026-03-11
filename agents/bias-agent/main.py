"""
Agent 10: Bias Agent
Approach: Counterfactual Simulation
Tools: Standard Python Math

Trigger: risk_generated
Reads: risk, derived_features
Writes: bias_checks
Logic: For each top-3 SHAP feature: set to median, recompute score.
       If decision flips → add to flip_features, set overweight_flags.
Errors: BIAS_COMPUTE_FAIL → log error, set counterfactual_tested=false.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase


# Indian national medians for key financial features (heuristic baselines)
FEATURE_MEDIANS = {
    "dscr_normalized":           0.45,
    "leverage_normalized":       0.40,
    "revenue_growth_normalized": 0.35,
    "ebitda_margin_normalized":  0.30,
    "gst_discrepancy_norm":      0.10,
    "circular_trade_norm":       0.05,
    "litigation_norm":           0.15,
    "news_sentiment_norm":       0.50,
}

# Risk weights (same as Risk Agent)
WEIGHTS = {
    "dscr_normalized":           0.25,
    "leverage_normalized":       0.18,
    "revenue_growth_normalized": 0.12,
    "ebitda_margin_normalized":  0.10,
    "gst_discrepancy_norm":      0.12,
    "circular_trade_norm":       0.08,
    "litigation_norm":           0.10,
    "news_sentiment_norm":       0.05,
}


def assign_band(score: float) -> str:
    if score < 0.30:
        return "LOW"
    if score < 0.55:
        return "MEDIUM"
    if score < 0.75:
        return "HIGH"
    return "REJECT"


def recompute_score(features: dict) -> float:
    """Recompute weighted risk score from normalized features."""
    score = sum(WEIGHTS[k] * features.get(k, 0.5) for k in WEIGHTS)
    pd_adj = features.get("pd_risk_adjustment", 0.0)
    return round(min(1.0, max(0.0, score + pd_adj)), 4)


class BiasAgent(AgentBase):
    AGENT_NAME = "bias-agent"
    LISTEN_TOPICS = ["risk_generated"]
    OUTPUT_NAMESPACE = "bias_checks"
    OUTPUT_EVENT = "bias_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Counterfactual fairness test:
        For each top-3 SHAP feature, replace with median and recompute.
        If the decision flips (REJECT → APPROVE), flag it.
        """
        risk = ucso.get("risk", {})
        original_score = risk.get("score", 0.5)
        original_band = risk.get("band", "MEDIUM")
        original_decision = risk.get("decision", "REVIEW")
        top_factors = risk.get("top_risk_factors", [])

        feature_vector = risk.get("feature_vector", {})
        pd_adj = ucso.get("pd_intelligence", {}).get("risk_adjustment", 0.0)

        # Build normalized features dict from feature vector
        normalized_features = {
            k: feature_vector.get(k, 0.5) for k in WEIGHTS
        }
        normalized_features["pd_risk_adjustment"] = pd_adj

        flip_features = []
        overweight_flags = []

        try:
            # Test top 3 factors
            for factor in top_factors[:3]:
                feat_name = factor.get("feature", "")
                if feat_name not in WEIGHTS:
                    continue

                # Create modified copy with feature set to median
                modified = normalized_features.copy()
                median_val = FEATURE_MEDIANS.get(feat_name, 0.5)
                modified[feat_name] = median_val

                # Recompute score
                new_score = recompute_score(modified)
                new_band = assign_band(new_score)
                new_decision = (
                    "APPROVE" if new_band in ("LOW", "MEDIUM")
                    else ("REVIEW" if new_band == "HIGH" else "REJECT")
                )

                self.logger.info(
                    f"Counterfactual [{feat_name}]: "
                    f"original={original_score:.4f} ({original_decision}) → "
                    f"modified={new_score:.4f} ({new_decision})",
                    extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                )

                # Check if decision flips
                if new_decision != original_decision:
                    flip_features.append({
                        "feature": feat_name,
                        "original_value": round(normalized_features.get(feat_name, 0), 4),
                        "median_value": median_val,
                        "original_score": original_score,
                        "modified_score": new_score,
                        "original_decision": original_decision,
                        "modified_decision": new_decision,
                    })

                # Check if single feature contributes >30% of total score
                contribution = WEIGHTS.get(feat_name, 0) * normalized_features.get(feat_name, 0)
                if contribution / max(original_score, 0.01) > 0.30:
                    overweight_flags.append({
                        "feature": feat_name,
                        "contribution_pct": round(
                            contribution / max(original_score, 0.01) * 100, 2
                        ),
                    })

            return {
                "counterfactual_tested": True,
                "flip_features": flip_features,
                "overweight_flags": overweight_flags,
            }

        except Exception as e:
            self.logger.error(
                f"Bias computation failed: {e}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
            return {
                "counterfactual_tested": False,
                "flip_features": [],
                "overweight_flags": [],
            }


if __name__ == "__main__":
    agent = BiasAgent()
    agent.run()
