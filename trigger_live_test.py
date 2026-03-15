import requests
import json
import uuid
from agents.test_full_pipeline import APPLICATION

API_URL = "http://localhost:8000/api"

def trigger_live_test():
    # 1. Mocking the initial application payload Creation to get a clean UUID
    applicant_payload = APPLICATION["applicant"]
    applicant_payload["loan_requested"] = APPLICATION["loan_requested"]
    response = requests.post(f"{API_URL}/application", json=applicant_payload)
    app_id = response.json()["id"]
    
    print(f"🚀 Triggering LIVE FULL Pipeline test for new valid UUID: {app_id}")

    # 2. Mocking the Database directly because the /api/application route only 
    # instantiates an empty application. The agents need the pre-populated PDF data.
    for namespace, data in APPLICATION.items():
        if isinstance(data, dict) and namespace not in ["applicant", "documents"]:
            requests.patch(f"{API_URL}/application/{app_id}/namespace/{namespace}", json=data)
            
    # 3. Upload Dummy File to trigger 'application_created' event in Redis
    from reportlab.pdfgen import canvas
    import io
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer)
    c.drawString(100, 750, "MOCK FULL PIPELINE PDF")
    c.save()
    pdf_bytes = pdf_buffer.getvalue()

    print("📤 Uploading document to trigger the Genesis Redis event...")
    files = {"file": ("bank_statement.pdf", pdf_bytes, "application/pdf")}
    data = {"application_id": app_id, "type": "DOCUMENT"}
    requests.post(f"{API_URL}/files/upload", files=files, data=data)
    
    print(f"✅ Success! Redis event fired. The 13 agents should be cascading now.")

if __name__ == "__main__":
    trigger_live_test()
