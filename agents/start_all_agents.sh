#!/bin/bash

# A simple, robust script to start Trinetra Agents in the background.
# Now includes a status check to verify agents are running!

cd "$(dirname "$0")"

# 1. Clean up any globally dangling agents to prevent port/memory conflicts
echo "🧹 Cleaning up any existing agent processes..."
pkill -f 'agents/.*/main.py' 2>/dev/null
sleep 2

# 2. Activate the virtual environment
source venv/bin/activate

# Create logs directory if it doesn't exist
mkdir -p logs

# Note: pd-agent is intentionally excluded from this array!
AGENTS=(
    "compliance-agent" "doc-agent" "gst-agent" "bank-recon-agent"
    "mca-agent" "web-agent" "model-selector-agent" "risk-agent"
    "bias-agent" "stress-agent" "cam-agent" "pan-agent" "monitor-agent"
)

PIDS=()

echo "🚀 Starting Trinetra Agents..."

for agent in "${AGENTS[@]}"; do
    if [ -d "$agent" ]; then
        cd "$agent"
        # Add a timestamp separator to the log
        echo -e "\n\n===========================================================" >> "../logs/${agent}.log"
        echo "🚀 Starting $agent at $(date)" >> "../logs/${agent}.log"
        echo "===========================================================" >> "../logs/${agent}.log"
        
        # Run agent in background, detach it, and pipe logs (Appending with >>)
        # Using abstract PWD to ensure unique process name for PKILL later
        nohup python "$PWD/main.py" >> "../logs/${agent}.log" 2>&1 &
        PIDS+=($!)
        cd ..
    else
        echo "  ❌ Could not find directory for $agent"
        PIDS+=("")
    fi
done

echo "⏳ Waiting 3 seconds for agents to initialize..."
sleep 3

echo ""
echo "📊 Agent Status Report:"
echo "-----------------------------------------------------------"
for i in "${!AGENTS[@]}"; do
    agent="${AGENTS[$i]}"
    pid="${PIDS[$i]}"
    
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        # Print padded strings for a beautiful aligned output
        printf "  🟢 [RUNNING]   %-22s (PID: %s)\n" "$agent" "$pid"
    else
        printf "  🔴 [FAILED]    %-22s (Check logs/%s.log)\n" "$agent" "$agent"
    fi
done
echo "-----------------------------------------------------------"
echo "ℹ️  (pd-agent was specifically excluded as requested)"
echo "📄 To view any agent log in real time, type, e.g.: tail -f logs/risk-agent.log"
echo ""