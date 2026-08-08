#!/bin/bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
SERVICE_NAME=$(basename "$SCRIPT_DIR")
INSTALL_DIR="/data/etc/$SERVICE_NAME"
RC_LOCAL="/data/rc.local"
OLD_SERVICE_NAME="dbus-mqtt-pv"

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

if [ "$SERVICE_NAME" != "$OLD_SERVICE_NAME" ]; then
    echo "Removing legacy $OLD_SERVICE_NAME service if present..."
    if [ -e "/service/$OLD_SERVICE_NAME" ]; then
        svc -d "/service/$OLD_SERVICE_NAME" 2>/dev/null || true
        rm -f "/service/$OLD_SERVICE_NAME"
    fi
    pkill -f "python .*/$OLD_SERVICE_NAME.py" 2>/dev/null || true
    pkill -f "supervise .*$OLD_SERVICE_NAME" 2>/dev/null || true
    pkill -f "multilog .*$OLD_SERVICE_NAME" 2>/dev/null || true
fi

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

if [ "$SERVICE_NAME" != "$OLD_SERVICE_NAME" ]; then
    sed -i "/$OLD_SERVICE_NAME/d" "$RC_LOCAL"
fi
grep -qxF "bash $INSTALL_DIR/install.sh" "$RC_LOCAL" || echo "bash $INSTALL_DIR/install.sh" >> "$RC_LOCAL"

if command -v svc >/dev/null 2>&1; then
    svc -u "/service/$SERVICE_NAME" 2>/dev/null || true
    svc -t "/service/$SERVICE_NAME" 2>/dev/null || true
fi

echo "done."
echo
