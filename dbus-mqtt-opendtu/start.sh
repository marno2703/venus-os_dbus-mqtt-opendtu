#!/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
SERVICE_NAME=$(basename "$SCRIPT_DIR")

echo
echo "Starting $SERVICE_NAME..."

if [ ! -e "/service/$SERVICE_NAME" ]; then
    echo "Service /service/$SERVICE_NAME does not exist. Run install.sh first."
    echo
    exit 1
fi

svc -u "/service/$SERVICE_NAME/log" 2>/dev/null || true
svc -u "/service/$SERVICE_NAME" 2>/dev/null || true

echo "done."
echo
