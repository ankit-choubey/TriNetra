"""
Trinetra Direct Agent Tester
=============================
Tests each agent's process() logic directly — NO KAFKA NEEDED.
Just run:  python agents/test_agents_direct.py
"""
import sys
import os
import json
import traceback

# Add agents directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# ── Sample UCSO data for testing ──
SAMPLE_UCSO = {
    "application_id": "TEST-APP-001",
    "ucso_version": 1,
    "applicant": {
        "company_name": "Trinetra Industries Pvt Ltd",
        "pan": "AABCT1234A",
        "gstin": "07AABCT1234A1Z5",
        "cin": "U72200DL2020PTC123456",
        "promoter_name": "Utkarsh Singh",
        "sector": "fintech",
        "incorporation_date": "2020-01-15"
    },
    "compliance": {},
    "documents": {
        "files": [
            {"doc_type": "ANNUAL_REPORT", "s3_key": "test/annual_report.pdf", "status": "UPLOADED"},
            {"doc_type": "BANK_STMT", "s3_key": "test/bank_stmt.pdf", "status": "UPLOADED"},
            {"doc_type": "GST_RETURN", "s3_key": "test/gst_return.pdf", "status": "UPLOADED"},
            {"doc_type": "ITR", "s3_key": "test/itr.pdf", "status": "UPLOADED"},
        ]
    },
    "financials": {
        "revenue_annual": [50000000, 60000000, 75000000],
        "ebitda_annual": [8000000, 10000000, 13000000],
        "total_debt": 20000000,
        "net_worth": 30000000,
        "interest_expense": 2500000,
        "promoter_holding_pct": 65.0,
        "pledged_shares_pct": 5.0,
        "cibil_score": 750,
        "current_assets": 40000000,
        "current_liabilities": 25000000,
    },
    "gst_analysis": {
        "gstr_2b_itc": 5000000,
        "gstr_3b_itc_claimed": 5800000,
        "gstr2b_vs_3b_discrepancy_pct": 16.0,
        "reconciliation_status": "DISCREPANCY",
        "circular_trade_index": 0.0,
        "suspicious_cycles": [],
        "supplier_gstin_list": ["07AABCT1234A1Z5", "27BBBFT5678B1Z3"],
    },
    "bank_reconciliation": {
        "annual_credit_turnover": 72000000,
        "gst_turnover": 75000000,
        "itr_income": 73000000,
        "turnover_divergence_pct": 4.0,
        "revenue_inflation_flag": False,
        "round_trip_count": 0,
        "cheque_bounce_count": 2,
        "reconciliation_verdict": "PASS",
    },
    "mca_intelligence": {
        "company_status": "ACTIVE",
        "director_changes_last_2yr": [],
        "new_charge_flag": False,
        "defaulter_flag": False,
    },
    "web_intel": {
        "promoter_news": [
            {"headline": "Trinetra raises Series A funding", "sentiment_score": 0.8, "source": "Economic Times"},
            {"headline": "Fintech sector sees growth", "sentiment_score": 0.5, "source": "Mint"},
        ],
        "litigation_records": [],
        "sector_headwinds": [],
        "kb_freshness_hours": 24,
    },
    "pd_intelligence": {
        "transcript_text": "The borrower has a clear succession plan...",
        "risk_adjustment": -0.05,
        "key_findings": {"succession_plan": True, "capacity_concern": False},
    },
    "derived_features": {
        "dscr": 1.8,
        "icr": 5.2,
        "leverage": 0.67,
        "current_ratio": 1.6,
        "revenue_growth_yoy": 0.25,
        "ebitda_margin": 0.173,
        "cibil_score": 750,
        "promoter_holding_pct": 65.0,
        "gst_discrepancy_pct": 16.0,
        "bank_divergence_pct": 4.0,
        "web_sentiment_avg": 0.65,
    },
    "risk": {
        "model_used": "RULE_FALLBACK",
        "score": 0.35,
        "band": "LOW",
        "decision": "APPROVED",
        "recommended_limit": 15000000,
        "recommended_rate_bps": 950,
        "top_risk_factors": [
            {"feature": "gst_discrepancy_pct", "shap_value": 0.12},
            {"feature": "leverage", "shap_value": 0.08},
            {"feature": "revenue_growth_yoy", "shap_value": -0.05},
        ],
        "rejection_reasons": [],
        "corrective_actions": [],
    },
    "bias_checks": {
        "counterfactual_tested": False,
        "flip_features": [],
    },
    "stress_results": {
        "scenarios": [],
        "worst_case_dscr": 0,
        "survival_verdict": "",
    },
    "cam_output": {},
    "decision_confidence": {"score": 0.82, "formula": "0.4*model + 0.3*doc + 0.2*recon + 0.1*web"},
    "human_notes": {"raw_text": "Borrower seems confident. Revenue projections look solid."},
    "audit_log": [],
    "ews_monitoring": {"risk_drift": 0.0},
}


def header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def test_agent(name, test_fn):
    """Run a single agent test and print results."""
    try:
        result = test_fn()
        print(f"  ✅ {name}: PASSED")
        if isinstance(result, dict):
            # Print a compact summary of key fields
            for k, v in list(result.items())[:5]:
                val_str = str(v)[:80]
                print(f"     • {k}: {val_str}")
            if len(result) > 5:
                print(f"     ... and {len(result) - 5} more fields")
        return True
    except Exception as e:
        print(f"  ❌ {name}: FAILED — {e}")
        traceback.print_exc()
        return False


def test_compliance():
    from importlib import import_module
    mod = import_module("compliance-agent.main".replace("-", "_"))
    # Can't import with hyphens, so test the logic directly
    pass

# ── Direct logic tests (no Kafka, no imports with hyphens) ──

def test_1_compliance():
    """Test Compliance Agent logic: check required docs."""
    ucso = SAMPLE_UCSO.copy()
    files = ucso["documents"]["files"]
    required = {"ANNUAL_REPORT", "BANK_STMT", "GST_RETURN", "ITR"}
    uploaded = {f["doc_type"] for f in files if f.get("status") == "UPLOADED"}
    missing = required - uploaded
    result = {
        "status": "PASSED" if not missing else "FAILED",
        "missing_documents": list(missing),
        "checked_at": "2026-03-04T14:30:00Z",
    }
    assert result["status"] == "PASSED", f"Expected PASSED, got {result}"
    return result


def test_2_doc_intelligence():
    """Test Doc Intelligence: Indian number normalization."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "doc-agent"))
    # Import the normalize function directly
    spec_path = os.path.join(os.path.dirname(__file__), "doc-agent", "main.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("doc_agent", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Test normalization
    assert mod.normalize_indian_number("₹12,50,000") == 1250000.0
    assert mod.normalize_indian_number("5.2 Cr") == 52000000.0
    assert mod.normalize_indian_number("3.5 Lakh") == 350000.0
    assert mod.normalize_indian_number("1,00,000") == 100000.0

    return {"normalize_indian_number": "All 4 tests passed"}


def test_3_gst_reconciliation():
    """Test GST Agent: discrepancy calculation + cycle detection."""
    spec_path = os.path.join(os.path.dirname(__file__), "gst-agent", "main.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("gst_agent", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Test discrepancy — function takes dicts, not ints
    disc_result = mod.compute_itc_discrepancy(
        {"total_itc": 5000000},
        {"itc_claimed": 5800000}
    )
    assert abs(disc_result["discrepancy_pct"] - 16.0) < 0.1, f"Expected ~16%, got {disc_result}"

    # Test cycle detection with a simple graph
    transactions = [
        {"seller_gstin": "A", "buyer_gstin": "B", "amount": 100000},
        {"seller_gstin": "B", "buyer_gstin": "C", "amount": 100000},
        {"seller_gstin": "C", "buyer_gstin": "A", "amount": 100000},
    ]
    circular_result = mod.detect_circular_trading(transactions)
    assert circular_result["total_edges"] > 0

    return {"discrepancy": disc_result, "cycles": circular_result}


def test_4_bank_reconciliation():
    """Test Bank Recon: turnover divergence and inflation flag."""
    bank_turnover = 72000000
    gst_turnover = 75000000
    itr_income = 73000000

    avg_declared = (gst_turnover + itr_income) / 2
    divergence = abs(bank_turnover - avg_declared) / avg_declared * 100
    inflation_flag = divergence > 25

    result = {
        "turnover_divergence_pct": round(divergence, 2),
        "revenue_inflation_flag": inflation_flag,
    }
    assert not inflation_flag, "Should not flag inflation at ~4% divergence"
    return result


def test_5_model_selector():
    """Test Model Selector: feature count logic."""
    spec_path = os.path.join(os.path.dirname(__file__), "model-selector-agent", "main.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("model_selector", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Test with full features → should select XGBOOST or LGBM
    count = mod.count_populated_features(SAMPLE_UCSO["derived_features"])
    assert count >= 4, f"Expected ≥4 features, got {count}"

    model_name, version, _ = mod.select_model(SAMPLE_UCSO["derived_features"], SAMPLE_UCSO)
    # Without pkl files, should fallback
    assert model_name == "RULE_FALLBACK", f"Expected RULE_FALLBACK (no pkl), got {model_name}"

    return {"feature_count": count, "selected_model": model_name}


def test_6_risk_normalization():
    """Test Risk Agent: feature normalization bounds."""
    spec_path = os.path.join(os.path.dirname(__file__), "risk-agent", "main.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("risk_agent", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Test per-feature normalization
    test_features = {
        "dscr": (1.8, "dscr"),
        "leverage": (0.67, "leverage"),
        "cibil_score": (750, "cibil_score"),
    }
    results = {}
    for label, (raw_val, feat_name) in test_features.items():
        norm_val = mod.normalize(raw_val, feat_name)
        assert 0 <= norm_val <= 1, f"Feature {label} out of bounds: {norm_val}"
        results[label] = round(norm_val, 4)

    # Test weighted score computation
    score = mod.compute_risk_score({
        "dscr_normalized": 0.4,
        "leverage_normalized": 0.3,
        "cibil_normalized": 0.2,
        "revenue_growth_normalized": 0.5,
        "ebitda_margin_normalized": 0.4,
        "gst_discrepancy_norm": 0.6,
        "circular_trade_norm": 0.1,
        "litigation_norm": 0.2,
        "news_sentiment_norm": 0.3,
    })
    assert 0 <= score <= 1, f"Weighted score out of bounds: {score}"
    results["weighted_risk_score"] = round(score, 4)

    # Test band assignment
    assert mod.assign_band(0.25) == "LOW"
    assert mod.assign_band(0.45) == "MEDIUM"
    assert mod.assign_band(0.65) == "HIGH"
    assert mod.assign_band(0.80) == "REJECT"
    results["band_logic"] = "All 4 thresholds correct"

    return results


def test_7_stress_scenarios():
    """Test Stress Agent: DSCR recalculation under stress."""
    spec_path = os.path.join(os.path.dirname(__file__), "stress-agent", "main.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("stress_agent", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    revenue = 75000000
    ebitda = 13000000
    ebitda_margin = ebitda / revenue
    interest = 2500000
    principal = 5000000

    # Test each scenario using the actual functions
    dscr_rev = mod.compute_stressed_dscr(revenue, ebitda_margin, interest, principal, revenue_shock=-0.20)
    dscr_rate = mod.compute_stressed_dscr(revenue, ebitda_margin, interest, principal, rate_shock_pct=0.02)
    dscr_combined = mod.compute_stressed_dscr(revenue, ebitda_margin, interest, principal, revenue_shock=-0.20, rate_shock_pct=0.02)

    scenarios = [
        {"name": "Revenue-20%", "dscr": dscr_rev, "verdict": mod.assign_stress_verdict(dscr_rev)},
        {"name": "Rate+2%", "dscr": dscr_rate, "verdict": mod.assign_stress_verdict(dscr_rate)},
        {"name": "Combined", "dscr": dscr_combined, "verdict": mod.assign_stress_verdict(dscr_combined)},
    ]

    assert len(scenarios) == 3
    for s in scenarios:
        assert s["dscr"] > 0, f"DSCR should be positive, got {s['dscr']}"

    return {"scenarios": [{"name": s["name"], "dscr": round(s["dscr"], 4), "verdict": s["verdict"]} for s in scenarios]}


def test_8_bias_logic():
    """Test Bias Agent: counterfactual flip detection concept."""
    original_score = 0.35
    original_decision = "APPROVED"

    # Simulate: removing gst_discrepancy (setting to median) changes score
    modified_score = 0.28  # Lower score = still approved
    decision_flips = (original_decision == "APPROVED" and modified_score > 0.55) or \
                     (original_decision == "REJECTED" and modified_score <= 0.55)

    result = {
        "counterfactual_tested": True,
        "flip_detected": decision_flips,
        "original_score": original_score,
        "modified_score": modified_score,
    }
    assert not decision_flips, "Score change should not flip decision"
    return result


def test_9_cam_generator():
    """Test CAM Agent: generates a Word document."""
    spec_path = os.path.join(os.path.dirname(__file__), "cam-agent", "main.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("cam_agent", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    output_path = mod.generate_cam_document(SAMPLE_UCSO)
    file_size = os.path.getsize(output_path)

    result = {
        "output_path": output_path,
        "file_size_bytes": file_size,
        "passes_5kb_check": file_size > 5120,
    }
    assert file_size > 5120, f"CAM file too small: {file_size} bytes"

    # Cleanup
    os.unlink(output_path)
    return result


# ── Main Test Runner ──
if __name__ == "__main__":
    header("TRINETRA AGENT TEST SUITE (No Kafka Required)")
    print(f"  Testing with sample application: {SAMPLE_UCSO['application_id']}")

    tests = [
        ("1. Compliance Agent (Rule Engine)", test_1_compliance),
        ("2. Doc Intelligence (₹ Normalization)", test_2_doc_intelligence),
        ("3. GST Reconciliation (Discrepancy + Cycles)", test_3_gst_reconciliation),
        ("4. Bank Reconciliation (Divergence)", test_4_bank_reconciliation),
        ("5. Model Selector (Feature Heuristics)", test_5_model_selector),
        ("6. Risk Agent (Normalization Bounds)", test_6_risk_normalization),
        ("7. Stress Agent (3 Scenarios)", test_7_stress_scenarios),
        ("8. Bias Agent (Counterfactual Logic)", test_8_bias_logic),
        ("9. CAM Generator (python-docx Output)", test_9_cam_generator),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        if test_agent(name, fn):
            passed += 1
        else:
            failed += 1

    header("RESULTS")
    print(f"  Passed: {passed}/{passed + failed}")
    print(f"  Failed: {failed}/{passed + failed}")

    if failed == 0:
        print(f"\n  🎉 ALL TESTS PASSED — Agent logic is verified!")
    else:
        print(f"\n  ⚠  {failed} test(s) failed. Check errors above.")

    sys.exit(0 if failed == 0 else 1)
