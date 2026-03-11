"""
Agent 6: MCA Intelligence Agent
Approach: REST API Consumption
Tools: requests
APIs: Surepass MCA API (Primary), Weaviate fallback

Trigger: parsing_completed
Reads: applicant.cin, applicant.pan
Writes: mca_intelligence
Errors: MCA_FETCH_FAIL → use Weaviate MCAFiling collection snapshot.
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase

import requests as http_requests

SUREPASS_TOKEN = os.getenv("SUREPASS_TOKEN", "")
SUREPASS_MCA_URL = "https://kyc-api.surepass.io/api/v1/company-details/mca-basic"
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate:8080")


def extract_director_changes(data: dict) -> list:
    """
    Extract director changes in the last 2 years from MCA data.
    """
    directors = data.get("directors", [])
    cutoff = datetime.now() - timedelta(days=730)  # 2 years
    changes = []

    for d in directors:
        date_str = d.get("date", "")
        if not date_str:
            continue
        try:
            change_date = datetime.strptime(date_str, "%Y-%m-%d")
            if change_date > cutoff:
                changes.append({
                    "din": d.get("din", ""),
                    "name": d.get("name", ""),
                    "change_type": d.get("change_type", "APPOINTMENT"),
                    "date": date_str,
                })
        except ValueError:
            continue

    return changes


def has_new_charge(data: dict) -> bool:
    """Check if any new charges were registered in the last 6 months."""
    charges = data.get("charges", [])
    cutoff = datetime.now() - timedelta(days=180)

    for charge in charges:
        date_str = charge.get("creation_date", "")
        if not date_str:
            continue
        try:
            charge_date = datetime.strptime(date_str, "%Y-%m-%d")
            if charge_date > cutoff:
                return True
        except ValueError:
            continue

    return False


def fetch_from_surepass(cin: str) -> dict:
    """
    Primary: Call Surepass MCA API with CIN.
    Returns structured MCA intelligence data.
    """
    if not SUREPASS_TOKEN:
        raise ConnectionError("SUREPASS_TOKEN not configured")

    resp = http_requests.post(
        SUREPASS_MCA_URL,
        json={"id_number": cin},
        headers={"Authorization": f"Bearer {SUREPASS_TOKEN}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})

    return {
        "company_status": data.get("company_status", "UNKNOWN"),
        "director_changes_last_2yr": extract_director_changes(data),
        "charges_registered": data.get("charges", []),
        "new_charge_flag": has_new_charge(data),
        "director_din_list": [
            d.get("din", "") for d in data.get("directors", [])
        ],
        "last_agm_date": data.get("last_agm_date", ""),
        "defaulter_flag": data.get("in_defaulter_list", False),
    }


def fetch_from_weaviate_fallback(company_name: str) -> dict:
    """
    Fallback: Query Weaviate MCAFiling collection for pre-seeded data.
    """
    try:
        query = {
            "query": f"""{{
                Get {{
                    MCAFiling(
                        nearText: {{concepts: ["{company_name}"]}}
                        limit: 5
                    ) {{
                        cin
                        company_name
                        filing_type
                        filing_date
                        description
                        risk_flag
                        _additional {{ certainty }}
                    }}
                }}
            }}"""
        }
        resp = http_requests.post(
            f"{WEAVIATE_URL}/v1/graphql", json=query, timeout=10
        )
        resp.raise_for_status()
        hits = resp.json().get("data", {}).get("Get", {}).get("MCAFiling", [])

        if not hits:
            return {
                "company_status": "UNKNOWN",
                "director_changes_last_2yr": [],
                "charges_registered": [],
                "new_charge_flag": False,
                "director_din_list": [],
                "last_agm_date": "",
                "defaulter_flag": False,
            }

        # Parse Weaviate results into MCA format
        risk_flags = [h for h in hits if h.get("risk_flag")]
        return {
            "company_status": "ACTIVE" if not risk_flags else "FLAGGED",
            "director_changes_last_2yr": [],
            "charges_registered": [
                {"description": h.get("description", ""), "filing_date": h.get("filing_date", "")}
                for h in hits if h.get("filing_type") == "CHARGE"
            ],
            "new_charge_flag": any(h.get("filing_type") == "CHARGE" for h in hits),
            "director_din_list": [],
            "last_agm_date": "",
            "defaulter_flag": any(h.get("risk_flag") for h in hits),
        }

    except Exception:
        return {
            "company_status": "UNKNOWN",
            "director_changes_last_2yr": [],
            "charges_registered": [],
            "new_charge_flag": False,
            "director_din_list": [],
            "last_agm_date": "",
            "defaulter_flag": False,
        }


class MCAIntelligenceAgent(AgentBase):
    AGENT_NAME = "mca-intelligence-agent"
    LISTEN_TOPICS = ["parsing_completed"]
    OUTPUT_NAMESPACE = "mca_intelligence"
    OUTPUT_EVENT = "mca_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Query MCA for company status, director changes, charges.
        Primary: Surepass API. Fallback: Weaviate MCAFiling snapshot.
        """
        applicant = ucso.get("applicant", {})
        cin = applicant.get("cin", "")
        company_name = applicant.get("company_name", "")

        if not cin and not company_name:
            self.logger.warning(
                f"No CIN or company name for {application_id}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
            return {
                "company_status": "UNKNOWN",
                "director_changes_last_2yr": [],
                "charges_registered": [],
                "new_charge_flag": False,
                "director_din_list": [],
                "last_agm_date": "",
                "defaulter_flag": False,
            }

        # Try Weaviate first (Option 1: Free)
        try:
            self.logger.info(
                f"Fetching MCA data from Weaviate for company: {company_name}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
            return fetch_from_weaviate_fallback(company_name)

        except Exception as e:
            self.logger.warning(
                f"Weaviate MCA query failed ({e}), falling back to Surepass if configured",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )
            # Fallback to Surepass only if Weaviate fails and token is present
            if cin and SUREPASS_TOKEN:
                try:
                    return fetch_from_surepass(cin)
                except Exception as ex:
                    self.logger.error(f"Surepass fallback also failed: {ex}")
            
            return {
                "company_status": "UNKNOWN",
                "director_changes_last_2yr": [],
                "charges_registered": [],
                "new_charge_flag": False,
                "director_din_list": [],
                "last_agm_date": "",
                "defaulter_flag": False,
            }


if __name__ == "__main__":
    agent = MCAIntelligenceAgent()
    agent.run()
