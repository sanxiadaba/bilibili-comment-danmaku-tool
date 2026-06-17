$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$port = 8001

Set-Location $root
python backend/server.py --host 127.0.0.1 --port $port
