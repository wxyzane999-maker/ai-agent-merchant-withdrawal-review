#!/bin/bash
# Start Merchant Withdrawal Review AI Demo server
# Usage: bash start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="/tmp/wxy-merchant-withdrawal.pid"

# Stop existing if running
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID"
        echo "Stopped old server (PID $OLD_PID)"
        sleep 1
    fi
fi

cd "$DIR"
nohup python3 server.py > /tmp/wxy-merchant-withdrawal.log 2>&1 &
PID=$!
echo $PID > "$PIDFILE"
echo "Server started (PID $PID)"
echo "URL: http://localhost:8766"
echo "Log: /tmp/wxy-merchant-withdrawal.log"
