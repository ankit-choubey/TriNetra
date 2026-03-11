"""
╔══════════════════════════════════════════════════════════════════╗
║  TRINETRA — FastAPI Backend (Central Orchestrator)              ║
║  Replaces Spring Boot with Python-native backend               ║
╠══════════════════════════════════════════════════════════════════╣
║  Stack: FastAPI + Supabase (Postgres + Storage) + Redis Pub/Sub ║
║  All 6 API pillars preserved 1:1 from Spring Boot              ║
╚══════════════════════════════════════════════════════════════════╝

Run:  cd backend && python main.py
"""
import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, Form, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from config import CORS_ORIGINS, HOST, PORT
from models import (
    ApplicationCreate,
    ApplicationResponse,
    NoteRequest,
    StressTriggerRequest,
)
from supabase_client import SupabaseClient
from redis_broker import AsyncRedisBroker
from websocket_manager import WebSocketManager

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-18s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("trinetra-backend")

# ── Global instances ──
db = SupabaseClient()
redis_broker = AsyncRedisBroker()
ws_manager = WebSocketManager()


# ── Background task: Redis → WebSocket bridge ──
async def redis_to_websocket_bridge():
    """
    Listens to the 'agent_status' Redis channel and broadcasts
    every agent update to connected WebSocket clients.
    This replaces Spring Boot's KafkaConsumerService + STOMP bridge.
    """
    try:
        await redis_broker.connect()
        await redis_broker.subscribe("agent_status")
        logger.info("🔗 Redis → WebSocket bridge started (listening on 'agent_status')")

        async for msg in redis_broker.listen():
            data = msg["data"]
            app_id = data.get("application_id", "")
            if app_id:
                await ws_manager.broadcast(app_id, data)
                logger.info(
                    f"📡 WS broadcast: {data.get('agent', '?')} → {data.get('status', '?')} "
                    f"(app: {app_id[:8]}..., clients: {ws_manager.connection_count})"
                )
    except asyncio.CancelledError:
        logger.info("Redis → WebSocket bridge stopped")
    except Exception as e:
        logger.error(f"Redis bridge error: {e}")


# ── App lifecycle ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks on startup, clean up on shutdown."""
    # Start the Redis → WebSocket bridge
    bridge_task = asyncio.create_task(redis_to_websocket_bridge())
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║   TRINETRA FastAPI Backend — ONLINE                 ║")
    logger.info("╚══════════════════════════════════════════════════════╝")
    yield
    # Shutdown
    bridge_task.cancel()
    await redis_broker.close()
    logger.info("Backend shut down.")


# ═══════════════════════════════════════════════════════════
#  FASTAPI APP
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="Trinetra OS — Backend API",
    description="Central Orchestrator for Intelli-Credit Agentic AI System",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS (for Devraj's React frontend) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
#  PILLAR 1: Application Initialization
# ═══════════════════════════════════════════════════════════

@app.post("/api/application", response_model=ApplicationResponse)
async def create_application(payload: ApplicationCreate):
    """
    Create a new loan application.
    Initializes the UCSO with 14 empty agent namespaces.
    """
    applicant_data = payload.model_dump()
    result = db.create_application(applicant_data)

    app_id = result["id"]
    logger.info(f"📋 Application created: {app_id}")

    return ApplicationResponse(
        id=app_id,
        status="CREATED",
        message="Application created. Upload documents to trigger AI pipeline.",
    )


# ═══════════════════════════════════════════════════════════
#  PILLAR 2: Data Fetching (UCSO)
# ═══════════════════════════════════════════════════════════

@app.get("/api/application/{application_id}")
async def get_application(application_id: str):
    """
    Fetch the full UCSO for an application.
    Used by both frontend (UI rendering) and agents (data fetching).
    """
    ucso = db.get_ucso(application_id)
    if not ucso:
        raise HTTPException(status_code=404, detail="Application not found")
    return ucso


# ═══════════════════════════════════════════════════════════
#  PILLAR 3: File Ingestion (Upload to Supabase Storage)
# ═══════════════════════════════════════════════════════════

@app.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    application_id: str = Form(...),
    type: str = Form("DOCUMENT"),
):
    """
    Upload a file (PDF, DOCX, etc.) to Supabase Storage.
    Appends file metadata to the UCSO's documents.files array.
    After upload, publishes 'application_created' event to trigger AI pipeline.
    """
    file_bytes = await file.read()
    filename = file.filename or "uploaded_file"

    result = db.upload_file(application_id, file_bytes, filename, type)

    # Fire the Genesis Event — triggers the AI pipeline
    # Do not trigger if the file is a CAM generated by the system itself
    if type != "CAM":
        await redis_broker.publish("application_created", {
            "application_id": application_id,
        })
    
    logger.info(
        f"📤 File uploaded: {filename} ({len(file_bytes)} bytes) → "
        f"Storage: {result['storage_path']} | Event: {'application_created fired' if type != 'CAM' else 'skipped (CAM)'}"
    )

    return {
        "storage_path": result["storage_path"],
        "file_url": result["file_url"],
        "s3_key": result["storage_path"],  # Backward compatibility for agents
        "status": "UPLOADED",
    }


# ═══════════════════════════════════════════════════════════
#  PILLAR 4: Agent Namespace Commits (PATCH)
# ═══════════════════════════════════════════════════════════

@app.patch("/api/application/{application_id}/namespace/{namespace}")
async def patch_namespace(application_id: str, namespace: str, data: dict):
    """
    Patch a specific namespace within the UCSO.
    Exclusively used by Python AI agents to inject their results.
    """
    try:
        result = db.patch_namespace(application_id, namespace, data)
        logger.info(f"✏️ PATCH {namespace} for {application_id[:8]}... ({list(data.keys())})")
        return result.get("ucso_data", result) if isinstance(result, dict) else result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════
#  PILLAR 5: File Retrieval (Download)
# ═══════════════════════════════════════════════════════════

@app.get("/api/files/{application_id}")
async def get_file(
    application_id: str,
    filename: str = Query(None, description="Specific filename to download (e.g. CAM.docx)"),
):
    """
    Download a file for an application.
    Default: prioritizes .pdf files (backward compat for agents).
    With ?filename=CAM.docx: downloads specific file.
    """
    result = db.get_file(application_id, filename)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")

    file_bytes, actual_filename = result

    # Determine content type
    content_type = "application/octet-stream"
    if actual_filename.lower().endswith(".pdf"):
        content_type = "application/pdf"
    elif actual_filename.lower().endswith(".docx"):
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={actual_filename}"},
    )


# ═══════════════════════════════════════════════════════════
#  PILLAR 6: Interactive Triggers
# ═══════════════════════════════════════════════════════════

@app.post("/api/application/{application_id}/notes")
async def add_notes(application_id: str, payload: NoteRequest):
    """Add a human note from the credit officer."""
    try:
        ucso = db.add_note(application_id, payload.note, payload.author)
        logger.info(f"📝 Note added for {application_id[:8]}... by {payload.author}")
        return {"status": "OK", "note_count": len(ucso.get("human_notes", {}).get("notes", []))}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/application/{application_id}/stress")
async def trigger_stress_test(application_id: str, payload: StressTriggerRequest):
    """Re-trigger the Stress Agent with custom parameters."""
    # Publish event to Redis → Stress Agent picks it up
    await redis_broker.publish("stress_retrigger", {
        "application_id": application_id,
        "interest_rate_hike": payload.interest_rate_hike,
        "revenue_drop_pct": payload.revenue_drop_pct,
    })
    logger.info(
        f"🔄 Stress re-trigger for {application_id[:8]}... "
        f"(rate+{payload.interest_rate_hike}%, rev-{payload.revenue_drop_pct}%)"
    )
    return {"status": "TRIGGERED", "message": "Stress agent will re-process with new parameters"}


@app.post("/api/application/{application_id}/pd")
async def trigger_pd(application_id: str):
    """Re-trigger the PD Transcript Agent."""
    await redis_broker.publish("pd_retrigger", {
        "application_id": application_id,
    })
    return {"status": "TRIGGERED", "message": "PD agent will re-process"}


# ═══════════════════════════════════════════════════════════
#  WEBSOCKET — Real-Time Agent Updates
# ═══════════════════════════════════════════════════════════

@app.websocket("/ws/{application_id}")
async def websocket_endpoint(websocket: WebSocket, application_id: str):
    """
    Native WebSocket endpoint for real-time agent status updates.
    Replaces STOMP/SockJS. Frontend connects to ws://host:8000/ws/{id}
    """
    await ws_manager.connect(websocket, application_id)
    logger.info(
        f"🔌 WebSocket connected: {application_id[:8]}... "
        f"(total: {ws_manager.connection_count})"
    )

    try:
        # Keep connection alive — listen for client messages (ping/pong)
        while True:
            data = await websocket.receive_text()
            # Client can send a ping, we respond with pong
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, application_id)
        logger.info(f"🔌 WebSocket disconnected: {application_id[:8]}...")


# ═══════════════════════════════════════════════════════════
#  UTILITY ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "OK",
        "service": "Trinetra FastAPI Backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "websocket_connections": ws_manager.connection_count,
    }


@app.get("/api/applications")
async def list_applications():
    """List all applications (for dashboard)."""
    try:
        result = db.client.table("applications").select(
            "id, company_name, pan, status, created_at"
        ).order("created_at", desc=True).limit(50).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to list applications: {e}")
        return []


# ═══════════════════════════════════════════════════════════
#  RUN SERVER
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    print("╔══════════════════════════════════════════════════════════╗")
    print("║   TRINETRA — FastAPI Backend Server                     ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  URL:    http://{HOST}:{PORT}                           ║")
    print(f"║  Docs:   http://{HOST}:{PORT}/docs                     ║")
    print(f"║  CORS:   {CORS_ORIGINS}                                 ║")
    print("╚══════════════════════════════════════════════════════════╝")

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
