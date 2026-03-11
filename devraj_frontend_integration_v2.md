# Trinetra OS — Frontend Integration Guide v2 (FastAPI Backend)

> **To: Devraj** | **From: Utkarsh** | **Date: 10 March 2026**
>
> Bhai Devraj, backend Spring Boot se FastAPI (Python) me shift ho gaya hai. API paths same hain, sirf base URL aur WebSocket protocol change hua hai. Below is everything you need.

---

## 🔗 Base URL

```
# Development (local)
BASE_URL = http://localhost:8000

# Production (will share later)
BASE_URL = https://trinetra-api.railway.app  (TBD)
```

> **Change from old:** `http://10.1.161.48:8080` → `http://localhost:8000`

---

## 📡 API Endpoints (Same Paths, Same Payloads)

### 1. Create Application (Form Submit)

```javascript
// POST /api/application
const res = await fetch(`${BASE_URL}/api/application`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    company_name: "XYZ Pvt Ltd",
    pan: "AAACT1234A",
    gstin: "27AAACT1234A1ZX",
    cin: "U12345MH2020PTC123456",
    loan_amount_requested: 5000000,
    loan_purpose: "Working Capital",
    industry_sector: "Manufacturing",
    // ... other fields
  })
});

const data = await res.json();
const applicationId = data.id;  // ← SAVE THIS UUID!
```

### 2. Upload Documents

```javascript
// POST /api/files/upload
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('application_id', applicationId);
formData.append('type', 'ANNUAL_REPORT');  // or BANK_STMT, GST_RETURN, ITR

const res = await fetch(`${BASE_URL}/api/files/upload`, {
  method: 'POST',
  body: formData,   // No Content-Type header — browser sets it automatically
});

const data = await res.json();
// Returns: { storage_path: "...", file_url: "https://...supabase.co/..." }
```

> **1-file shortcut still works:** Upload 1 PDF as `ANNUAL_REPORT`. The Compliance Agent auto-expands it into 4 types.

### 3. Fetch Application Data (UCSO)

```javascript
// GET /api/application/{id}
const res = await fetch(`${BASE_URL}/api/application/${applicationId}`);
const ucso = await res.json();

// ⚠️ KEY CHANGE: No more ucsoData wrapper!
// OLD: const risk = ucso.ucsoData.risk;
// NEW: const risk = ucso.risk;

// Display data:
const riskScore = ucso.risk.score;         // 0.0 - 1.0
const decision = ucso.risk.decision;       // "APPROVE" | "REVIEW" | "REJECT"
const confidence = 1.0 - riskScore;        // Invert for confidence %
const shapFactors = ucso.risk.top_risk_factors;
```

### 4. Download CAM Report

```javascript
// GET /api/files/{applicationId}?filename=CAM.docx
const downloadUrl = `${BASE_URL}/api/files/${applicationId}?filename=CAM.docx`;

// Option A: Direct download link
<a href={downloadUrl} download>Download CAM Report</a>

// Option B: Fetch and create blob
const res = await fetch(downloadUrl);
const blob = await res.blob();
const url = window.URL.createObjectURL(blob);
// Create temp link and click
```

### 5. Add Human Notes

```javascript
// POST /api/application/{id}/notes
await fetch(`${BASE_URL}/api/application/${applicationId}/notes`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    note: "Credit officer review: Approved with conditions",
    author: "Devraj"
  })
});
```

### 6. Re-trigger Stress Test

```javascript
// POST /api/application/{id}/stress
await fetch(`${BASE_URL}/api/application/${applicationId}/stress`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    interest_rate_hike: 2.0,    // +2% scenario
    revenue_drop_pct: 20.0      // -20% scenario
  })
});
```

---

## 🔌 WebSocket — Real-Time Agent Updates

> **⚠️ MAJOR CHANGE:** STOMP/SockJS is gone. Now using **native WebSocket**.

### Old Code (REMOVE THIS):
```javascript
// ❌ DELETE THIS — SockJS + STOMP is gone
import SockJS from 'sockjs-client';
import { Stomp } from '@stomp/stompjs';

const socket = new SockJS(`${BASE_URL}/ws`);
const client = Stomp.over(socket);
client.subscribe(`/topic/updates/${applicationId}`, ...);
```

### New Code (USE THIS):
```javascript
// ✅ Native WebSocket — much simpler!
const ws = new WebSocket(`ws://localhost:8000/ws/${applicationId}`);

ws.onopen = () => {
  console.log('🟢 Connected to Trinetra WebSocket');
};

ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  // update = {
  //   agent: "compliance-agent",        // Which agent
  //   status: "PROCESSING" | "COMPLETED" | "FAILED",
  //   application_id: "uuid",
  //   error_code: null | "DOCS_MISSING"
  // }

  console.log(`Agent ${update.agent}: ${update.status}`);

  // Update your progress bar / dashboard
  if (update.status === 'COMPLETED') {
    // Re-fetch UCSO to get latest data
    fetchApplicationData(applicationId);
  }
};

ws.onclose = () => {
  console.log('🔴 WebSocket disconnected');
  // Auto-reconnect after 3 seconds
  setTimeout(() => connectWebSocket(applicationId), 3000);
};

ws.onerror = (err) => {
  console.error('WebSocket error:', err);
};
```

### React Hook Example:
```javascript
import { useEffect, useState } from 'react';

function useTrinetraWebSocket(applicationId) {
  const [agentUpdates, setAgentUpdates] = useState([]);

  useEffect(() => {
    if (!applicationId) return;

    const ws = new WebSocket(`ws://localhost:8000/ws/${applicationId}`);

    ws.onmessage = (event) => {
      const update = JSON.parse(event.data);
      setAgentUpdates(prev => [...prev, update]);
    };

    return () => ws.close(); // Cleanup on unmount
  }, [applicationId]);

  return agentUpdates;
}

// Usage:
function Dashboard({ applicationId }) {
  const updates = useTrinetraWebSocket(applicationId);

  return (
    <div>
      {updates.map((u, i) => (
        <div key={i}>
          {u.agent}: {u.status === 'COMPLETED' ? '✅' : '⏳'}
        </div>
      ))}
    </div>
  );
}
```

---

## 📋 UCSO Data Mapping (For Dashboard Charts)

| Frontend Component | UCSO Path | Example Value |
|---|---|---|
| Risk Ring / Score | `ucso.risk.score` | `0.23` |
| Confidence % | `1.0 - ucso.risk.score` | `0.77` (77%) |
| Decision Badge | `ucso.risk.decision` | `"APPROVE"` |
| SHAP Bar Chart | `ucso.risk.top_risk_factors` | `[{feature, shap_value}]` |
| Credit Limit | `ucso.risk.recommended_limit` | `5000000` |
| Interest Rate | `ucso.risk.recommended_rate_bps` | `950` (9.5%) |
| Stress Test Table | `ucso.stress_results.scenarios` | `[{name, dscr, verdict}]` |
| GST Discrepancy | `ucso.gst_analysis.gstr2b_vs_3b_discrepancy_pct` | `5.2` |
| Bank Divergence | `ucso.bank_reconciliation.turnover_divergence_pct` | `8.1` |
| PAN Status | `ucso.pan_intelligence.pan_status` | `"VALID"` |
| CAM Download | `GET /api/files/{id}?filename=CAM.docx` | Binary file |

---

## 🔧 Quick Setup Checklist for Devraj

- [ ] Update `BASE_URL` from `http://10.1.161.48:8080` → `http://localhost:8000`
- [ ] Remove SockJS + STOMP dependencies (`npm uninstall sockjs-client @stomp/stompjs`)
- [ ] Replace WebSocket code with native `new WebSocket(...)` (see above)
- [ ] Remove `ucsoData` wrapper: `response.ucsoData.risk` → `response.risk`
- [ ] Install no new deps — native WebSocket is built into every browser!
- [ ] Test with: `npm run dev` → open app → submit form → watch console for WS messages

---

## 🚨 Dependencies to Remove
```bash
npm uninstall sockjs-client @stomp/stompjs
```

## 🆘 Troubleshooting
- **CORS error?** → The FastAPI backend has CORS enabled for `http://localhost:5173`
- **WebSocket won't connect?** → Make sure backend is running: `cd backend && python main.py`
- **File download returns 404?** → Use `?filename=CAM.docx` parameter
- **Empty UCSO fields?** → Agents haven't finished yet. Wait for WebSocket `COMPLETED` messages.
