#!/bin/bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
SERVICE_NAME=$(basename "$SCRIPT_DIR")
INSTALL_DIR="/data/etc/$SERVICE_NAME"
RC_LOCAL="/data/rc.local"

echo
echo "Installing $SERVICE_NAME to $INSTALL_DIR..."

if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    cp -a "$SCRIPT_DIR/." "$INSTALL_DIR/"
    SCRIPT_DIR="$INSTALL_DIR"
fi

if [ ! -f "$SCRIPT_DIR/config.ini" ] && [ -f "$SCRIPT_DIR/config.sample.ini" ]; then
    cp "$SCRIPT_DIR/config.sample.ini" "$SCRIPT_DIR/config.ini"
fi

echo "Setting permissions..."
chmod 755 "$SCRIPT_DIR"/*.py
chmod 755 "$SCRIPT_DIR"/*.sh
chmod 755 "$SCRIPT_DIR/service/run"
chmod 755 "$SCRIPT_DIR/service/log/run"

if [ ! -L "/service/$SERVICE_NAME" ]; then
    echo "Creating service..."
    ln -s "$SCRIPT_DIR/service" "/service/$SERVICE_NAME"
else
    echo "Service already exists."
fi

if [ ! -f "$RC_LOCAL" ]; then
    touch "$RC_LOCAL"
    chmod 755 "$RC_LOCAL"
    echo "#!/bin/bash" >> "$RC_LOCAL"
    echo >> "$RC_LOCAL"
fi

grep -qxF "bash $INSTALL_DIR/install.sh" "$RC_LOCAL" || echo "bash $INSTALL_DIR/install.sh" >> "$RC_LOCAL"

if command -v svc >/dev/null 2>&1; then
    svc -t "/service/$SERVICE_NAME" 2>/dev/null || true
fi

echo "done."
echo
