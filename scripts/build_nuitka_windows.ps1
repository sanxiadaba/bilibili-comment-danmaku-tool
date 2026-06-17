$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$releaseRoot = Join-Path $root "release"
$appName = "bilibili-comment-danmaku-tool"
$outputDir = Join-Path $releaseRoot $appName
$internalDir = Join-Path $outputDir "_internal"
$entry = Join-Path $root "backend\desktop_entry.py"
$distDir = Join-Path $root "dist"
$outputExe = Join-Path $outputDir "$appName.exe"

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

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
Move-Item -Force -LiteralPath $generatedDir -Destination $internalDir

$launcherSource = Join-Path $releaseRoot "launcher.cs"
$launcherCode = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;

class Launcher
{
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string target = Path.Combine(root, "_internal", "$appName.exe");
        if (!File.Exists(target))
        {
            Console.Error.WriteLine("Missing runtime executable: " + target);
            return 1;
        }
        var startInfo = new ProcessStartInfo
        {
            FileName = target,
            WorkingDirectory = root,
            UseShellExecute = false,
            Arguments = string.Join(" ", args.Select(Quote)),
        };
        using (var process = Process.Start(startInfo))
        {
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    static string Quote(string value)
    {
        if (string.IsNullOrEmpty(value)) return "\"\"";
        if (value.IndexOfAny(new[] { ' ', '\t', '\n', '\r', '"' }) < 0) return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
"@
$launcherCode | Set-Content -Encoding UTF8 $launcherSource
Add-Type -TypeDefinition $launcherCode -OutputAssembly $outputExe -OutputType ConsoleApplication
Remove-Item -Force -LiteralPath $launcherSource

New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "logs") | Out-Null

foreach ($leftover in @("desktop_entry.build", "desktop_entry.dist", "desktop_entry.onefile-build", "data")) {
    $leftoverPath = Join-Path $releaseRoot $leftover
    if (Test-Path $leftoverPath) {
        Remove-Item -Recurse -Force -LiteralPath $leftoverPath
    }
}

Write-Host "Built release folder: $outputDir"
