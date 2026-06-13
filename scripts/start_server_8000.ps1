$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$port = 8000

$connections = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
$owners = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($ownerPid in $owners) {
    if ($ownerPid) {
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
    }
}

Set-Location $root
python backend/server.py --host 127.0.0.1 --port $port
