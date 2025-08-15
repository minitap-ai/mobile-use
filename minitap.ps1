$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Find devices connected via TCP/IP
$tcp_devices = @(
    [regex]::Matches(
        (adb devices | Out-String),
        '(\d{1,3}(?:\.\d{1,3}){3}:\d+)'
    ) | ForEach-Object { $_.Value } | Sort-Object -Unique
)

if ($tcp_devices) {
    if ($tcp_devices.Length -eq 1) {
        # If one TCP/IP device is found, use it
        $device_ip = ($tcp_devices -split '\s+')[0]
        Write-Host "Device already in TCP/IP mode: $device_ip"
    } else {
        # If multiple TCP/IP devices are found, prompt user to select one
        Write-Host "Multiple devices found. Please select one:"
        for ($i = 0; $i -lt $tcp_devices.Length; $i++) {
            $ip = ($tcp_devices[$i] -split '\s+')[0]
            Write-Host "[$($i+1)] $ip"
        }
        $selection = Read-Host -Prompt "Enter number"
        $index = [int]$selection - 1
        if ($index -ge 0 -and $index -lt $tcp_devices.Length) {
            $device_ip = ($tcp_devices[$index] -split '\s+')[0]
        } else {
            Write-Error "Invalid selection."
            exit 1
        }
    }
} else {
    # If no TCP/IP devices found, get IP and connect
    Write-Host "No device in TCP/IP mode, enabling..."
    $ADB_COMMAND = "ip addr show wlan0 | grep 'inet ' | awk '{print `$2}' | cut -d/ -f1"
    $device_ip_only = (adb shell $ADB_COMMAND).Trim()
    if (-not $device_ip_only) {
        Write-Error "Could not get device IP. Is a device connected via USB and on the same Wi-Fi network?"
        exit 1
    }
    adb tcpip 5555
    $device_ip = "${device_ip_only}:5555"
}

Write-Output "Device IP is: $device_ip"
$env:ADB_CONNECT_ADDR = "$device_ip"

docker compose run --rm --remove-orphans -it mobile-use-ip $args
