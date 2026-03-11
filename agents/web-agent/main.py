"""
Agent 7: Web Intelligence Agent
Approach: True RAG (Retrieval-Augmented Generation) & NLP Sentiment
Tools: weaviate-client, sentence-transformers (all-MiniLM-L6-v2), vaderSentiment

Trigger: gst_completed, bank_recon_completed
Reads: applicant, gst_analysis
Writes: web_intel
Logic: Query Weaviate KB for news/litigation. Score with VADER sentiment.
       Surepass eCourt API for litigation. Credibility filter ≥2.
Errors: SCRAPE_TIMEOUT → use KB snapshot. LOW_CONFIDENCE (<0.75 cosine) → discard.
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase

import requests as http_requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate:8080")
SUREPASS_TOKEN = os.getenv("SUREPASS_TOKEN", "")
SUREPASS_ECOURT_URL = "https://kyc-api.surepass.io/api/v1/ecourt/cnr-details"
SIMILARITY_THRESHOLD = 0.75

analyzer = SentimentIntensityAnalyzer()


# ── Sentiment Scoring (from Blueprint Section 2.4) ──
def score_article(headline: str, body: str = "") -> dict:
    """
    Score a news article using VADER sentiment analysis.
    Returns sentiment_score, risk_contribution, and label.
    """
    text = f"{headline}. {body}"
    scores = analyzer.polarity_scores(text)
    compound = scores["compound"]  # -1.0 to +1.0

    # Normalize to risk contribution (0=no risk, 1=max risk)
    risk_contribution = (1 - compound) / 2  # maps [-1,1] → [1,0]

    return {
        "sentiment_score": round(compound, 4),
        "risk_contribution": round(risk_contribution, 4),
        "label": (
            "POSITIVE" if compound > 0.05
            else "NEGATIVE" if compound < -0.05
            else "NEUTRAL"
        ),
    }


def aggregate_news_sentiment(articles: list) -> float:
    """Aggregate risk contribution across all scored articles."""
    if not articles:
        return 0.5  # neutral default
    return round(
        sum(a.get("risk_contribution", 0.5) for a in articles) / len(articles), 4
    )


# ── Weaviate RAG Queries ──
def query_weaviate_collection(
    collection: str, query_text: str, company_name: str, fields: list
) -> list:
    """
    Query Weaviate using near_text semantic search.
    Discards results below cosine similarity threshold (0.75).
    """
    field_str = " ".join(fields)
    query = {
        "query": f"""{{
            Get {{
                {collection}(
                    nearText: {{concepts: ["{query_text}", "{company_name}"]}}
                    where: {{
                        path: ["credibility_score"]
                        operator: GreaterThan
                        valueNumber: 2
                    }}
                    limit: 10
                ) {{
                    {field_str}
                    _additional {{ certainty }}
                }}
            }}
        }}"""
    }

    try:
        resp = http_requests.post(
            f"{WEAVIATE_URL}/v1/graphql", json=query, timeout=10
        )
        resp.raise_for_status()
        hits = resp.json().get("data", {}).get("Get", {}).get(collection, [])

        # Filter by similarity threshold
        return [
            h for h in hits
            if h.get("_additional", {}).get("certainty", 0) >= SIMILARITY_THRESHOLD
        ]
    except Exception:
        return []


def fetch_news(company_name: str, industry: str) -> list:
    """
    Fetch and score news articles from Weaviate NewsArticle collection.
    """
    hits = query_weaviate_collection(
        "NewsArticle",
        f"{company_name} {industry} risk",
        company_name,
        ["headline", "body", "source_url", "credibility_score", "published_at", "entity_tags"],
    )

    scored_news = []
    for hit in hits:
        sentiment = score_article(
            hit.get("headline", ""), hit.get("body", "")
        )
        scored_news.append({
            "headline": hit.get("headline", ""),
            "source_url": hit.get("source_url", ""),
            "credibility_score": hit.get("credibility_score", 0),
            "sentiment_score": sentiment["sentiment_score"],
            "risk_contribution": sentiment["risk_contribution"],
            "published_at": hit.get("published_at", ""),
            "entity_tags": hit.get("entity_tags", []),
        })

    return scored_news


def fetch_litigation(company_name: str, pan: str) -> list:
    """
    Fetch litigation records via Surepass eCourt API.
    Falls back to Weaviate LitigationRecord collection.
    """
    records = []

    # Try Surepass eCourt API
    if SUREPASS_TOKEN and pan:
        try:
            resp = http_requests.post(
                SUREPASS_ECOURT_URL,
                json={"id_number": pan},
                headers={"Authorization": f"Bearer {SUREPASS_TOKEN}"},
                timeout=10,
            )
            resp.raise_for_status()
            cases = resp.json().get("data", {}).get("cases", [])

            for case in cases:
                severity = "HIGH" if "criminal" in case.get("case_type", "").lower() else (
                    "MEDIUM" if "civil" in case.get("case_type", "").lower() else "LOW"
                )
                records.append({
                    "case_no": case.get("cnr_number", ""),
                    "court": case.get("court_name", ""),
                    "case_type": case.get("case_type", ""),
                    "status": case.get("status", ""),
                    "severity": severity,
                    "source": "SUREPASS",
                })

            return records

        except Exception:
            pass

    # Fallback: Weaviate LitigationRecord collection
    hits = query_weaviate_collection(
        "LitigationRecord",
        company_name,
        company_name,
        ["case_no", "court", "case_type", "status", "severity", "source"],
    )
    for hit in hits:
        records.append({
            "case_no": hit.get("case_no", ""),
            "court": hit.get("court", ""),
            "case_type": hit.get("case_type", ""),
            "status": hit.get("status", ""),
            "severity": hit.get("severity", "LOW"),
            "source": hit.get("source", "SCRAPE"),
        })

    return records


def fetch_regulatory_flags(industry: str) -> list:
    """
    Query Weaviate RBICircular collection for sector-specific headwinds.
    """
    hits = query_weaviate_collection(
        "RBICircular",
        f"{industry} regulation risk headwind",
        industry,
        ["circular_no", "title", "body", "issued_date", "sector_tags"],
    )

    return [
        {
            "circular_no": h.get("circular_no", ""),
            "title": h.get("title", ""),
            "issued_date": h.get("issued_date", ""),
        }
        for h in hits
    ]


class WebIntelligenceAgent(AgentBase):
    AGENT_NAME = "web-intelligence-agent"
    LISTEN_TOPICS = ["gst_completed", "bank_recon_completed"]
    OUTPUT_NAMESPACE = "web_intel"
    OUTPUT_EVENT = "web_intel_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Full RAG pipeline: query Weaviate for news, litigation, and RBI circulars.
        Score sentiment using VADER. Return structured web intelligence.
        """
        applicant = ucso.get("applicant", {})
        company_name = applicant.get("company_name", "")
        industry = applicant.get("industry_sector", "")
        pan = applicant.get("pan", "")

        # Fetch news with sentiment scoring
        self.logger.info(
            f"Querying Weaviate for news about '{company_name}'",
            extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
        )
        promoter_news = fetch_news(company_name, industry)

        # Fetch litigation records
        self.logger.info(
            f"Fetching litigation records for '{company_name}'",
            extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
        )
        litigation_records = fetch_litigation(company_name, pan)

        # Fetch sector headwinds from RBI circulars
        regulatory_flags = fetch_regulatory_flags(industry)
        sector_headwinds = [f.get("title", "") for f in regulatory_flags]

        # Compute KB freshness
        now = datetime.now(timezone.utc)
        kb_freshness_hours = 0
        if promoter_news:
            latest_pub = max(
                (n.get("published_at", "") for n in promoter_news), default=""
            )
            if latest_pub:
                try:
                    pub_dt = datetime.fromisoformat(latest_pub.replace("Z", "+00:00"))
                    kb_freshness_hours = int((now - pub_dt).total_seconds() / 3600)
                except (ValueError, TypeError):
                    kb_freshness_hours = 9999
            else:
                kb_freshness_hours = 9999
        else:
            kb_freshness_hours = 9999

        return {
            "promoter_news": promoter_news,
            "litigation_records": litigation_records,
            "regulatory_flags": regulatory_flags,
            "sector_headwinds": sector_headwinds,
            "kb_query_timestamp": now.isoformat(),
            "kb_freshness_hours": kb_freshness_hours,
        }


if __name__ == "__main__":
    agent = WebIntelligenceAgent()
    agent.run()
