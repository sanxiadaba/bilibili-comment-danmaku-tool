$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$releaseRoot = Join-Path $root "release"
$appName = "bilibili-comment-danmaku-tool"
$outputDir = Join-Path $releaseRoot $appName
$entry = Join-Path $root "backend\desktop_entry.py"
$distDir = Join-Path $root "dist"

Set-Location $root

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm is required to build the frontend assets."
}

if (-not (Test-Path $entry)) {
    throw "Missing desktop entry: $entry"
}

pnpm build

if (-not (Test-Path (Join-Path $distDir "index.html"))) {
    throw "Frontend dist was not generated."
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
if (Test-Path $outputDir) {
    Remove-Item -Recurse -Force -LiteralPath $outputDir
}

$nuitkaArgs = @(
    "--standalone",
    "--assume-yes-for-downloads",
    "--output-dir=$releaseRoot",
    "--output-filename=$appName.exe",
    "--windows-console-mode=attach",
    "--include-data-dir=$distDir=dist",
    "--include-data-files=$(Join-Path $root 'README.md')=README.md",
    $entry
)

if (Get-Command uvx -ErrorAction SilentlyContinue) {
    uvx --from nuitka nuitka.cmd @nuitkaArgs
} else {
    python -m nuitka @nuitkaArgs
}
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka failed with exit code $LASTEXITCODE"
}

$generatedDir = Join-Path $releaseRoot "desktop_entry.dist"
if (-not (Test-Path $generatedDir)) {
    throw "Nuitka output was not found: $generatedDir"
}

Move-Item -Force -LiteralPath $generatedDir -Destination $outputDir

New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "logs") | Out-Null

$readme = @(
    "# Bilibili Comment Danmaku Tool",
    "",
    "Double-click $appName.exe to start the local service. It opens:",
    "",
    "http://127.0.0.1:8000/",
    "",
    "This is a portable build. Data, cookies, and logs are stored in data/ and logs/ next to the exe."
)
$readme | Set-Content -Encoding UTF8 (Join-Path $outputDir "README.txt")

Write-Host "Built release folder: $outputDir"
