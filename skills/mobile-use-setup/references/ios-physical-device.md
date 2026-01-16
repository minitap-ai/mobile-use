# iOS Physical Device Setup

Complete guide for connecting a physical iPhone or iPad for mobile automation.

## Prerequisites

- macOS with Xcode installed
- Apple ID (free tier works)
- Physical iOS device
- USB cable

## Step 1: Install Dependencies

```bash
# libimobiledevice for device communication
brew install libimobiledevice

# Appium and XCUITest driver
npm install -g appium
appium driver install xcuitest
```

## Step 2: Configure WebDriverAgent Code Signing

WebDriverAgent (WDA) is the bridge between Appium and iOS. It must be signed with your Apple Developer certificate.

### Open WDA in Xcode

```bash
open ~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj
```

### Sign All Targets

For **each** of these targets:
- WebDriverAgentRunner
- WebDriverAgentLib
- IntegrationApp

Do the following:

1. Select the target in the Project Navigator (left sidebar)
2. Click "Signing & Capabilities" tab
3. Check "Automatically manage signing"
4. Select your Team (your Apple ID)
5. Change Bundle Identifier to something unique:
   - `com.yourname.WebDriverAgentRunner`
   - `com.yourname.WebDriverAgentLib`
   - `com.yourname.IntegrationApp`

### Build IntegrationApp

1. Connect your iOS device via USB
2. Select your device as the build destination (dropdown in toolbar)
3. Select "IntegrationApp" scheme
4. Press Cmd+B to build

This installs WDA on your device.

## Step 3: Trust Developer Certificate

On your iOS device:

1. Go to **Settings**
2. Navigate to **General → VPN & Device Management**
3. Find your developer certificate under "Developer App"
4. Tap **Trust "[Your Name]"**
5. Confirm by tapping **Trust**

## Step 4: Verify Connection

```bash
# List connected devices
idevice_id -l

# Get device info
ideviceinfo
```

You should see your device's UDID.

## Troubleshooting

### Device not showing up

1. Ensure device is unlocked
2. On device, tap "Trust" when prompted about the computer
3. Try a different USB cable/port
4. Restart the device

### "Untrusted Developer" error

Go to Settings → General → VPN & Device Management and trust your certificate.

### WDA build fails

1. Ensure all 3 targets are signed with the same Apple ID
2. Use unique Bundle Identifiers (not the defaults)
3. Try cleaning the build: Cmd+Shift+K in Xcode

### "Could not launch WebDriverAgent" during automation

1. Rebuild IntegrationApp in Xcode
2. Ensure device is unlocked during automation
3. Check if WDA app appears on device home screen

## Multiple Devices

When multiple iOS devices are connected, specify the target device:

```python
from minitap.mobile_use.sdk.builders import Builders

# Get UDID with: idevice_id -l
config = (
    Builders.AgentConfig
    .for_device("00008110-001A2C3E4F50001E", platform="ios")
    .build()
)
agent = Agent(config=config)
```

## Wireless Connection (Advanced)

iOS devices can be connected wirelessly after initial USB pairing:

1. Connect device via USB
2. In Xcode: Window → Devices and Simulators
3. Select your device
4. Check "Connect via network"
5. Disconnect USB

The device will now appear over WiFi when on the same network.
