# Trinetra Agent Integration: Backend Architecture Guide

The Trinetra AI Agents operate as 13 independent microservices communicating purely via Kafka topics and REST API calls (to fetch/update the UCSO state).

For the entire pipeline to run flawlessly, the Java/Spring Boot backend must adhere to these specific architectural contracts.

---

## 1. REST API Endpoints Contract

The agents expect 3 specific endpoints to be consistently available. Any mismatches in these paths will break the python `UcsoClient`.

### 1.1 Fetch UCSO State
**Expected:** `GET /api/application/{application_id}`
- **Behavior:** Returns the full, latest JSON representation of the application (the entire UCSO).
- **Security:** Must either be unauthenticated (for internal IP traffic) or the agents must be provided a static Bearer token in their `.env` file to bypass Spring Security.

### 1.2 Update Namespace (PATCH)
**Expected:** `PATCH /api/application/{application_id}/namespace/{namespace}`
- **Behavior:** The backend must update ONLY the specific namespace key provided in the path with the JSON payload provided in the body.
- **Example Call:** `PATCH /api/application/123-abc/namespace/risk` updates `ucsoData.risk`.
- **CRITICAL FORMAT RULE:** The backend must accept a flat JSON Object `{}` for the body. If the agent needs to send an array (like the `audit_log` from the Monitor Agent), it will wrap it in an object: `{"data": [...]}`. The backend must handle this format without throwing a `400 Bad Request`.

### 1.3 File Upload/Download
**Expected GET:** `GET /api/files/{application_id}`
- **Behavior:** Returns the raw binary stream of the document. If multiple files exist, it can accept a query param `?doc_type=ANNUAL_REPORT` (or it must return a zip). *Current Python agent expects a single PDF stream.*
**Expected POST:** `POST /api/files/upload`
- **Behavior:** Accepts `multipart/form-data` with fields `file`, `application_id`, and `type`.

---

## 2. Kafka Topic Contract

The agents are entirely reactive. They wake up when specific strings are published to Kafka. 
The backend is responsible for triggering the very first domino.

### 2.1 The Genesis Event
When the user submits the form on the frontend, the backend creates the database record, generates the UUID, and must publish the genesis event:
- **Topic Name:** `application_created`  *(Must be exact)*
- **Payload Format:**
```json
{
  "application_id": "YOUR-UUID-HERE",
  "source": "backend_api",
  "timestamp": "2026-03-07T10:00:00Z"
}
```
*Note: Without this initial `application_created` event hitting Kafka, the Compliance Agent will not wake up, and the entire 13-agent chain will never start.*

### 2.2 Kafka Broker Configuration
- The Spring Boot `application.properties` must set the Kafka broker to `PLAINTEXT://0.0.0.0:9092` so that external agents (on the same WiFi network) can connect.
- Topic auto-creation must be enabled, or the backend script must ensure all topics are created at startup.

---

## 3. Database / UCSO Schema Expectations

The backend is the ultimate source of truth for the UCSO (Unified Credit Scoring Object). It must persist changes made by the agents.

### 3.1 Namespace Initialization
When an application is created, the backend should initialize empty objects for the major namespaces so that `PATCH` requests don't fail trying to write to `null`:
```json
{
  "application_id": "123-abc",
  "applicant": { ... }, // Filled by frontend form
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

### 3.2 Handling the "Combined Document" Scenario
As requested, the Compliance Agent has been updated to handle cases where the user only uploads **1 single file** (a combined PDF). 
- If the backend receives only 1 file upload from the frontend, it should just store it in the `documents.files` array.
- **The Compliance Agent will automatically detect it is a singleton, duplicate the entry into the 4 required `doc_type`s (ANNUAL_REPORT, BANK_STMT, GST_RETURN, ITR), and PATCH the backend.**
- The backend database must accept this PATCH and update the document list.

---

## 4. WebSocket Feed for Frontend

The Python agents do not talk directly to the frontend. They communicate their status (e.g., "Doc Agent Completed") by printing to logs, but they do NOT push direct WebSocket frames.

If the frontend expects a live feed, the Spring Boot Backend must:
1. Act as a Consumer on all Trinetra Kafka topics (`compliance_failed`, `parsing_completed`, `risk_generated`, etc.).
2. When parsing a message from these topics, transform it into the WebSocket format expected by the frontend.
3. Push it to `/topic/agent-updates` via STOMP.
