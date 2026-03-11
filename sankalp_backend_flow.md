# Trinetra OS — Backend Integration Guide for Sankalp

Hi Sankalp, this document outlines the exact handshakes required between your Spring Boot backend and Utkarsh's 13 Python AI Agents.

For the AI pipeline to function deterministically, the backend must orchestrate the flow exactly as follows:

## 1. Application Creation & Initialization
When Devraj sends the initial text payload (Phase 1):
1. Save the applicant data to your DB.
2. Generate the unique `application_id`.
3. **CRITICAL INITIALIZATION:** You must initialize the UCSO (Unified Credit Scoring Object) with empty namespaces for the agents to write into later. If these are `null`, the agents' PATCH requests will throw 400 Bad Requests.
   ```json
   {
     "application_id": "uuid-here",
     "applicant": { ... devraj's data ... },
     "documents": { "files": [] },
     "compliance": {},
     "financials": {},
     "gst_analysis": {},
     "bank_reconciliation": {},
     "mca_intelligence": {},
     "web_intel": {},
     "pd_intelligence": {},
     "derived_features": {},
     "risk": {},
     "stress_results": {},
     "bias_checks": {},
     "cam_output": {}
   }
   ```
4. Return the `application_id` to Devraj.

## 2. Document Handling & The Kafka Trigger
When Devraj uploads the PDF(s) to `POST /api/files/upload`:

### The 1-File vs 4-File Logic
- Devraj will either send **1 combined PDF** or **4 separate PDFs**.
- Just save the files to your storage (S3/local).
- Append the file metadata to the `documents.files` array in the UCSO.
  ```json
  // Inside UCSO
  "documents": {
    "files": [
      { "doc_type": "ANNUAL_REPORT", "s3_key": "path/combined.pdf" }
    ]
  }
  ```

### Firing the Starting Gun (Kafka)
**This is the most critical step.** Once the user has finished uploading their document(s), your backend **must** publish the Genesis Event to Kafka. If you don't send this, none of the 13 agents will ever wake up.

- **Topic:** `application_created`
- **Payload:** `{"application_id": "uuid-here"}`

*What happens next:* Utkarsh's **Compliance Agent** immediately wakes up. 
- If you saved 4 files: It verifies they are the correct types (`ANNUAL_REPORT`, `BANK_STMT`, `GST_RETURN`, `ITR`).
- If you saved 1 file: It magically duplicates that 1 file into 4 separate database entries by sending a `PATCH` back to your API to update the `documents` array.
- It then publishes `compliance_passed` to Kafka, which wakes up the rest of the 12 agents.

## 3. Handling Agent PATCH Requests
While the 13 agents are running, they will constantly hit your API to save their math and ML results.

- **Endpoint:** `PATCH /api/application/{application_id}/namespace/{namespace}`
- You must strictly apply the JSON payload to the specific `{namespace}` key in the database without overwriting the rest of the object.
- **Data Shape:** Every agent is hardcoded to send a `dict` (JSON Object) as the payload. Even if the data is a list (like the Monitor Agent's audit log), it will be wrapped in `{"data": [...]}`.

## 4. Final Output (The CAM Report)
The very last agent to run is the **CAM Generator Agent**.
1. It downloads the entire finalized UCSO from your API.
2. It generates a 5-page Word Document (Credit Appraisal Memo).
3. It uploads this `.docx` file back to your backend using `POST /api/files/upload` (with `type="CAM"`).
4. It patches the `cam_output` namespace with the file path.
5. Devraj will then fetch this finalized JSON from you to display the dashboard charts and the download button!
