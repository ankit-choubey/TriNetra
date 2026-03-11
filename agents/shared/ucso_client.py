"""
Trinetra UCSO Client
HTTP client for interacting with the FastAPI backend API.
Each agent uses this to GET the current UCSO state and PATCH its own namespace.

Migration: Spring Boot → FastAPI (March 2026)
- Removed 'ucsoData' wrapper unwrap (FastAPI returns raw UCSO)
- Default port changed from :8080 to :8000
"""
import os
import requests
from .logger import get_logger

logger = get_logger("ucso-client")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


class UcsoClient:
    """
    Client for reading and writing to the central UCSO (Unified Credit Schema Object)
    stored in the FastAPI backend (Supabase Postgres).

    Rules:
        - Each agent MUST only PATCH its own namespace. No full PUT allowed.
        - All field names use snake_case.
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or BACKEND_URL

    def get_ucso(self, application_id: str) -> dict:
        """
        Fetch the full UCSO JSON for a given application.

        Args:
            application_id: UUID of the loan application.

        Returns:
            The full UCSO dictionary.
        """
        url = f"{self.base_url}/api/application/{application_id}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            # FastAPI returns raw UCSO directly (no ucsoData wrapper)
            return data
        except requests.RequestException as e:
            logger.error(f"Failed to GET UCSO {application_id}: {e}")
            raise

    def patch_namespace(self, application_id: str, namespace: str, data: dict) -> dict:
        """
        PATCH a specific namespace of the UCSO.

        Args:
            application_id: UUID of the loan application.
            namespace: The top-level key to update (e.g., 'gst_analysis', 'risk').
            data: The dictionary payload to merge into that namespace.

        Returns:
            The updated UCSO dictionary.
        """
        url = f"{self.base_url}/api/application/{application_id}/namespace/{namespace}"
        try:
            resp = requests.patch(url, json=data, timeout=10)
            resp.raise_for_status()
            logger.info(
                f"PATCH {namespace} for {application_id} successful",
                extra={"agent_name": "ucso-client", "application_id": application_id},
            )
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to PATCH {namespace} for {application_id}: {e}")
            raise

    def upload_file(self, application_id: str, file_path: str, doc_type: str) -> str:
        """
        Upload a file to Supabase Storage via the FastAPI backend.

        Args:
            application_id: UUID of the loan application.
            file_path: Local path to the file.
            doc_type: Document type (e.g., 'ANNUAL_REPORT', 'CAM').

        Returns:
            The storage path of the uploaded file.
        """
        url = f"{self.base_url}/api/files/upload"
        with open(file_path, "rb") as f:
            files = {"file": f}
            data = {"application_id": application_id, "type": doc_type}
            try:
                resp = requests.post(url, files=files, data=data, timeout=30)
                resp.raise_for_status()
                result = resp.json()
                # Return storage_path (also available as s3_key for backward compat)
                return result.get("storage_path", result.get("s3_key", ""))
            except requests.RequestException as e:
                logger.error(f"Failed to upload file for {application_id}: {e}")
                raise
