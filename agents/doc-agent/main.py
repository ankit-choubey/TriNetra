"""
Agent 2: Document Intelligence Agent
Approach: OCR (Optical Character Recognition) + Pattern Matching
Tools: pdfplumber (digital text), pytesseract (scanned), re (Indian number parsing)

Trigger: docs_uploaded, compliance_passed
Reads: documents (S3 keys)
Writes: documents, financials
Errors: PARSE_LOW_CONF (<0.6) → flag for human review. PARSE_FAIL → retry alternate parser.
"""
import sys
import os
import re
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase

import pdfplumber
import pytesseract
from PIL import Image
import requests as http_requests


# ── Indian Number Normalizer ──
def normalize_indian_number(text: str) -> float:
    """
    Convert Indian formatted numbers to float.
    Handles: ₹, commas (lakh/crore style), 'Cr', 'Lakh', etc.

    Examples:
        '₹45,00,000'    -> 4500000.0
        '₹6.5 Cr'       -> 65000000.0
        '28 Lakh'        -> 2800000.0
        '1,23,45,678.90' -> 12345678.90
    """
    if not text:
        return 0.0

    text = text.strip().replace("₹", "").replace(",", "").strip()

    # Handle 'Cr' / 'Crore' multiplier
    cr_match = re.search(r"([\d.]+)\s*(cr|crore)", text, re.IGNORECASE)
    if cr_match:
        return float(cr_match.group(1)) * 1e7

    # Handle 'Lakh' / 'L' multiplier
    lakh_match = re.search(r"([\d.]+)\s*(lakh|lac|l)\b", text, re.IGNORECASE)
    if lakh_match:
        return float(lakh_match.group(1)) * 1e5

    # Plain number
    try:
        return float(text)
    except ValueError:
        return 0.0


# ── Financial Field Extraction Patterns ──
FINANCIAL_PATTERNS = {
    "revenue": [
        r"(?:total\s+)?revenue\s*(?:from\s+operations)?\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
        r"turnover\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
        r"net\s+sales\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "ebitda": [
        r"ebitda\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
        r"operating\s+profit\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "net_profit": [
        r"(?:net\s+)?profit\s+(?:after\s+tax|for\s+the\s+year)\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
        r"pat\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "total_debt": [
        r"total\s+(?:borrowings?|debt)\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
        r"long\s+term\s+borrowings?\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "net_worth": [
        r"net\s+worth\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
        r"shareholders?\s*(?:\'s)?\s+funds?\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "interest_expense": [
        r"(?:interest|finance)\s+(?:expense|cost)\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "taxable_income": [
        r"taxable\s+income\s*[:\-]?\s*([\d₹,.]+\s*(?:cr|crore|lakh|lac)?)",
    ],
    "cibil_score": [
        r"cibil\s*(?:score)?\s*[:\-]?\s*(\d{3})",
        r"credit\s+score\s*[:\-]?\s*(\d{3})",
    ],
}


def extract_text_from_pdf(file_path: str) -> tuple:
    """
    Extract text from a PDF using pdfplumber (digital) with Tesseract OCR fallback.

    Returns:
        (full_text: str, confidence: float, method: str)
    """
    full_text = ""
    confidence = 0.0

    # Try digital extraction first
    try:
        with pdfplumber.open(file_path) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
            full_text = "\n".join(pages_text)

        if len(full_text.strip()) > 100:
            # Good digital extraction
            confidence = 0.95
            return full_text, confidence, "pdfplumber"
    except Exception:
        pass

    # Fallback to OCR (scanned PDFs)
    try:
        with pdfplumber.open(file_path) as pdf:
            pages_text = []
            for page in pdf.pages:
                img = page.to_image(resolution=300).original
                ocr_text = pytesseract.image_to_string(img, lang="eng")
                pages_text.append(ocr_text)
            full_text = "\n".join(pages_text)

        if len(full_text.strip()) > 50:
            confidence = 0.70
            return full_text, confidence, "tesseract"
        else:
            confidence = 0.30
            return full_text, confidence, "tesseract_low"
    except Exception as e:
        return f"PARSE_FAIL: {str(e)}", 0.0, "failed"


def extract_financials(text: str) -> dict:
    """
    Extract financial fields from text using regex patterns.
    Returns a dict of field_name -> normalized float value.
    """
    results = {}
    for field, patterns in FINANCIAL_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_value = match.group(1)
                results[field] = normalize_indian_number(raw_value)
                break
    return results


class DocIntelligenceAgent(AgentBase):
    AGENT_NAME = "doc-intelligence-agent"
    LISTEN_TOPICS = ["docs_uploaded", "compliance_passed"]
    OUTPUT_NAMESPACE = "documents"
    OUTPUT_EVENT = "parsing_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Parse all uploaded PDFs. Extract financials with confidence + provenance.
        Normalize Indian numbers. PATCH documents + financials namespaces.
        """
        documents = ucso.get("documents", {}).get("files", [])
        aggregated_financials = {}
        updated_files = []

        for doc in documents:
            if doc.get("parsed"):
                updated_files.append(doc)
                continue

            # Determine how to get the file
            local_path = doc.get("local_path", "")
            s3_key = doc.get("s3_key", "")
            doc_id = doc.get("doc_id", doc.get("doc_type", "unknown"))

            if not s3_key and not local_path:
                updated_files.append(doc)
                continue

            try:
                tmp_path = None

                if local_path and os.path.exists(local_path):
                    # Local file (for testing)
                    tmp_path = local_path
                else:
                    # Download from backend API
                    file_url = f"{self.ucso_client.base_url}/api/files/{application_id}"
                    self.logger.info(
                        f"Downloading file from {file_url}",
                        extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                    )
                    resp = http_requests.get(file_url, timeout=60)
                    resp.raise_for_status()

                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(resp.content)
                        tmp_path = tmp.name

                # Extract text
                text, confidence, method = extract_text_from_pdf(tmp_path)

                # Extract financial fields
                extracted = extract_financials(text)

                # Update document record
                doc["parsed"] = True
                doc["confidence"] = confidence
                doc["extracted_fields"] = extracted
                doc["provenance"] = {
                    "page": 1,
                    "section": f"Extracted via {method}",
                }
                doc.setdefault("parse_errors", [])

                if confidence < 0.6:
                    doc["parse_errors"].append(
                        f"PARSE_LOW_CONF: confidence={confidence}, method={method}"
                    )
                    self.logger.warning(
                        f"Low confidence ({confidence}) for doc {doc_id}",
                        extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                    )

                # Merge into aggregated financials
                for k, v in extracted.items():
                    if k not in aggregated_financials or v > 0:
                        aggregated_financials[k] = v

                # Clean up temp file (only if we downloaded it)
                if tmp_path != local_path and tmp_path:
                    os.unlink(tmp_path)

                self.logger.info(
                    f"Parsed {doc_id}: {len(extracted)} fields, confidence={confidence:.2f}, method={method}",
                    extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to parse doc {doc_id}: {e}",
                    extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                )
                doc.setdefault("parse_errors", [])
                doc["parse_errors"].append(f"PARSE_FAIL: {str(e)}")

            updated_files.append(doc)

        # PATCH financials namespace separately
        if aggregated_financials:
            financials_patch = {}
            field_map = {
                "revenue": "revenue_annual",
                "ebitda": "ebitda_annual",
                "net_profit": "net_profit_annual",
                "total_debt": "total_debt",
                "net_worth": "net_worth",
                "interest_expense": "interest_expense",
                "taxable_income": "itr_taxable_income",
                "cibil_score": "cibil_score",
            }
            for src, dest in field_map.items():
                if src in aggregated_financials:
                    val = aggregated_financials[src]
                    if dest.endswith("_annual"):
                        financials_patch[dest] = [val]
                    else:
                        financials_patch[dest] = val

            self.ucso_client.patch_namespace(
                application_id, "financials", financials_patch
            )

        return {"files": updated_files}


if __name__ == "__main__":
    agent = DocIntelligenceAgent()
    agent.run()
