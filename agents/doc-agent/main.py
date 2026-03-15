"""
Agent 2: Document Intelligence Agent
Approach: Table-First Extraction + Text Fallback + OCR
Tools: pdfplumber (digital tables + text), pytesseract (scanned PDFs), re (Indian number parsing)

Trigger: docs_uploaded, compliance_passed
Reads: documents (S3 keys)
Writes: documents, financials
Errors: PARSE_LOW_CONF (<0.6) → flag for human review. PARSE_FAIL → retry alternate parser.

Extraction Priority:
  1. pdfplumber.extract_tables() → reads actual table grid rows/columns (handles all Indian annual reports)
  2. pdfplumber.extract_text()   → regex on raw text (fallback for text-inline PDFs)
  3. pytesseract OCR             → final fallback for scanned/image-based PDFs
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
    Handles: ₹, commas (lakh/crore style), 'Cr', 'Lakh', negative brackets (123), etc.
    """
    if not text:
        return 0.0

    text = str(text).strip()

    # Handle bracketed negatives like (1,23,456) → treat as negative but return abs
    is_negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("₹", "").replace(",", "").strip()

    # Handle 'Cr' / 'Crore' multiplier
    cr_match = re.search(r"([\d.]+)\s*(cr|crore)", text, re.IGNORECASE)
    if cr_match:
        val = float(cr_match.group(1)) * 1e7
        return -val if is_negative else val

    # Handle 'Lakh' / 'L' multiplier
    lakh_match = re.search(r"([\d.]+)\s*(lakh|lac|l)\b", text, re.IGNORECASE)
    if lakh_match:
        val = float(lakh_match.group(1)) * 1e5
        return -val if is_negative else val

    # Plain number — strip any trailing non-numeric chars
    num_match = re.search(r"[\d.]+", text)
    if num_match:
        try:
            val = float(num_match.group())
            return -val if is_negative else val
        except ValueError:
            pass

    return 0.0


# ── Financial Field Keyword Map (universal: Indian + IFRS/International) ──
# Maps known synonyms from both Indian annual reports (₹) and IFRS reports (KRW/USD/GBP etc.)
FIELD_KEYWORDS = {
    "revenue": [
        # Indian formats
        "total revenue from operations", "revenue from operations",
        "net revenue", "net sales", "total turnover", "turnover",
        "total income", "gross revenue", "total net sales",
        # IFRS / International formats
        "revenue", "net revenues", "total revenues",
        "sales revenue", "sales and other revenues",
    ],
    "ebitda": [
        # Indian
        "ebitda", "operating profit", "profit before depreciation",
        "pbdit", "earnings before interest",
        # IFRS
        "operating income", "income from operations",
        "profit/(loss) from operations",
    ],
    "net_profit": [
        # Indian
        "profit after tax", "net profit", "profit for the year", "pat",
        "profit/(loss) after tax",
        # IFRS
        "profit for the period", "net income", "net earnings",
        "profit attributable to owners", "net profit for the period",
        "profit for the period attributable",
    ],
    "total_debt": [
        # Indian
        "total borrowings", "total debt", "long term borrowings",
        "long-term borrowings", "secured loans", "unsecured loans",
        # IFRS
        "total liabilities", "total financial liabilities",
        "bonds and borrowings", "borrowings", "long-term debt",
        "total interest-bearing debt",
    ],
    "net_worth": [
        # Indian
        "net worth", "shareholders funds", "total equity",
        "share capital and reserves", "equity share capital",
        # IFRS
        "total shareholders equity", "shareholders equity",
        "equity attributable to owners", "total equity and reserves",
        "total stockholders equity",
    ],
    "interest_expense": [
        # Indian
        "finance costs", "interest expense", "finance charges",
        "interest & finance charges", "borrowing costs",
        # IFRS
        "financial expense", "interest costs", "interest paid",
        "net finance costs", "net interest expense",
    ],
    "taxable_income": [
        "taxable income", "income chargeable to tax", "gross total income",
        "profit before income tax", "profit before tax", "income before taxes",
    ],
    "cibil_score": [
        "cibil score", "credit score", "bureau score",
    ],
}

# Minimum number of digits to be considered a real financial figure (not a note reference)
# e.g. "Revenue 26 71,915,601" — skip '26' (note ref), pick '71915601'
MIN_FINANCIAL_DIGITS = 4  # Must have at least 4 digits (i.e. ≥1000)


def _extract_large_numbers_from_line(line: str) -> list:
    """
    Extract all financial numbers from a text line, sorted by magnitude (largest first).
    Filters out small inline note reference numbers (e.g. '26' in 'Revenue 26 71,915,601').
    Handles: comma-separated (Indian/international), plain floats, bracketed negatives.
    """
    # Match all number-like tokens: optional (, digits+commas+dots, optional )
    # This handles: 71,915,601  /  (37,000)  /  3,861,524  /  37.19  etc.
    raw_numbers = re.findall(r'\(?[\d][\d,]*(?:\.[\d]+)?\)?', line)
    parsed = []
    for raw in raw_numbers:
        is_neg = raw.startswith('(') and raw.endswith(')')
        cleaned = raw.strip('()').replace(',', '')
        try:
            val = float(cleaned)
            # Must have at least MIN_FINANCIAL_DIGITS digits before decimal
            integer_part = cleaned.split('.')[0]
            if len(integer_part) >= MIN_FINANCIAL_DIGITS:
                parsed.append((-val if is_neg else val))
        except ValueError:
            continue
    # Sort by absolute magnitude, largest first (most likely the real financial figure)
    parsed.sort(key=abs, reverse=True)
    return parsed


def _match_line_to_field(line: str) -> str | None:
    """Match a text line to a financial field using keyword synonyms."""
    line_lower = line.lower().strip()
    for field, keywords in FIELD_KEYWORDS.items():
        for kw in keywords:
            # Check if keyword appears at the start of the line or after whitespace
            # Use word-boundary style check to avoid "total revenue" matching "total revenues growth"
            if re.search(r'(?:^|\s)' + re.escape(kw) + r'(?:\s|$|[^a-z])', line_lower):
                return field
    return None


def extract_from_tables(file_path: str) -> tuple:
    """
    PRIMARY extraction method: Read tables from PDF using pdfplumber.extract_tables().
    Works for grid-based PDFs (Indian annual reports with visible table borders).

    Returns:
        (financials: dict, fields_found: int, confidence: float, method: str)
    """
    results = {}
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    for row in table:
                        if not row or len(row) < 2:
                            continue
                        label = str(row[0] or "").strip().lower()
                        field = None
                        for f, keywords in FIELD_KEYWORDS.items():
                            for kw in keywords:
                                if kw in label:
                                    field = f
                                    break
                            if field:
                                break

                        if not field or field in results:
                            continue

                        # Get numbers from all cells in the row, pick the largest
                        all_nums = []
                        for cell in row[1:]:
                            cell_str = str(cell or "").strip()
                            nums = _extract_large_numbers_from_line(cell_str)
                            all_nums.extend(nums)

                        if all_nums:
                            all_nums.sort(key=abs, reverse=True)
                            results[field] = all_nums[0]

        if results:
            return results, len(results), 0.95, "pdfplumber_tables"
    except Exception:
        pass

    return {}, 0, 0.0, "tables_failed"


def extract_from_text(file_path: str) -> tuple:
    """
    SECONDARY extraction method: Extract raw text + regex.
    Fallback for PDFs that don't have visible grid-line tables
    (e.g. text-only PDFs, annual reports with no borders).

    Returns:
        (full_text: str, confidence: float, method: str)
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
            full_text = "\n".join(pages_text)

        if len(full_text.strip()) > 100:
            return full_text, 0.80, "pdfplumber_text"
    except Exception:
        pass

    return "", 0.0, "text_failed"


def extract_from_ocr(file_path: str) -> tuple:
    """
    FINAL FALLBACK: Tesseract OCR for scanned/image-based PDFs.

    Returns:
        (full_text: str, confidence: float, method: str)
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            pages_text = []
            for page in pdf.pages:
                img = page.to_image(resolution=300).original
                ocr_text = pytesseract.image_to_string(img, lang="eng")
                pages_text.append(ocr_text)
            full_text = "\n".join(pages_text)

        if len(full_text.strip()) > 50:
            return full_text, 0.70, "tesseract"
        return full_text, 0.30, "tesseract_low"
    except Exception as e:
        return f"PARSE_FAIL: {str(e)}", 0.0, "failed"


def extract_financials_from_text(text: str) -> dict:
    """
    Smart line-level financial extraction.
    Handles BOTH:
      - Indian Rupee statements (₹ lakh/crore inline)
      - IFRS/International statements (KRW millions / USD thousands, multi-column)
    Key insight: uses _extract_large_numbers_from_line() which skips small
    inline note-reference numbers like '26' in 'Revenue 26 71,915,601 ...'.
    """
    results = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        field = _match_line_to_field(line)
        if not field or field in results:
            continue

        # Indian ₹ formatted values (e.g. '₹6.5 Cr', '28 Lakh')
        cr_match = re.search(r'([\d,. ]+(?:cr|crore))', line, re.IGNORECASE)
        if cr_match:
            val = normalize_indian_number(cr_match.group(0))
            if val > 0:
                results[field] = val
                continue

        lakh_match = re.search(r'([\d,. ]+(?:lakh|lac))\b', line, re.IGNORECASE)
        if lakh_match:
            val = normalize_indian_number(lakh_match.group(0))
            if val > 0:
                results[field] = val
                continue

        # IFRS/general: extract all large numbers, pick the first (most recent year)
        nums = _extract_large_numbers_from_line(line)
        if nums:
            results[field] = nums[0]  # Largest number = most significant financial figure

    return results


def extract_text_from_pdf(file_path: str) -> tuple:
    """
    COMBINED extraction pipeline:
    1. Try table extraction (best for financial statements with grids)
    2. Try raw text + regex (for inline-text PDFs)
    3. Try OCR (for scanned PDFs)

    Returns:
        (full_text: str, confidence: float, method: str)
    """
    # Stage 1: Table-based extraction
    table_results, fields_found, confidence, method = extract_from_tables(file_path)
    if fields_found > 0:
        # Return a special marker so extract_financials knows to use the table data
        return f"__TABLE_RESULTS__:{fields_found}", confidence, method

    # Store table_results for later even if zero fields — still try text
    # Stage 2: Text + regex fallback
    text, text_confidence, text_method = extract_from_text(file_path)
    if text_confidence > 0.5:
        return text, text_confidence, text_method

    # Stage 3: OCR fallback
    text, ocr_confidence, ocr_method = extract_from_ocr(file_path)
    return text, ocr_confidence, ocr_method


# ── Module-level cache for table results (avoids double-parsing) ──
_TABLE_CACHE: dict = {}


def extract_financials_from_pdf(file_path: str) -> tuple:
    """
    Top-level function: runs the full 3-stage extraction pipeline and returns
    (financials_dict, field_count, confidence, method).
    Used directly by DocIntelligenceAgent.process().
    """
    # Stage 1: table extraction
    table_results, fields_found, confidence, method = extract_from_tables(file_path)
    if fields_found > 0:
        return table_results, fields_found, confidence, method

    # Stage 2: text + regex
    text, text_conf, text_method = extract_from_text(file_path)
    if text_conf > 0.5:
        results = extract_financials_from_text(text)
        if results:
            return results, len(results), text_conf, text_method

    # Stage 3: OCR + regex
    text, ocr_conf, ocr_method = extract_from_ocr(file_path)
    results = extract_financials_from_text(text)
    return results, len(results), ocr_conf, ocr_method


def extract_financials(text: str) -> dict:
    """
    Legacy wrapper kept for backward compatibility.
    Extracts financials from a text string using regex.
    """
    return extract_financials_from_text(text)


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

                # Run full 3-stage extraction: tables → text+regex → OCR
                # Returns (financials_dict, field_count, confidence, method)
                extracted, fields_found, confidence, method = extract_financials_from_pdf(tmp_path)

                # Update document record
                doc["parsed"] = True
                doc["confidence"] = confidence
                doc["extracted_fields"] = extracted
                doc["provenance"] = {
                    "page": 1,
                    "section": f"Extracted via {method} ({fields_found} fields found)",
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

                # Merge into aggregated financials (prefer non-zero values)
                for k, v in extracted.items():
                    if v != 0.0 and (k not in aggregated_financials or aggregated_financials[k] == 0.0):
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