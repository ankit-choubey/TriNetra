#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  TRINETRA — Agent & Backend Supervisor                  ║
# ║  Monitors backend + 14 agents — restarts crashes        ║
# ╚══════════════════════════════════════════════════════════╝

cd /Users/utkarshsingh/Desktop/Trinetra

if [ -f agents/.env ]; then
    set -a
    source agents/.env
    set +a
fi

AGENTS=(
    "compliance-agent" "doc-agent" "gst-agent" "bank-recon-agent"
    "mca-agent" "web-agent" "model-selector-agent" "risk-agent"
    "bias-agent" "stress-agent" "cam-agent" "pan-agent" "monitor-agent"
    "pd-agent"
)

mkdir -p agents/logs
mkdir -p logs

start_backend() {
    if [ -f "backend/main.py" ]; then
        python backend/main.py >> "logs/backend.log" 2>&1 &
        PID_backend=$!
        echo "  🚀 Started backend (PID: $PID_backend)"
    else
        echo "  ❌ backend/main.py not found at $(pwd)!"
    fi
}

start_agent() {
    local agent=$1
    local var_name="PID_${agent//-/_}"
    if [ -f "agents/$agent/main.py" ]; then
        cd agents
        python "$agent/main.py" >> "logs/${agent}.log" 2>&1 &
        eval "$var_name=\$!"
        cd ..
        eval "echo \"  🚀 Started ${agent} (PID: \$$var_name)\""
    else
        echo "  ❌ agents/${agent}/main.py not found at $(pwd)!"
    fi
}

is_alive() {
    local pid=$1
    kill -0 "$pid" 2>/dev/null
}

cleanup() {
    echo -e "\n🛑 Stopping all processes..."
    if [ -n "$PID_backend" ]; then kill "$PID_backend" 2>/dev/null; fi
    for agent in "${AGENTS[@]}"; do
        local var_name="PID_${agent//-/_}"
        eval "local pid=\$$var_name"
        if [ -n "$pid" ]; then kill "$pid" 2>/dev/null; fi
    done
    pkill -f 'python.*backend/main.py' 2>/dev/null
    pkill -f 'python.*main.py' 2>/dev/null
    echo "✅ All processes stopped."
    exit 0
}
trap cleanup INT TERM

echo "🚀 Starting Backend..."
start_backend

echo "🚀 Starting all agents..."
for agent in "${AGENTS[@]}"; do
    start_agent "$agent"
done

echo -e "\n════════════════════════════════════════════════════════"
echo "  🎉 Backend and ${#AGENTS[@]} agents started!"
echo "  🔄 Watchdog checking every 10 seconds..."
echo "  🛑 Press Ctrl+C to stop"
echo -e "════════════════════════════════════════════════════════\n"

RESTART_COUNT=0
while true; do
    sleep 10
    
    # Check Backend
    if [ -z "$PID_backend" ] || ! is_alive "$PID_backend"; then
        RESTART_COUNT=$((RESTART_COUNT + 1))
        echo "  ⚠️  Backend died — restarting... (#${RESTART_COUNT})"
        start_backend
    fi

    # Check Agents
    for agent in "${AGENTS[@]}"; do
        var_name="PID_${agent//-/_}"
        eval "pid=\$$var_name"
        if [ -z "$pid" ] || ! is_alive "$pid"; then
            RESTART_COUNT=$((RESTART_COUNT + 1))
            echo "  ⚠️  ${agent} died — restarting... (#${RESTART_COUNT})"
            start_agent "$agent"
        fi
    done
done
