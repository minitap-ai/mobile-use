#!/bin/bash
# Verify device connectivity for mobile automation
# Usage: ./verify-device.sh [ios|android|both]

PLATFORM="${1:-both}"

echo "=== Device Connectivity Check ==="
echo ""

# iOS checks
if [ "$PLATFORM" = "ios" ] || [ "$PLATFORM" = "both" ]; then
    echo "iOS Devices:"

    # Physical devices
    if command -v idevice_id &> /dev/null; then
        DEVICES=$(idevice_id -l 2>/dev/null)
        if [ -n "$DEVICES" ]; then
            echo "  Physical devices connected:"
            echo "$DEVICES" | while read -r udid; do
                NAME=$(ideviceinfo -u "$udid" -k DeviceName 2>/dev/null || echo "Unknown")
                echo "    - $NAME ($udid)"
            done
        else
            echo "  No physical iOS devices detected"
            echo "  Tip: Ensure device is unlocked and trusted"
        fi
    else
        echo "  [libimobiledevice not installed - cannot check physical devices]"
    fi

    # Simulators
    if command -v xcrun &> /dev/null; then
        echo ""
        echo "  Booted simulators:"
        BOOTED=$(xcrun simctl list devices | grep "(Booted)" || true)
        if [ -n "$BOOTED" ]; then
            echo "$BOOTED" | while read -r line; do
                echo "    - $line"
            done
        else
            echo "    No simulators currently running"
            echo "    Tip: open -a Simulator"
        fi
    fi
    echo ""
fi

# Android checks
if [ "$PLATFORM" = "android" ] || [ "$PLATFORM" = "both" ]; then
    echo "Android Devices:"

    if command -v adb &> /dev/null; then
        # Start server if needed
        adb start-server 2>/dev/null

        DEVICES=$(adb devices 2>/dev/null | grep -v "List" | grep -v "^$")
        if [ -n "$DEVICES" ]; then
            echo "$DEVICES" | while read -r line; do
                SERIAL=$(echo "$line" | awk '{print $1}')
                STATUS=$(echo "$line" | awk '{print $2}')

                if [ "$STATUS" = "device" ]; then
                    MODEL=$(adb -s "$SERIAL" shell getprop ro.product.model 2>/dev/null | tr -d '\r')
                    echo "  [OK] $MODEL ($SERIAL)"
                elif [ "$STATUS" = "unauthorized" ]; then
                    echo "  [UNAUTHORIZED] $SERIAL"
                    echo "      Tip: Check device for USB debugging authorization prompt"
                elif [ "$STATUS" = "offline" ]; then
                    echo "  [OFFLINE] $SERIAL"
                    echo "      Tip: Reconnect device or run: adb kill-server && adb start-server"
                else
                    echo "  [$STATUS] $SERIAL"
                fi
            done
        else
            echo "  No Android devices detected"
            echo "  Tips:"
            echo "    - Enable USB Debugging in Developer Options"
            echo "    - Try a different USB cable/port"
            echo "    - Run: adb kill-server && adb start-server"
        fi
    else
        echo "  [ADB not installed]"
        echo "  Install: brew install --cask android-platform-tools"
    fi
    echo ""
fi

echo "=== Verification Complete ==="
