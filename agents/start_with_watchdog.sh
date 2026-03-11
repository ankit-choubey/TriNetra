#!/bin/zsh
# ╔══════════════════════════════════════════════════════════╗
# ║  TRINETRA — Agent Supervisor with Auto-Restart          ║
# ╚══════════════════════════════════════════════════════════╝

PYTHON_EXE="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
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

start_backend() {
    if [ -f "backend/main.py" ]; then
        $PYTHON_EXE "backend/main.py" >> "backend/logs/backend.log" 2>&1 &
        PROCESS_PIDS[backend]=$!
        echo "  🚀 Started backend (PID: ${PROCESS_PIDS[backend]})"
    else
        echo "  ❌ backend/main.py not found!"
    fi
}

start_agent() {
    local agent=$1
    if [ -d "agents/$agent" ]; then
        cd "agents/$agent"
        $PYTHON_EXE main.py >> "../logs/${agent}.log" 2>&1 &
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

echo "🚀 Starting Backend..."
start_backend

echo "🚀 Starting all agents..."
for agent in "${AGENTS[@]}"; do
    start_agent "$agent"
done

echo "\n🎉 System started!"
echo "🔄 Monitoring... (Check agents/watchdog.log for details)"

while true; do
    sleep 10
    if ! is_alive "${PROCESS_PIDS[backend]}"; then
        echo "  ⚠️  Backend died — restarting..."
        start_backend
    fi
    for agent in "${AGENTS[@]}"; do
        if ! is_alive "${PROCESS_PIDS[$agent]}"; then
            echo "  ⚠️  ${agent} died — restarting..."
            start_agent "$agent"
        fi
    done
done
