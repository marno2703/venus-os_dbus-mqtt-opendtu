#!/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
SERVICE_NAME=$(basename "$SCRIPT_DIR")
SERVICE_PATH="/service/$SERVICE_NAME"

echo
echo "Stopping $SERVICE_NAME..."

if [ -e "$SERVICE_PATH" ]; then
    touch "$SERVICE_PATH/down" 2>/dev/null || true
    touch "$SERVICE_PATH/log/down" 2>/dev/null || true
    svc -d "$SERVICE_PATH" 2>/dev/null || true
    svc -d "$SERVICE_PATH/log" 2>/dev/null || true
    sleep 2
fi

pkill -f "python[0-9.]* .*/$SERVICE_NAME.py" 2>/dev/null || true
pkill -f ".*/$SERVICE_NAME.py" 2>/dev/null || true
pkill -f "multilog .*$SERVICE_NAME" 2>/dev/null || true

sleep 1

remaining=$(pgrep -f "$SERVICE_NAME.py|multilog .*$SERVICE_NAME" 2>/dev/null || true)
if [ -n "$remaining" ]; then
    echo "Still running:"
    ps w | grep -E "$SERVICE_NAME.py|multilog .*$SERVICE_NAME" | grep -v grep || true
    echo
    exit 1
fi

echo "done."
echo
