$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$backendPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw 'Python virtual environment not found. See README for setup.'
}

$backendArgs = @(
    '-m', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1',
    '--port', '8000',
    '--reload'
)
Start-Process -FilePath $backendPython `
    -ArgumentList $backendArgs `
    -WorkingDirectory (Join-Path $projectRoot 'backend') `
    -WindowStyle Hidden

Start-Process -FilePath 'npm.cmd' `
    -ArgumentList @('run', 'dev') `
    -WorkingDirectory (Join-Path $projectRoot 'frontend') `
    -WindowStyle Hidden

$activeAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.AddressState -eq 'Preferred' -and
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254*'
    } |
    Sort-Object InterfaceMetric |
    Select-Object -First 1

Write-Host ''
Write-Host 'AI Tech Article Studio started.'
Write-Host 'Computer: http://127.0.0.1:5173'
Write-Host 'API docs: http://127.0.0.1:8000/docs'

if ($activeAddress) {
    $mobileUrl = "http://$($activeAddress.IPAddress):5173"
    $adapter = Get-NetAdapter -InterfaceIndex $activeAddress.InterfaceIndex -ErrorAction SilentlyContinue
    $virtualAdapter = (
        $adapter.InterfaceDescription -match 'VMware|VirtualBox|Hyper-V|Virtual Ethernet' -or
        $adapter.MacAddress -match '^(00-0C-29|00-05-69|00-1C-14|00-50-56|08-00-27)'
    )
    Write-Host "Mobile/LAN candidate: $mobileUrl"
    Write-Host "Network adapter: $($adapter.InterfaceDescription)"
    if ($virtualAdapter) {
        Write-Warning (
            'A virtual network adapter was detected. If the virtual machine uses NAT, ' +
            'phones on the physical Wi-Fi cannot open this address. Switch the VM network ' +
            'to Bridged mode, or configure port forwarding on the host.'
        )
    } else {
        Write-Host 'Keep the phone and computer on the same Wi-Fi, then open the Mobile/LAN URL.'
    }
}
