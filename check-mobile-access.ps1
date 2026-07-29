$ErrorActionPreference = 'SilentlyContinue'

$listener = Get-NetTCPConnection -State Listen -LocalPort 5173 |
    Select-Object -First 1
$address = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.AddressState -eq 'Preferred' -and
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254*'
    } |
    Sort-Object InterfaceMetric |
    Select-Object -First 1

Write-Host '=== Mobile Access Check ==='
if (-not $listener) {
    Write-Host '[FAIL] Frontend is not running. Run .\start.ps1 first.' -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Frontend listener: $($listener.LocalAddress):5173"
if (-not $address) {
    Write-Host '[FAIL] No usable private IPv4 address was found.' -ForegroundColor Red
    exit 1
}

$url = "http://$($address.IPAddress):5173"
$adapter = Get-NetAdapter -InterfaceIndex $address.InterfaceIndex
$profile = Get-NetConnectionProfile -InterfaceIndex $address.InterfaceIndex
$virtualAdapter = (
    $adapter.InterfaceDescription -match 'VMware|VirtualBox|Hyper-V|Virtual Ethernet' -or
    $adapter.MacAddress -match '^(00-0C-29|00-05-69|00-1C-14|00-50-56|08-00-27)'
)
Write-Host "[INFO] Candidate mobile URL: $url"
Write-Host "[INFO] Adapter: $($adapter.InterfaceDescription)"
Write-Host "[INFO] Network profile: $($profile.NetworkCategory)"

try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    Write-Host "[OK] LAN URL works on this computer. HTTP $($response.StatusCode)"
} catch {
    Write-Host '[FAIL] LAN URL does not work locally. Restart the project.' -ForegroundColor Red
}

$nodeRule = Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True `
    -Direction Inbound -Action Allow |
    Where-Object {
        $application = $_ | Get-NetFirewallApplicationFilter
        $application.Program -like '*\node.exe'
    } |
    Select-Object -First 1
if ($nodeRule) {
    Write-Host '[OK] Windows Firewall allows Node.js inbound traffic.'
} else {
    Write-Host '[WARN] No Node.js inbound rule. Allow Node.js on Private networks.' -ForegroundColor Yellow
}

if ($virtualAdapter) {
    Write-Host ''
    Write-Host '[BLOCKED] A virtual network adapter is active.' -ForegroundColor Yellow
    Write-Host 'Phones cannot enter a VM NAT subnet. Switch the VM network to Bridged mode,'
    Write-Host 'restart networking, then run this check again.'
} else {
    Write-Host ''
    Write-Host "Open this URL on a phone connected to the same Wi-Fi: $url" -ForegroundColor Green
}
