#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  TRINETRA — Start All 13 Agents                         ║
# ║  Each agent runs as a separate background process        ║
# ╚══════════════════════════════════════════════════════════╝

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env values
if [ -f .env ]; then
    export BACKEND_URL=$(grep "^BACKEND_URL=" .env | cut -d= -f2-)
    export KAFKA_BROKER=$(grep "^KAFKA_BROKER=" .env | cut -d= -f2-)
fi
BACKEND_URL="${BACKEND_URL:-http://localhost:8080}"
KAFKA_BROKER="${KAFKA_BROKER:-localhost:9092}"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║   TRINETRA — Starting All 13 Agents                     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Backend:  ${BACKEND_URL}                                ║"
echo "║  Kafka:    ${KAFKA_BROKER}                               ║"
echo "╚══════════════════════════════════════════════════════════╝"

# ── Pre-flight checks ──
echo ""
echo "🔍 Running pre-flight checks..."

# Check backend
if curl -s --connect-timeout 3 "${BACKEND_URL}" > /dev/null 2>&1; then
    echo "  ✅ Backend is reachable at ${BACKEND_URL}"
else
    echo "  ❌ Backend is NOT reachable at ${BACKEND_URL}"
    echo "     Make sure Spring Boot is running!"
    exit 1
fi

# Check Kafka
KAFKA_HOST=$(echo ${KAFKA_BROKER} | cut -d: -f1)
KAFKA_PORT=$(echo ${KAFKA_BROKER} | cut -d: -f2)
if nc -z -w3 "$KAFKA_HOST" "$KAFKA_PORT" 2>/dev/null; then
    echo "  ✅ Kafka is reachable at ${KAFKA_BROKER}"
else
    echo "  ❌ Kafka is NOT reachable at ${KAFKA_BROKER}"
    echo "     Make sure Kafka is running! (docker-compose up -d kafka)"
    exit 1
fi

echo ""
echo "🚀 Starting agents..."

# Create logs directory
mkdir -p logs

# ── Start each agent as a background process ──
AGENTS=(
    "compliance-agent"
    "doc-agent"
    "pd-agent"
    "gst-agent"
    "bank-recon-agent"
    "mca-agent"
    "web-agent"
    "model-selector-agent"
    "risk-agent"
    "bias-agent"
    "stress-agent"
    "cam-agent"
    "monitor-agent"
)

PIDS=()
for agent in "${AGENTS[@]}"; do
    if [ -f "$agent/main.py" ]; then
        python "$agent/main.py" > "logs/${agent}.log" 2>&1 &
        PID=$!
        PIDS+=($PID)
        echo "  ✅ Started ${agent} (PID: $PID)"
    else
        echo "  ❌ ${agent}/main.py not found!"
    fi
done

echo ""
echo "════════════════════════════════════════════════════════"
echo "  🎉 All ${#PIDS[@]} agents started!"
echo "  📋 Logs: agents/logs/<agent-name>.log"
echo ""
echo "  To view live logs:"
echo "    tail -f agents/logs/compliance-agent.log"
echo ""
echo "  To stop all agents:"
echo "    pkill -f 'python.*agent.*main.py'"
echo "════════════════════════════════════════════════════════"

# Save PIDs for cleanup
echo "${PIDS[@]}" > logs/agent_pids.txt

# Wait for all — press Ctrl+C to stop
echo ""
echo "  Press Ctrl+C to stop all agents..."
cleanup() {
    echo ""
    echo "Stopping all agents..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    echo "Done."
    exit 0
}
trap cleanup INT TERM
wait
