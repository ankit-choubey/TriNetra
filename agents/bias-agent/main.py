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


def compute_decision_confidence(ucso: dict) -> dict:
    """
    Compute overall Decision Confidence score.

    Formula (from UCSO schema):
        score = 0.30 * data_completeness
              + 0.30 * extraction_confidence
              + 0.20 * kb_freshness
              + 0.20 * model_stability

    Components:
        data_completeness   — fraction of expected financial fields that are non-zero
        extraction_confidence — avg doc parse confidence from documents.files[]
        kb_freshness        — 1.0 if Weaviate KB is fresh (or not used), 0.5 if stale
        model_stability     — 1.0 for trained models (LOGISTIC/XGBOOST/LGBM), 0.85 for RULE_FALLBACK
    """
    # ── Component 1: Data Completeness ──
    financials = ucso.get("financials", {})
    applicant  = ucso.get("applicant", {})

    expected_financial_fields = [
        "revenue_annual", "ebitda_annual", "net_profit_annual",
        "total_debt", "net_worth", "interest_expense",
    ]
    filled_financial = sum(
        1 for f in expected_financial_fields
        if financials.get(f) not in (None, 0, 0.0, [], "")
    )
    expected_applicant_fields = ["company_name", "pan", "cin", "loan_amount_requested"]
    filled_applicant = sum(
        1 for f in expected_applicant_fields
        if applicant.get(f) not in (None, 0, 0.0, "", "N/A")
    )
    total_expected = len(expected_financial_fields) + len(expected_applicant_fields)
    total_filled   = filled_financial + filled_applicant
    data_completeness = round(total_filled / max(total_expected, 1), 4)

    # ── Component 2: Extraction Confidence ──
    files = ucso.get("documents", {}).get("files", [])
    if files:
        confidences = [f.get("confidence", 0.5) for f in files]
        extraction_confidence = round(sum(confidences) / len(confidences), 4)
    else:
        extraction_confidence = 0.5  # neutral default if no docs parsed yet

    # ── Component 3: KB Freshness ──
    # Weaviate is optional — if not running, default to 1.0 (doesn't penalize)
    kb_hours = ucso.get("web_intel", {}).get("kb_freshness_hours", 0)
    if kb_hours == 0:
        kb_freshness = 1.0  # Not used / not applicable
    elif kb_hours <= 24:
        kb_freshness = 1.0
    elif kb_hours <= 168:  # 1 week
        kb_freshness = 0.75
    else:
        kb_freshness = 0.5

    # ── Component 4: Model Stability ──
    model_used = ucso.get("risk", {}).get("model_used", "")
    stability_map = {
        "LOGISTIC":      1.0,
        "XGBOOST":       1.0,
        "LGBM":          1.0,
        "RULE_FALLBACK": 0.85,
    }
    model_stability = stability_map.get(model_used.upper() if model_used else "", 0.85)

    # ── Final Score ──
    score = round(
        0.30 * data_completeness
        + 0.30 * extraction_confidence
        + 0.20 * kb_freshness
        + 0.20 * model_stability,
        4,
    )

    formula_str = (
        f"0.30×{data_completeness:.2f}(completeness) "
        f"+ 0.30×{extraction_confidence:.2f}(extraction) "
        f"+ 0.20×{kb_freshness:.2f}(kb_freshness) "
        f"+ 0.20×{model_stability:.2f}(model_stability)"
    )

    return {
        "score": score,
        "data_completeness": data_completeness,
        "extraction_confidence": extraction_confidence,
        "kb_freshness": kb_freshness,
        "model_stability": model_stability,
        "formula": formula_str,
    }


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

        finally:
            # ── Decision Confidence (always computed, non-blocking) ──
            # Runs whether bias succeeded or failed. Separate PATCH so
            # any error here CANNOT affect bias_checks or bias_completed event.
            try:
                conf = compute_decision_confidence(ucso)
                self.ucso_client.patch_namespace(
                    application_id, "decision_confidence", conf
                )
                self.logger.info(
                    f"Decision confidence for {application_id}: {conf['score']:.4f} "
                    f"(completeness={conf['data_completeness']:.2f}, "
                    f"extraction={conf['extraction_confidence']:.2f})",
                    extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                )
            except Exception as conf_err:
                self.logger.warning(
                    f"Decision confidence compute failed (non-blocking): {conf_err}",
                    extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                )


if __name__ == "__main__":
    agent = BiasAgent()
    agent.run()
