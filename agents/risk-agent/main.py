"""
Agent 9: Risk Agent
Approach: Tree-Based Machine Learning & Explainable AI (XAI)
Tools: xgboost, lightgbm, shap, lime

Trigger: model_selected
Reads: derived_features, gst_analysis, bank_reconciliation, web_intel, pd_intelligence
Writes: risk
Logic: Normalize features → Weighted score → SHAP + LIME → Limits + Rate
Errors: SHAP_FAIL → continue without SHAP. LIME_FAIL → continue without LIME.
"""
import sys
import os
import pickle
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase


# ── Feature Normalization (from Blueprint Section 2.1) ──
FEATURE_BOUNDS = {
    # (raw_min, raw_max, risk_direction)
    # 'inverse' = lower raw = higher risk
    # 'direct'  = higher raw = higher risk
    "dscr":             (0.5,  2.5,  "inverse"),
    "icr":              (1.0,  5.0,  "inverse"),
    "leverage":         (0.0,  5.0,  "direct"),
    "ccc":              (0,    180,  "direct"),
    "revenue_growth":   (-0.3, 0.4,  "inverse"),
    "ebitda_margin":    (-0.1, 0.4,  "inverse"),
    "gst_discrepancy":  (0.0,  0.5,  "direct"),
    "circular_trade":   (0.0,  0.5,  "direct"),
    "litigation_count": (0,    10,   "direct"),
    "news_sentiment":   (-1.0, 1.0,  "inverse"),
}

# ── Outlier Safe Bounds (from Blueprint Section 4, GAP 3) ──
SAFE_BOUNDS = {
    "dscr":           (0.0, 5.0),
    "leverage":       (0.0, 20.0),
    "revenue_growth": (-1.0, 5.0),
    "ccc":            (-365, 365),
}

# ── Risk Weights (from Blueprint Section 2.2) ──
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
# Total = 1.00


def handle_outlier(feature_name: str, raw_value: float) -> float:
    """Clip outliers to safe production bounds."""
    lo, hi = SAFE_BOUNDS.get(feature_name, (-1e9, 1e9))
    return max(lo, min(hi, raw_value))


def normalize(raw_value: float, feat_name: str) -> float:
    """Normalize a raw feature to [0, 1] risk scale."""
    if feat_name not in FEATURE_BOUNDS:
        return 0.5

    lo, hi, direction = FEATURE_BOUNDS[feat_name]
    clipped = max(lo, min(hi, raw_value))
    ratio = (clipped - lo) / (hi - lo) if (hi - lo) != 0 else 0.0
    return (1 - ratio) if direction == "inverse" else ratio


def compute_risk_score(features: dict) -> float:
    """Compute weighted risk score."""
    score = sum(WEIGHTS[k] * features.get(k, 0.5) for k in WEIGHTS)
    pd_adj = features.get("pd_risk_adjustment", 0.0)
    return round(min(1.0, max(0.0, score + pd_adj)), 4)


def assign_band(score: float) -> str:
    """Assign risk band based on score thresholds."""
    if score < 0.30:
        return "LOW"
    if score < 0.55:
        return "MEDIUM"
    if score < 0.75:
        return "HIGH"
    return "REJECT"


def compute_limit_and_rate(requested: float, score: float, base_rate_bps: float = 850) -> tuple:
    """Calculate recommended loan limit and interest rate premium."""
    limit = requested * (1 - score * 0.6)     # max 60% haircut
    rate_bps = base_rate_bps + (score * 400)   # max +400bps premium
    return round(limit, 2), round(rate_bps, 2)


def compute_rejection_reasons(top_factors: list, band: str) -> list:
    """Generate human-readable rejection reasons from top risk factors."""
    if band not in ("HIGH", "REJECT"):
        return []

    reasons = []
    reason_map = {
        "dscr_normalized": "Debt Service Coverage Ratio is below acceptable threshold",
        "leverage_normalized": "Debt-to-Equity ratio indicates excessive leverage",
        "gst_discrepancy_norm": "Significant discrepancy between GSTR-2B and GSTR-3B returns",
        "circular_trade_norm": "Circular trading patterns detected in GST transactions",
        "litigation_norm": "Elevated litigation risk based on active court cases",
        "revenue_growth_normalized": "Revenue growth is declining or negative",
        "ebitda_margin_normalized": "EBITDA margins are below industry benchmarks",
        "news_sentiment_norm": "Negative news sentiment detected for the company/promoters",
    }

    for factor in top_factors[:3]:
        feat = factor.get("feature", "")
        if feat in reason_map:
            reasons.append(reason_map[feat])

    return reasons


def run_shap_analysis(model, feature_vector: dict) -> dict:
    """
    Run SHAP (Global Explainability) on the risk model.
    Returns SHAP values for each feature.
    """
    try:
        import shap

        feature_names = list(feature_vector.keys())
        feature_values = np.array([list(feature_vector.values())])

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(feature_values)

        if isinstance(shap_values, list):
            shap_values = shap_values[0]

        result = {}
        for i, name in enumerate(feature_names):
            result[name] = round(float(shap_values[0][i]), 6)

        return result

    except Exception as e:
        print(f"SHAP_FAIL: {e}")
        return {}


def run_lime_analysis(model, feature_vector: dict) -> dict:
    """
    Run LIME (Local Explainability) to explain this specific prediction.
    """
    try:
        from lime.lime_tabular import LimeTabularExplainer

        feature_names = list(feature_vector.keys())
        feature_values = np.array([list(feature_vector.values())])

        # Create a dummy training set around the current values for LIME
        dummy_train = np.random.normal(
            loc=feature_values, scale=0.1, size=(100, len(feature_names))
        )
        dummy_train = np.clip(dummy_train, 0, 1)

        explainer = LimeTabularExplainer(
            dummy_train,
            feature_names=feature_names,
            mode="regression",
            random_state=42,
        )

        explanation = explainer.explain_instance(
            feature_values[0],
            model.predict if hasattr(model, "predict") else lambda x: np.array([0.5] * len(x)),
            num_features=len(feature_names),
        )

        result = {}
        for feat, weight in explanation.as_list():
            result[feat] = round(weight, 6)

        return result

    except Exception as e:
        print(f"LIME_FAIL: {e}")
        return {}


MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(os.path.dirname(__file__), "models"))


class RiskAgent(AgentBase):
    AGENT_NAME = "risk-agent"
    LISTEN_TOPICS = ["model_selected"]
    OUTPUT_NAMESPACE = "risk"
    OUTPUT_EVENT = "risk_generated"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Full risk scoring pipeline:
        1. Build feature vector from all UCSO namespaces
        2. Normalize features
        3. Compute weighted risk score
        4. Assign band, limit, rate
        5. Run SHAP and LIME explainability
        """
        derived = ucso.get("derived_features", {})
        gst = ucso.get("gst_analysis", {})
        bank = ucso.get("bank_reconciliation", {})
        web = ucso.get("web_intel", {})
        pd_intel = ucso.get("pd_intelligence", {})
        applicant = ucso.get("applicant", {})

        # ── Step 1: Build raw feature vector ──
        raw_features = {
            "dscr": derived.get("dscr", 1.0),
            "icr": derived.get("icr", 2.0),
            "leverage": derived.get("leverage", 1.0),
            "ccc": derived.get("ccc", 60),
            "revenue_growth": derived.get("revenue_growth", 0.0),
            "ebitda_margin": derived.get("ebitda_margin", 0.1),
            "gst_discrepancy": gst.get("gstr2b_vs_3b_discrepancy_pct", 0.0) / 100,
            "circular_trade": gst.get("circular_trade_index", 0.0),
            "litigation_count": len(web.get("litigation_records", [])),
            "news_sentiment": (
                sum(n.get("sentiment_score", 0) for n in web.get("promoter_news", []))
                / max(1, len(web.get("promoter_news", [])))
            ),
        }

        # ── Step 2: Outlier handling + Normalization ──
        for feat in SAFE_BOUNDS:
            if feat in raw_features:
                raw_features[feat] = handle_outlier(feat, raw_features[feat])

        normalized_features = {
            "dscr_normalized": normalize(raw_features["dscr"], "dscr"),
            "leverage_normalized": normalize(raw_features["leverage"], "leverage"),
            "revenue_growth_normalized": normalize(raw_features["revenue_growth"], "revenue_growth"),
            "ebitda_margin_normalized": normalize(raw_features["ebitda_margin"], "ebitda_margin"),
            "gst_discrepancy_norm": normalize(raw_features["gst_discrepancy"], "gst_discrepancy"),
            "circular_trade_norm": normalize(raw_features["circular_trade"], "circular_trade"),
            "litigation_norm": normalize(raw_features["litigation_count"], "litigation_count"),
            "news_sentiment_norm": normalize(raw_features["news_sentiment"], "news_sentiment"),
            "pd_risk_adjustment": pd_intel.get("risk_adjustment", 0.0),
        }

        # ── Step 3: Compute weighted risk score ──
        score = compute_risk_score(normalized_features)
        band = assign_band(score)

        # ── Step 4: Limit and rate calculation ──
        requested = applicant.get("loan_amount_requested", 0)
        limit, rate_bps = compute_limit_and_rate(requested, score)

        # ── Step 5: SHAP + LIME ──
        model_used = ucso.get("risk", {}).get("model_used", "RULE_FALLBACK")
        model = None

        model_files = {
            "LOGISTIC": "logistic_risk_model.pkl",
            "XGBOOST": "xgboost_risk_model.pkl",
            "LGBM": "lgbm_risk_model.pkl",
        }

        if model_used in model_files:
            model_path = os.path.join(MODEL_DIR, model_files[model_used])
            if os.path.exists(model_path):
                try:
                    with open(model_path, "rb") as f:
                        model = pickle.load(f)
                except Exception:
                    pass

        shap_values = run_shap_analysis(model, normalized_features) if model else {}
        lime_explanation = run_lime_analysis(model, normalized_features) if model else {}

        # ── Step 6: Top risk factors ──
        if shap_values:
            sorted_shap = sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)
            top_risk_factors = [
                {"feature": k, "shap_value": v, "weight": WEIGHTS.get(k, 0)}
                for k, v in sorted_shap[:5]
            ]
        else:
            # Fallback: sort by weighted contribution
            contributions = [
                (k, normalized_features.get(k, 0) * WEIGHTS.get(k, 0))
                for k in WEIGHTS
            ]
            contributions.sort(key=lambda x: x[1], reverse=True)
            top_risk_factors = [
                {"feature": k, "contribution": round(v, 4), "weight": WEIGHTS.get(k, 0)}
                for k, v in contributions[:5]
            ]

        # Decision
        decision = "APPROVE" if band in ("LOW", "MEDIUM") else ("REVIEW" if band == "HIGH" else "REJECT")

        # Rejection reasons
        rejection_reasons = compute_rejection_reasons(top_risk_factors, band)

        # Corrective actions
        corrective_actions = []
        if band in ("HIGH", "REJECT"):
            if normalized_features.get("dscr_normalized", 0) > 0.5:
                corrective_actions.append("Improve DSCR by reducing debt or increasing cash flows")
            if normalized_features.get("leverage_normalized", 0) > 0.5:
                corrective_actions.append("Reduce leverage by injecting equity or repaying debt")
            if normalized_features.get("gst_discrepancy_norm", 0) > 0.5:
                corrective_actions.append("Resolve ITC discrepancies between GSTR-2B and GSTR-3B")

        return {
            "score": score,
            "band": band,
            "model_used": model_used,
            "model_version": ucso.get("risk", {}).get("model_version", "v1.0"),
            "feature_vector": {**raw_features, **normalized_features},
            "shap_values": shap_values,
            "lime_explanation": lime_explanation,
            "top_risk_factors": top_risk_factors,
            "decision": decision,
            "recommended_limit": limit,
            "recommended_rate_bps": rate_bps,
            "rejection_reasons": rejection_reasons,
            "corrective_actions": corrective_actions,
        }


if __name__ == "__main__":
    agent = RiskAgent()
    agent.run()
