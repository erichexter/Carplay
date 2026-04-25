# find-pi.ps1 — scan the local /24 for Raspberry Pi boards.
#
# Ping-sweeps the current subnet (or one you pass in), then reads the
# Windows ARP/neighbor cache and filters for Raspberry Pi Foundation
# OUIs. Prints each hit with IP, MAC, and a best-guess model.
#
# Requires PowerShell 7+ (for Test-Connection -Parallel).
#
# Usage:
#   pwsh .\scripts\find-pi.ps1                   # auto-detect subnet
#   pwsh .\scripts\find-pi.ps1 -Subnet 192.168.1 # force subnet

param(
    [string]$Subnet = "",
    [int]$ThrottleLimit = 64
)

# Raspberry Pi Foundation OUIs. The Foundation reuses OUIs across model
# generations, so the label is a hint, not proof of model.
$PiOuis = @{
    'B8:27:EB' = 'Pi (older: 1 / 2 / 3 / Zero)'
    'DC:A6:32' = 'Pi (4 / CM4 / Zero 2 W)'
    'E4:5F:01' = 'Pi (4 / 400 / CM4)'
    'D8:3A:DD' = 'Pi 5'
    '28:CD:C1' = 'Pi (mixed — 4 / 5)'
    '2C:CF:67' = 'Pi (newer)'
}

if (-not $Subnet) {
    $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Sort-Object -Property RouteMetric | Select-Object -First 1
    if (-not $route) {
        Write-Error "No default route found. Pass -Subnet (e.g. 192.168.1)."
        exit 1
    }
    $localIp = (Get-NetIPAddress -InterfaceIndex $route.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress
    if (-not $localIp) {
        Write-Error "Couldn't read local IPv4 address. Pass -Subnet explicitly."
        exit 1
    }
    $Subnet = ($localIp -split '\.')[0..2] -join '.'
    Write-Host "[scan] local ip: $localIp"
}

Write-Host "[scan] subnet:   $Subnet.0/24"
Write-Host "[scan] ping-sweeping (takes ~15-30s)..."

1..254 | ForEach-Object -Parallel {
    $ip = "$using:Subnet.$_"
    Test-Connection -IPv4 -Count 1 -TimeoutSeconds 1 -Quiet $ip | Out-Null
} -ThrottleLimit $ThrottleLimit

Write-Host "[scan] reading neighbor cache..."
$neighbors = Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -like "$Subnet.*" -and
        $_.LinkLayerAddress -and
        $_.LinkLayerAddress -ne '00-00-00-00-00-00' -and
        $_.State -ne 'Unreachable'
    }

$hits = foreach ($n in $neighbors) {
    $mac = ($n.LinkLayerAddress -replace '-', ':').ToUpper()
    $oui = ($mac -split ':')[0..2] -join ':'
    if ($PiOuis.ContainsKey($oui)) {
        # Best-effort reverse DNS — mDNS-published names (foo.local) won't
        # always show here, but router-assigned hostnames often will.
        $name = try { [System.Net.Dns]::GetHostEntry($n.IPAddress).HostName } catch { '' }
        [pscustomobject]@{
            IP    = $n.IPAddress
            MAC   = $mac
            Guess = $PiOuis[$oui]
            Host  = $name
        }
    }
}

if (-not $hits) {
    Write-Host ""
    Write-Host "[scan] no Raspberry Pi MAC prefixes found on $Subnet.0/24"
    Write-Host "[scan] if the Pi just booted, wait 30s for DHCP and retry"
    Write-Host "[scan] also try:  ssh pi@truckdash.local"
    exit 2
}

Write-Host ""
$hits | Sort-Object { [int](($_.IP -split '\.')[-1]) } | Format-Table -AutoSize
