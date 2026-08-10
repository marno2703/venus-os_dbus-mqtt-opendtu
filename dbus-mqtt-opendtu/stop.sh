#!/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
SERVICE_NAME=$(basename "$SCRIPT_DIR")

echo
echo "Stopping $SERVICE_NAME..."

if [ -e "/service/$SERVICE_NAME" ]; then
    svc -d "/service/$SERVICE_NAME" 2>/dev/null || true
    svc -d "/service/$SERVICE_NAME/log" 2>/dev/null || true
fi

pkill -f "python .*/$SERVICE_NAME.py" 2>/dev/null || true
pkill -f "supervise $SERVICE_NAME" 2>/dev/null || true
pkill -f "multilog .*$SERVICE_NAME" 2>/dev/null || true

echo "done."
echo
