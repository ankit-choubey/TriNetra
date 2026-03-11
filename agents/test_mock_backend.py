"""
Trinetra Mock Backend
Simulates the Spring Boot API for agent testing.
Handles UCSO GET/PATCH and file upload/download mocks.
"""
from flask import Flask, request, jsonify, send_file
import json
import os
import uuid
from datetime import datetime, timezone

app = Flask(__name__)

# In-memory storage for UCSOs
# Schema based on agents/shared/ucso_schema.json
STORAGE_DIR = "/tmp/trinetra_mock"
os.makedirs(STORAGE_DIR, exist_ok=True)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "shared", "ucso_schema.json")
with open(SCHEMA_PATH, "r") as f:
    MASTER_SCHEMA = json.load(f)


def get_ucso_path(app_id):
    return os.path.join(STORAGE_DIR, f"{app_id}.json")


@app.route("/api/ucso/<app_id>", methods=["GET"])
def get_ucso(app_id):
    path = get_ucso_path(app_id)
    if not os.path.exists(path):
        # Initialize from schema
        ucso = MASTER_SCHEMA.copy()
        ucso["application_id"] = app_id
        with open(path, "w") as f:
            json.dump(ucso, f)
    
    with open(path, "r") as f:
        return jsonify(json.load(f))


@app.route("/api/ucso/<app_id>/namespace/<namespace>", methods=["PATCH"])
def patch_namespace(app_id, namespace):
    data = request.json
    path = get_ucso_path(app_id)
    
    if not os.path.exists(path):
        return jsonify({"error": "Application not found"}), 404
    
    with open(path, "r") as f:
        ucso = json.load(f)
    
    # Merge data into namespace
    if namespace not in ucso:
        ucso[namespace] = {}
    
    ucso[namespace].update(data)
    
    # Add audit log entry
    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": f"PATCH_{namespace}",
        "data": data
    }
    ucso["audit_log"].append(audit_entry)
    
    with open(path, "w") as f:
        json.dump(ucso, f)
    
    return jsonify(ucso)


@app.route("/api/files/upload", methods=["POST"])
def upload_file():
    app_id = request.form.get("application_id")
    doc_type = request.form.get("doc_type")
    file = request.files.get("file")
    
    if not file:
        return jsonify({"error": "No file"}), 400
    
    s3_key = f"{app_id}/{doc_type}/{file.filename}"
    save_path = os.path.join(STORAGE_DIR, "files", s3_key)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)
    
    return jsonify({"s3_key": s3_key, "status": "UPLOADED"})


@app.route("/api/files/download", methods=["GET"])
def download_file():
    s3_key = request.args.get("s3_key")
    path = os.path.join(STORAGE_DIR, "files", s3_key)
    if os.path.exists(path):
        return send_file(path)
    return jsonify({"error": "File not found"}), 404


if __name__ == "__main__":
    print(f"Starting Trinetra Mock Backend at http://localhost:8080")
    print(f"Storage directory: {STORAGE_DIR}")
    app.run(host="0.0.0.0", port=8080)
