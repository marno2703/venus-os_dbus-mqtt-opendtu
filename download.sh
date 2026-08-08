#!/bin/bash
set -e

driver_path="/data/etc"
driver_name="dbus-mqtt-opendtu"
repo_name="venus-os_dbus-mqtt-opendtu"
branch="master"

stop_driver_service() {
    if [ -e "/service/$driver_name" ]; then
        svc -d "/service/$driver_name" 2>/dev/null || true
        svc -d "/service/$driver_name/log" 2>/dev/null || true
        rm -f "/service/$driver_name"
        sleep 2
    fi

    pkill -f "python .*/$driver_name.py" 2>/dev/null || true
    pkill -f "supervise $driver_name" 2>/dev/null || true
    pkill -f "multilog .*dbus-mqtt-opendtu" 2>/dev/null || true
}

echo
echo "Downloading $driver_name..."

cd /tmp
rm -rf "/tmp/$repo_name.zip" "/tmp/$repo_name-$branch"

curl -L -o "/tmp/$repo_name.zip" "https://github.com/marno2703/$repo_name/archive/refs/heads/$branch.zip"
unzip -o "/tmp/$repo_name.zip" -d /tmp

if [ -f "$driver_path/$driver_name/config.ini" ]; then
    echo "Backing up existing config.ini..."
    cp "$driver_path/$driver_name/config.ini" "/tmp/${driver_name}_config.ini"
fi

echo "Stopping existing $driver_name service..."
stop_driver_service

rm -rf "$driver_path/$driver_name"
mkdir -p "$driver_path"
cp -R "/tmp/$repo_name-$branch/$driver_name" "$driver_path/$driver_name"

if [ -f "/tmp/${driver_name}_config.ini" ]; then
    echo "Restoring existing config.ini..."
    mv "/tmp/${driver_name}_config.ini" "$driver_path/$driver_name/config.ini"
fi

bash "$driver_path/$driver_name/install.sh"

rm -rf "/tmp/$repo_name.zip" "/tmp/$repo_name-$branch"

echo
echo "Done."
echo
