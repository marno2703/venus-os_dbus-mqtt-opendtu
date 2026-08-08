#!/bin/bash
set -e

driver_path="/data/etc"
driver_name="dbus-mqtt-opendtu"
repo_name="venus-os_dbus-mqtt-opendtu"
branch="master"

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
