"""
Agent 3: PD (Personal Discussion) Transcript Agent
Approach: Speech-to-Text + Contextual LLM (Groq API with Llama 3 70b)
Tools: openai-whisper (base model), Groq API

Trigger: pd_submitted
Reads: human_notes
Writes: pd_intelligence
Errors: WHISPER_FAIL → accept text fallback. LLM_FAIL → log warning, use raw transcript.
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase

import requests as http_requests

# Groq API setup
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-70b-8192")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# LLM Evaluation Prompt (strict JSON output)
PD_EVALUATION_PROMPT = """You are a senior credit risk officer at an Indian bank. 
You are reading the transcript of a Personal Discussion (PD) with a loan applicant.

Evaluate the transcript on these 3 risk dimensions:
1. **Succession Planning**: Does the company have a clear succession plan? (0.0 = solid plan, 1.0 = no plan at all)
2. **Operational Capacity**: Is the factory/business operating at reasonable capacity? (0.0 = excellent, 1.0 = severely underutilized or overextended)
3. **Management Integrity**: Does the management appear transparent and honest? (0.0 = fully transparent, 1.0 = evasive or concerning)

Also extract any named entities (people, companies, locations, financial figures) mentioned.

RESPOND ONLY with valid JSON in this exact format:
{
  "succession_risk": 0.0,
  "capacity_risk": 0.0,
  "integrity_risk": 0.0,
  "overall_risk_adjustment": 0.0,
  "qualitative_flags": ["flag1", "flag2"],
  "entities_extracted": {"people": [], "companies": [], "amounts": []},
  "confidence": 0.0,
  "reasoning": "One sentence explanation."
}

The overall_risk_adjustment should be between -0.10 (positive signal, reduce risk) and +0.15 (negative signal, increase risk).
"""


def transcribe_audio(file_path: str) -> str:
    """
    Transcribe audio file using OpenAI Whisper (base model).
    Falls back to empty string on failure.
    """
    try:
        import whisper

        model = whisper.load_model("base")
        result = model.transcribe(file_path)
        return result.get("text", "")
    except Exception as e:
        print(f"WHISPER_FAIL: {e}")
        return ""


def evaluate_transcript_with_groq(transcript: str) -> dict:
    """
    Send the transcript to Groq API (Llama 3 70b) for structured evaluation.
    Returns the parsed JSON risk assessment.
    """
    if not GROQ_API_KEY:
        return {
            "succession_risk": 0.5,
            "capacity_risk": 0.5,
            "integrity_risk": 0.5,
            "overall_risk_adjustment": 0.0,
            "qualitative_flags": ["GROQ_API_KEY_MISSING"],
            "entities_extracted": {},
            "confidence": 0.0,
            "reasoning": "Groq API key not configured. Using neutral defaults.",
        }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": PD_EVALUATION_PROMPT},
            {
                "role": "user",
                "content": f"Here is the Personal Discussion transcript:\n\n{transcript}",
            },
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = http_requests.post(
            GROQ_API_URL, headers=headers, json=payload, timeout=30
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"GROQ_LLM_FAIL: {e}")
        return {
            "succession_risk": 0.5,
            "capacity_risk": 0.5,
            "integrity_risk": 0.5,
            "overall_risk_adjustment": 0.0,
            "qualitative_flags": [f"LLM_FAIL: {str(e)}"],
            "entities_extracted": {},
            "confidence": 0.0,
            "reasoning": f"LLM evaluation failed: {str(e)}",
        }


class PDTranscriptAgent(AgentBase):
    AGENT_NAME = "pd-transcript-agent"
    LISTEN_TOPICS = ["pd_submitted"]
    OUTPUT_NAMESPACE = "pd_intelligence"
    OUTPUT_EVENT = "pd_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Process PD submission: transcribe audio (if any) and evaluate with Groq LLM.
        """
        human_notes = ucso.get("human_notes", {})
        notes = human_notes.get("notes", [])

        transcript_text = ""
        source_type = "TEXT"

        # Check if there's an audio file to transcribe
        for note in notes:
            if note.get("type") == "AUDIO" and note.get("s3_key"):
                source_type = "AUDIO"
                try:
                    file_url = f"{self.ucso_client.base_url}/api/files/download?s3_key={note['s3_key']}"
                    resp = http_requests.get(file_url, timeout=60)
                    resp.raise_for_status()

                    with tempfile.NamedTemporaryFile(
                        suffix=".mp3", delete=False
                    ) as tmp:
                        tmp.write(resp.content)
                        tmp_path = tmp.name

                    transcript_text = transcribe_audio(tmp_path)
                    os.unlink(tmp_path)

                    if not transcript_text:
                        source_type = "TEXT"
                        self.logger.warning(
                            "Whisper transcription failed, falling back to text notes",
                            extra={
                                "agent_name": self.AGENT_NAME,
                                "application_id": application_id,
                            },
                        )
                except Exception as e:
                    self.logger.error(
                        f"Audio download/transcription failed: {e}",
                        extra={
                            "agent_name": self.AGENT_NAME,
                            "application_id": application_id,
                        },
                    )

        # If no audio transcript, use text notes
        if not transcript_text:
            text_notes = [
                n.get("text", "") for n in notes if n.get("type") == "TEXT"
            ]
            transcript_text = " ".join(text_notes)

        if not transcript_text.strip():
            self.logger.warning(
                f"No PD content found for {application_id}",
                extra={
                    "agent_name": self.AGENT_NAME,
                    "application_id": application_id,
                },
            )
            return {
                "transcript_text": "",
                "source_type": source_type,
                "entities_extracted": {},
                "qualitative_flags": ["NO_PD_CONTENT"],
                "risk_adjustment": 0.0,
                "pd_confidence": 0.0,
            }

        # Evaluate transcript using Groq LLM (Llama 3 70b)
        self.logger.info(
            f"Evaluating PD transcript ({len(transcript_text)} chars) with Groq LLM",
            extra={
                "agent_name": self.AGENT_NAME,
                "application_id": application_id,
            },
        )
        evaluation = evaluate_transcript_with_groq(transcript_text)

        # Clamp risk adjustment to safe bounds [-0.10, +0.15]
        risk_adj = evaluation.get("overall_risk_adjustment", 0.0)
        risk_adj = max(-0.10, min(0.15, risk_adj))

        return {
            "transcript_text": transcript_text,
            "source_type": source_type,
            "entities_extracted": evaluation.get("entities_extracted", {}),
            "qualitative_flags": evaluation.get("qualitative_flags", []),
            "risk_adjustment": round(risk_adj, 4),
            "pd_confidence": round(evaluation.get("confidence", 0.0), 4),
        }


if __name__ == "__main__":
    agent = PDTranscriptAgent()
    agent.run()
