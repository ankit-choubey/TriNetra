"""
Agent 14: PAN Verification Agent
Approach: REST API Consumption
Tools: requests
APIs: Surepass PAN Comprehensive Plus API

Trigger: application_created
Reads: applicant.pan
Writes: pan_intelligence
Errors: PAN_FETCH_FAIL
"""
import sys
import os
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase

import requests

from duckduckgo_search import DDGS
from bs4 import BeautifulSoup

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-70b-8192")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

PAN_EXTRACTION_PROMPT = """You are a verification officer. 
Given the following web search snippets for a PAN number, extract the person's full name, category (Individual/Company), and any other available details.

RESPOND ONLY with valid JSON in this exact format:
{
  "full_name": "NAME",
  "category": "Individual/Company/Firm",
  "pan_status": "VALID",
  "aadhaar_linked": true/false,
  "father_name": "NAME",
  "dob": "YYYY-MM-DD",
  "gender": "M/F",
  "address": "FULL ADDRESS",
  "confidence": 0.0
}
If data is missing, use null or empty strings. If the search results look irrelevant, set confidence to 0.
"""

def search_pan_public_data(pan: str) -> str:
    """Search for PAN info on public directories."""
    try:
        with DDGS() as ddgs:
            # Search for PAN profile or GST results which often link PAN
            query = f"PAN card {pan} profile OR site:zaubacorp.com {pan} OR site:gst.gov.in {pan}"
            results = ddgs.text(query, max_results=5)
            snippets = [r.get("body", "") for r in results]
            return "\n---\n".join(snippets)
    except Exception as e:
        print(f"SEARCH_FAIL: {e}")
        return ""

def extract_pan_info_with_llm(pan: str, snippets: str) -> dict:
    """Use Groq to extract structured info from search snippets."""
    if not GROQ_API_KEY or not snippets.strip():
        # Algorithmic fallback for PAN category (4th letter)
        category_code = pan[3].upper() if len(pan) >= 4 else ""
        categories = {"P": "Individual", "C": "Company", "H": "HUF", "F": "Firm", "A": "AOP", "T": "Trust"}
        return {
            "full_name": "Scraping Unavailable",
            "category": categories.get(category_code, "Unknown"),
            "pan_status": "VALID_FORMAT",
            "aadhaar_linked": False,
            "confidence": 0.1
        }

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": PAN_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Search snippets for PAN {pan}:\n\n{snippets}"},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"GROQ_PAN_FAIL: {e}")
        return {"full_name": "Extraction Failed", "confidence": 0.0}

class PanVerificationAgent(AgentBase):
    AGENT_NAME = "pan-verification-agent"
    LISTEN_TOPICS = ["application_created"]
    OUTPUT_NAMESPACE = "pan_intelligence"
    OUTPUT_EVENT = "pan_verified"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Query Public Data via RAG for PAN Verification (Option 2: Free).
        """
        applicant = ucso.get("applicant", {})
        pan = applicant.get("pan", "")

        if not pan:
            self.logger.warning(f"No PAN provided for {application_id}")
            return {
                "status": "FAIL",
                "full_name": "",
                "pan_status": "MISSING",
                "aadhaar_linked": False,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

        try:
            self.logger.info(
                f"Performing Web Scraping RAG for PAN={pan}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )

            # Step 1: Search
            snippets = search_pan_public_data(pan)
            
            # Step 2: Extract
            extracted = extract_pan_info_with_llm(pan, snippets)

            self.logger.info(
                f"PAN RAG complete: name={extracted.get('full_name')}, confidence={extracted.get('confidence')}",
                extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
            )

            return {
                "status": "PASS" if extracted.get("confidence", 0) > 0.5 else "WARNING",
                "full_name": extracted.get("full_name", ""),
                "father_name": extracted.get("father_name", ""),
                "pan_number": pan,
                "pan_status": extracted.get("pan_status", "VALID"),
                "category": extracted.get("category", ""),
                "dob": extracted.get("dob", ""),
                "gender": extracted.get("gender", ""),
                "email": extracted.get("email", ""),
                "phone_number": extracted.get("phone_number", ""),
                "masked_aadhaar": extracted.get("masked_aadhaar", ""),
                "aadhaar_linked": extracted.get("aadhaar_linked", False),
                "address": extracted.get("address", ""),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "extraction_method": "WEB_RAG"
            }

        except Exception as e:
            self.logger.warning(f"PAN RAG failed ({e}), using format fallback")
            return {
                "status": "WARNING",
                "full_name": "UNKNOWN",
                "pan_status": "FORMAT_ONLY",
                "aadhaar_linked": False,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

if __name__ == "__main__":
    agent = PanVerificationAgent()
    agent.run()
