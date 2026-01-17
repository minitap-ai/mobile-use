# Android Device Setup

Complete guide for connecting an Android device for mobile automation.

## Prerequisites

- Android SDK Platform Tools (adb)
- Physical Android device OR emulator
- USB cable (for physical device)

## Step 1: Install ADB

```bash
# macOS
brew install --cask android-platform-tools

# Linux (Debian/Ubuntu)
sudo apt install android-tools-adb

# Linux (Fedora)
sudo dnf install android-tools

# Windows
# Download from: https://developer.android.com/studio/releases/platform-tools
# Extract and add to PATH
```

Verify installation:
```bash
adb version
```

## Step 2: Enable Developer Options

On your Android device:

1. Go to **Settings → About Phone**
2. Find **Build Number**
3. Tap it **7 times** rapidly
4. You'll see "You are now a developer!"

## Step 3: Enable USB Debugging

1. Go to **Settings → Developer Options**
2. Enable **USB Debugging**
3. (Optional) Enable **Stay Awake** to prevent screen timeout during testing

## Step 4: Connect and Authorize

1. Connect device via USB
2. Run `adb devices`
3. On the device, you'll see "Allow USB debugging?"
4. Check "Always allow from this computer"
5. Tap **Allow**

Verify connection:
```bash
adb devices
# Should show: XXXXXXXX    device
```

## Troubleshooting

### Device shows "unauthorized"

1. On device, revoke USB debugging authorizations:
   Settings → Developer Options → Revoke USB debugging authorizations
2. Reconnect and re-authorize

### Device not detected

```bash
# Restart ADB server
adb kill-server
adb start-server
adb devices
```

Other fixes:
- Try a different USB cable (data cable, not charge-only)
- Try a different USB port
- Install device-specific drivers (Windows)
- Check if device is in "Charging only" mode - switch to "File Transfer"

### Multiple devices

Specify target device by serial:

```bash
# List devices
adb devices

# Run command on specific device
adb -s SERIAL_NUMBER shell
```

In Python:
```python
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import Builders

config = (
    Builders.AgentConfig
    .for_device(platform="android", device_id="SERIAL_NUMBER")
    .build()
)
agent = Agent(config=config)
```

## Wireless Debugging

Connect without USB cable (Android 11+):

### Method 1: Wireless Debugging (Android 11+)

1. Enable **Wireless debugging** in Developer Options
2. Tap **Pair device with pairing code**
3. On computer:
   ```bash
   adb pair <IP>:<PAIRING_PORT>
   # Enter pairing code when prompted
   adb connect <IP>:<PORT>
   ```

### Method 2: TCP/IP (Any Android version)

1. Connect device via USB first
2. Run:
   ```bash
   adb tcpip 5555
   adb connect <DEVICE_IP>:5555
   ```
3. Disconnect USB
4. Verify: `adb devices`

To find device IP: Settings → About Phone → Status → IP Address

## Emulator Setup

Using Android Emulator from Android Studio:

1. Open Android Studio
2. Tools → Device Manager
3. Create Virtual Device
4. Select hardware profile and system image
5. Launch emulator

The emulator appears automatically in `adb devices`:
```bash
adb devices
# emulator-5554    device
```

## Scrcpy (Screen Mirroring)

Optional but helpful for debugging - mirror device screen to computer:

```bash
# Install
brew install scrcpy

# Run (with device connected)
scrcpy
```
