#!/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
SERVICE_NAME=$(basename "$SCRIPT_DIR")
SERVICE_PATH="/service/$SERVICE_NAME"

echo
echo "Starting $SERVICE_NAME..."

if [ ! -e "$SERVICE_PATH" ]; then
    echo "Service $SERVICE_PATH does not exist. Run install.sh first."
    echo
    exit 1
fi

rm -f "$SERVICE_PATH/down" "$SERVICE_PATH/log/down"
svc -u "$SERVICE_PATH/log" 2>/dev/null || true
svc -u "$SERVICE_PATH" 2>/dev/null || true

echo "done."
echo
