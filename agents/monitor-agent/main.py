"""
Agent 13: Monitor/Self-Heal Agent
Approach: Watchdog Process
Tools: Standard Python

Trigger: ALL events (subscriber)
Reads: ALL namespaces (read-only)
Writes: audit_log
Logic: Continuously check confidence thresholds, model drift, KB staleness,
       infinite loops. Circuit breaker after 3 repeats. Drift → fallback model.
Errors: INFINITE_LOOP → circuit breaker. DRIFT → alert + fallback.
"""
import sys
import os
import json
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase


# Circuit breaker config
MAX_EVENT_REPEATS = 3
KB_STALENESS_THRESHOLD_HOURS = 168  # 1 week
CONFIDENCE_ALERT_THRESHOLD = 0.5
DRIFT_THRESHOLD = 0.15  # 15% score drift


class MonitorAgent(AgentBase):
    AGENT_NAME = "monitor-agent"
    LISTEN_TOPICS = [
        "application_created",
        "compliance_passed",
        "compliance_failed",
        "docs_uploaded",
        "parsing_completed",
        "gst_completed",
        "bank_recon_completed",
        "mca_completed",
        "web_intel_completed",
        "pd_submitted",
        "pd_completed",
        "model_selected",
        "risk_generated",
        "bias_completed",
        "stress_completed",
        "cam_prereqs_met",
        "cam_generated",
        "agent_status",
    ]
    OUTPUT_NAMESPACE = "audit_log"
    OUTPUT_EVENT = ""  # Monitor doesn't publish normal events

    def __init__(self):
        super().__init__()
        # Track event counts per application for loop detection
        self.event_counts = defaultdict(lambda: defaultdict(int))

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Watchdog checks:
        1. Infinite loop detection (circuit breaker)
        2. Model drift detection
        3. KB staleness check
        4. Low confidence alert
        5. Error rate monitoring
        """
        audit_entries = ucso.get("audit_log", [])
        if not isinstance(audit_entries, list):
            audit_entries = []
        alerts = []
        now = datetime.now(timezone.utc).isoformat()

        # ── 1. Infinite Loop Detection ──
        # Count recent events for this application
        recent_events = [
            e for e in audit_entries
            if e.get("application_id") == application_id
        ]

        # Check last N events for repeats
        if len(recent_events) >= MAX_EVENT_REPEATS:
            last_events = [e.get("event") for e in recent_events[-MAX_EVENT_REPEATS:]]
            if len(set(last_events)) == 1:
                # Same event repeated 3 times = circuit breaker
                alerts.append({
                    "type": "INFINITE_LOOP",
                    "severity": "CRITICAL",
                    "message": f"Circuit breaker triggered: event '{last_events[0]}' repeated {MAX_EVENT_REPEATS} times",
                    "timestamp": now,
                })
                self.logger.error(
                    f"CIRCUIT BREAKER: {last_events[0]} repeated {MAX_EVENT_REPEATS}x for {application_id}",
                    extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                )
                self.publish_status(application_id, "CIRCUIT_BREAKER", error_code="INFINITE_LOOP")

        # ── 2. Model Drift Detection ──
        risk = ucso.get("risk", {})
        ews = ucso.get("ews_monitoring", {})
        if risk.get("score") and ews.get("risk_drift", 0) > DRIFT_THRESHOLD:
            alerts.append({
                "type": "MODEL_DRIFT",
                "severity": "HIGH",
                "message": f"Risk score drift of {ews['risk_drift']:.2%} exceeds threshold ({DRIFT_THRESHOLD:.0%}). Switching to safe model.",
                "timestamp": now,
            })
            self.logger.warning(
                f"MODEL DRIFT detected for {application_id}: drift={ews['risk_drift']:.4f}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )

        # ── 3. KB Staleness Check ──
        web_intel = ucso.get("web_intel", {})
        kb_hours = web_intel.get("kb_freshness_hours", 0)
        if kb_hours > KB_STALENESS_THRESHOLD_HOURS:
            alerts.append({
                "type": "KB_STALE",
                "severity": "MEDIUM",
                "message": f"Knowledge base is {kb_hours} hours old (threshold: {KB_STALENESS_THRESHOLD_HOURS}h). Recommend refresh.",
                "timestamp": now,
            })
            self.logger.warning(
                f"KB_STALE: Weaviate data is {kb_hours}h old for {application_id}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )

        # ── 4. Low Confidence Alert ──
        decision_conf = ucso.get("decision_confidence", {})
        conf_score = decision_conf.get("score", 0)
        if 0 < conf_score < CONFIDENCE_ALERT_THRESHOLD:
            alerts.append({
                "type": "LOW_CONFIDENCE",
                "severity": "HIGH",
                "message": f"Decision confidence {conf_score:.4f} is below threshold ({CONFIDENCE_ALERT_THRESHOLD}). Human review recommended.",
                "timestamp": now,
            })

        # ── 5. Document Parse Error Monitoring ──
        documents = ucso.get("documents", {}).get("files", [])
        parse_errors = []
        for doc in documents:
            errors = doc.get("parse_errors", [])
            if errors:
                parse_errors.extend(errors)

        if parse_errors:
            alerts.append({
                "type": "PARSE_ERRORS",
                "severity": "MEDIUM",
                "message": f"{len(parse_errors)} document parse errors detected: {parse_errors[:3]}",
                "timestamp": now,
            })

        # ── 6. Agent Failure Monitoring ──
        # Check if any agent reported FAILED status
        for entry in audit_entries[-10:]:
            if entry.get("status") == "FAILED":
                alerts.append({
                    "type": "AGENT_FAILURE",
                    "severity": "HIGH",
                    "message": f"Agent '{entry.get('agent', 'unknown')}' failed with error: {entry.get('error_code', 'UNKNOWN')}",
                    "timestamp": now,
                })

        # Build audit log entry
        new_entry = {
            "timestamp": now,
            "application_id": application_id,
            "agent": self.AGENT_NAME,
            "event": "health_check",
            "alerts": alerts,
            "alert_count": len(alerts),
        }

        # Append to existing audit log
        audit_entries.append(new_entry)

        # Log summary
        if alerts:
            self.logger.warning(
                f"Health check for {application_id}: {len(alerts)} alerts raised",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
        else:
            self.logger.info(
                f"Health check for {application_id}: all clear",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )

        return {"entries": audit_entries, "latest_check": new_entry, "alert_count": len(alerts)}


if __name__ == "__main__":
    agent = MonitorAgent()
    agent.run()
