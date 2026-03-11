# Trinetra OS — Frontend Integration Guide for Devraj

Hi Devraj, this document outlines the exact flow of data between your React frontend and the Trinetra AI Agents (via Sankalp's backend).

To ensure the 13 AI agents can process the application correctly, your frontend needs to follow this strict sequence:

## Phase 1: Application Creation (The Text Data)
1. The user fills out the 14-field form on the Data Ingestor page.
2. You send a `POST /api/application` request to Sankalp's backend.
3. **CRITICAL:** Sankalp's backend will return a unique `application_id` (UUID). You must store this UUID (e.g., in `sessionStorage` or global Context).
4. Do **not** allow the user to upload documents until you have successfully received this UUID.

## Phase 2: Document Uploads
Once you have the `application_id`, the user can upload their financial documents. The AI agents support two ways of doing this:

### Option A: The Combined Document (1 File)
If the user uploads a single master PDF containing everything:
1. You make a single `POST /api/files/upload` to Sankalp.
2. Keep the `type` parameter generic (e.g., `COMBINED` or `ANNUAL_REPORT`).
3. **What happens next:** Sankalp saves this single file. Utkarsh's Compliance Agent will automatically detect that only 1 file was uploaded. It will magically duplicate that file into the 4 required types (`ANNUAL_REPORT`, `BANK_STMT`, `GST_RETURN`, `ITR`) inside the backend database.

### Option B: Individual Documents (4 Files)
If the user uploads 4 separate files:
1. You make 4 separate `POST /api/files/upload` requests to Sankalp.
2. Ensure you pass the exact `type` strings:
   - `ANNUAL_REPORT`
   - `BANK_STMT`
   - `GST_RETURN`
   - `ITR`
3. **What happens next:** The Compliance Agent will check if all 4 exist. If any are missing, it will halt the AI pipeline and flag the loan.

## Phase 3: The AI Pipeline Execution
After the documents are uploaded, Utkarsh's 13 AI agents take over. They will run OCR, math models, and machine learning scoring on the backend.
- The agents will take roughly 30-60 seconds to complete.
- They will populate the `ucsoData` JSON object on Sankalp's backend.

## Phase 4: Displaying the Final Results
On the Recommendation Engine page, you will pull the final `ucsoData` JSON from Sankalp:
`GET /api/application/{application_id}`

### Key Data to Display:
Instead of looking for fake mock keys, you need to map your charts to the real agent outputs:

1. **Risk Ring / Confidence:** Use `1.0 - ucsoData.risk.score` to get a percentage from 0 to 100%. (The agent outputs pure risk, so inverse it for "confidence").
2. **Decision:** `ucsoData.risk.decision` ("APPROVE", "REVIEW", "REJECT")
3. **SHAP Chart:** Use the array at `ucsoData.risk.top_risk_factors`.
4. **Limits & Rates:** Use `ucsoData.risk.recommended_limit` and `ucsoData.risk.recommended_rate_bps`.
5. **CAM Report:** When the user clicks "Download CAM", fetch the PDF from Sankalp. The path will be saved by the agents in `ucsoData.cam_output.s3_key`.
