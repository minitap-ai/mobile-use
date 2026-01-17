#!/bin/bash
# Check prerequisites for Minitap mobile-use SDK setup
# Usage: ./check-prerequisites.sh [ios|android|both]

set -e

PLATFORM="${1:-both}"
MISSING=()

echo "=== Minitap Mobile-Use SDK Prerequisites Check ==="
echo ""

# Core requirements
echo "Checking core requirements..."

# Python 3.12+
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo $PY_VERSION | cut -d. -f1)
    PY_MINOR=$(echo $PY_VERSION | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
        echo "  [OK] Python $PY_VERSION"
    else
        echo "  [FAIL] Python $PY_VERSION (requires 3.12+)"
        MISSING+=("python3.12+")
    fi
else
    echo "  [FAIL] Python not found"
    MISSING+=("python3")
fi

# UV package manager
if command -v uv &> /dev/null; then
    echo "  [OK] UV package manager"
else
    echo "  [MISSING] UV package manager"
    MISSING+=("uv")
fi

# iOS checks
if [ "$PLATFORM" = "ios" ] || [ "$PLATFORM" = "both" ]; then
    echo ""
    echo "Checking iOS requirements..."

    # libimobiledevice
    if command -v idevice_id &> /dev/null; then
        echo "  [OK] libimobiledevice"
    else
        echo "  [MISSING] libimobiledevice"
        MISSING+=("libimobiledevice")
    fi

    # Appium
    if command -v appium &> /dev/null; then
        echo "  [OK] Appium"
        # Check XCUITest driver
        if appium driver list 2>/dev/null | grep -q "xcuitest"; then
            echo "  [OK] XCUITest driver"
        else
            echo "  [MISSING] XCUITest driver"
            MISSING+=("xcuitest-driver")
        fi
    else
        echo "  [MISSING] Appium"
        MISSING+=("appium")
    fi

    # idb (for simulator)
    if command -v idb_companion &> /dev/null; then
        echo "  [OK] idb-companion (simulator)"
    else
        echo "  [INFO] idb-companion not installed (needed for simulator only)"
    fi
fi

# Android checks
if [ "$PLATFORM" = "android" ] || [ "$PLATFORM" = "both" ]; then
    echo ""
    echo "Checking Android requirements..."

    # ADB
    if command -v adb &> /dev/null; then
        echo "  [OK] ADB (Android Debug Bridge)"
    else
        echo "  [MISSING] ADB"
        MISSING+=("adb")
    fi
fi

# Summary
echo ""
echo "=== Summary ==="

if [ ${#MISSING[@]} -eq 0 ]; then
    echo "All prerequisites met! Ready to set up mobile-use SDK."
    exit 0
else
    echo "Missing dependencies:"
    for dep in "${MISSING[@]}"; do
        case $dep in
            "python3"|"python3.12+")
                echo "  - Python 3.12+: brew install python@3.12"
                ;;
            "uv")
                echo "  - UV: curl -LsSf https://astral.sh/uv/install.sh | sh"
                ;;
            "libimobiledevice")
                echo "  - libimobiledevice: brew install libimobiledevice"
                ;;
            "appium")
                echo "  - Appium: npm install -g appium"
                ;;
            "xcuitest-driver")
                echo "  - XCUITest driver: appium driver install xcuitest"
                ;;
            "adb")
                echo "  - ADB: brew install --cask android-platform-tools"
                ;;
        esac
    done
    exit 1
fi
