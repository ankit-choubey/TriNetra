#!/bin/zsh
# ╔══════════════════════════════════════════════════════════╗
# ║  TRINETRA — Agent Supervisor with Auto-Restart          ║
# ╚══════════════════════════════════════════════════════════╝

PYTHON_EXE="$SCRIPT_DIR/venv/bin/python3"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." 

if [ -f agents/.env ]; then
    set -a
    source agents/.env
    set +a
fi

AGENTS=(
    "compliance-agent" "doc-agent" "gst-agent" "bank-recon-agent"
    "mca-agent" "web-agent" "model-selector-agent" "risk-agent"
    "bias-agent" "stress-agent" "cam-agent" "pan-agent" "monitor-agent"
)

typeset -A PROCESS_PIDS

mkdir -p agents/logs
mkdir -p backend/logs


start_agent() {
    local agent=$1
    if [ -d "agents/$agent" ]; then
        cd "agents/$agent"
        "$SCRIPT_DIR/venv/bin/python3" main.py >> "$SCRIPT_DIR/logs/${agent}.log" 2>&1 &
        PROCESS_PIDS[$agent]=$!
        cd ../..
        echo "  🚀 Started ${agent} (PID: ${PROCESS_PIDS[$agent]})"
    else
        echo "  ❌ agents/${agent} not found!"
    fi
}

is_alive() {
    local pid=$1
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

cleanup() {
    echo "\n🛑 Stopping all processes..."
    for key in ${(k)PROCESS_PIDS}; do
        pid=${PROCESS_PIDS[$key]}
        if is_alive "$pid"; then kill "$pid" 2>/dev/null; fi
    done
    pkill -f 'python.*main.py' 2>/dev/null
    exit 0
}
trap cleanup INT TERM


echo "🚀 Starting all agents..."
for agent in "${AGENTS[@]}"; do
    start_agent "$agent"
done

echo "\n🎉 System started!"
echo "🔄 Monitoring... (Check agents/watchdog.log for details)"

while true; do
    sleep 10
    for agent in "${AGENTS[@]}"; do
        if ! is_alive "${PROCESS_PIDS[$agent]}"; then
            echo "  ⚠️  ${agent} died — restarting..."
            start_agent "$agent"
        fi
    done
done