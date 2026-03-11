"""
Trinetra FastAPI Backend — Supabase Client
Handles all DB (Postgres) and Storage (S3-compatible) operations.
UCSO is stored as a single JSONB column — mirrors MongoDB's document model.
"""
import json
import uuid
from datetime import datetime, timezone
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, SUPABASE_STORAGE_BUCKET

# ── Master UCSO Schema (empty namespaces for agents) ──
EMPTY_UCSO = {
    "ucso_version": 1,
    "applicant": {},
    "compliance": {"status": "PENDING", "missing_documents": [], "checked_at": ""},
    "documents": {"files": []},
    "financials": {},
    "derived_features": {},
    "gst_analysis": {"reconciliation_status": "PENDING"},
    "bank_reconciliation": {"reconciliation_verdict": "PENDING"},
    "mca_intelligence": {"company_status": "UNKNOWN"},
    "pan_intelligence": {"status": "PENDING"},
    "web_intel": {},
    "pd_intelligence": {},
    "risk": {"band": "PENDING", "decision": "PENDING"},
    "bias_checks": {"counterfactual_tested": False},
    "stress_results": {"scenarios": [], "survival_verdict": "PENDING"},
    "ews_monitoring": {"enabled": False},
    "decision_confidence": {},
    "cam_output": {},
    "human_notes": {"notes": []},
    "audit_log": [],
}


class SupabaseClient:
    """Wrapper around Supabase for UCSO operations and file storage."""

    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be set in .env"
            )
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.bucket = SUPABASE_STORAGE_BUCKET

    # ═══════════════════════════════════════════════════════
    #  DATABASE OPERATIONS (Postgres JSONB)
    # ═══════════════════════════════════════════════════════

    def create_application(self, applicant_data: dict) -> dict:
        """
        Create a new application with an initialized UCSO.
        Returns the full application row.
        """
        app_id = str(uuid.uuid4())

        # Build the UCSO with applicant data injected
        ucso = json.loads(json.dumps(EMPTY_UCSO))  # Deep copy
        ucso["application_id"] = app_id
        ucso["applicant"] = applicant_data

        row = {
            "id": app_id,
            "company_name": applicant_data.get("company_name", ""),
            "pan": applicant_data.get("pan", ""),
            "gstin": applicant_data.get("gstin", ""),
            "cin": applicant_data.get("cin", ""),
            "ucso_data": ucso,
            "status": "CREATED",
        }

        result = self.client.table("applications").insert(row).execute()
        return result.data[0] if result.data else row

    def get_application(self, app_id: str) -> dict | None:
        """Fetch the full UCSO for an application."""
        result = (
            self.client.table("applications")
            .select("*")
            .eq("id", app_id)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]

    def get_ucso(self, app_id: str) -> dict | None:
        """Fetch just the UCSO data (what agents need)."""
        app = self.get_application(app_id)
        if not app:
            return None
        return app.get("ucso_data", {})

    def patch_namespace(self, app_id: str, namespace: str, data: dict) -> dict:
        """
        Patch a specific namespace within the UCSO.
        Uses Postgres JSONB merge to avoid overwriting other namespaces.
        """
        # Fetch current UCSO
        app = self.get_application(app_id)
        if not app:
            raise ValueError(f"Application {app_id} not found")

        ucso = app.get("ucso_data", {})

        # Merge data into the namespace
        if namespace not in ucso:
            ucso[namespace] = {}

        if isinstance(ucso[namespace], dict):
            ucso[namespace].update(data)
        else:
            ucso[namespace] = data

        # Add audit log
        if "audit_log" not in ucso or not isinstance(ucso["audit_log"], list):
            ucso["audit_log"] = []
            
        ucso["audit_log"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": f"PATCH_{namespace}",
            "keys_updated": list(data.keys()),
        })

        # Update the row
        result = (
            self.client.table("applications")
            .update({
                "ucso_data": ucso,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", app_id)
            .execute()
        )

        return result.data[0] if result.data else ucso

    def update_status(self, app_id: str, status: str):
        """Update application status (CREATED, PROCESSING, COMPLETED, FAILED)."""
        self.client.table("applications").update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", app_id).execute()

    def add_note(self, app_id: str, note: str, author: str) -> dict:
        """Add a human note to the UCSO."""
        app = self.get_application(app_id)
        if not app:
            raise ValueError(f"Application {app_id} not found")

        ucso = app.get("ucso_data", {})
        ucso.setdefault("human_notes", {"notes": []})
        ucso["human_notes"]["notes"].append({
            "text": note,
            "author": author,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.client.table("applications").update({
            "ucso_data": ucso,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", app_id).execute()

        return ucso

    # ═══════════════════════════════════════════════════════
    #  FILE STORAGE (Supabase Storage — S3-compatible)
    # ═══════════════════════════════════════════════════════

    def upload_file(self, app_id: str, file_bytes: bytes, filename: str, doc_type: str) -> dict:
        """
        Upload a file to Supabase Storage.
        Path structure: {app_id}/{doc_type}/{filename}
        """
        storage_path = f"{app_id}/{doc_type}/{filename}"

        # Upload to Supabase Storage
        self.client.storage.from_(self.bucket).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": "application/octet-stream", "upsert": "true"},
        )

        # Get public URL
        file_url = self.client.storage.from_(self.bucket).get_public_url(storage_path)

        # Update UCSO documents.files array
        app = self.get_application(app_id)
        if app:
            ucso = app.get("ucso_data", {})
            ucso.setdefault("documents", {"files": []})
            ucso["documents"]["files"].append({
                "doc_id": str(uuid.uuid4()),
                "type": doc_type,
                "storage_path": storage_path,
                "file_url": file_url,
                "filename": filename,
                "s3_key": storage_path,
                "parsed": False,
                "confidence": 0.0,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            })

            self.client.table("applications").update({
                "ucso_data": ucso,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", app_id).execute()

        return {"storage_path": storage_path, "file_url": file_url}

    def get_file(self, app_id: str, filename: str = None) -> tuple[bytes, str] | None:
        """
        Download a file from Supabase Storage.
        If filename is given, downloads that exact file.
        If not, prioritizes .pdf files (backward compatibility).
        """
        # List files in the app's folder
        try:
            files = self.client.storage.from_(self.bucket).list(app_id)
        except Exception:
            return None

        if not files:
            return None

        # Flatten: list all files recursively by checking subfolders
        all_files = []
        for item in files:
            if item.get("id") is None:
                # It's a folder, list its contents
                subfolder = f"{app_id}/{item['name']}"
                try:
                    subfiles = self.client.storage.from_(self.bucket).list(subfolder)
                    for sf in subfiles:
                        if sf.get("id") is not None:
                            all_files.append(f"{subfolder}/{sf['name']}")
                except Exception:
                    pass
            else:
                all_files.append(f"{app_id}/{item['name']}")

        if not all_files:
            return None

        target_path = None

        if filename:
            # Find exact filename match
            for fp in all_files:
                if fp.endswith(f"/{filename}") or fp.endswith(filename):
                    target_path = fp
                    break
        else:
            # Prioritize .pdf files (backward compatibility with agents)
            pdf_files = [f for f in all_files if f.lower().endswith(".pdf")]
            target_path = pdf_files[0] if pdf_files else all_files[0]

        if not target_path:
            return None

        try:
            data = self.client.storage.from_(self.bucket).download(target_path)
            actual_filename = target_path.split("/")[-1]
            return data, actual_filename
        except Exception:
            return None

    def get_file_url(self, storage_path: str) -> str:
        """Get the public URL for a file."""
        return self.client.storage.from_(self.bucket).get_public_url(storage_path)
