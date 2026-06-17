$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$releaseRoot = Join-Path $root "release"
$appName = "bilibili-comment-danmaku-tool"
$outputDir = Join-Path $releaseRoot $appName
$internalDir = Join-Path $outputDir "_internal"
$entry = Join-Path $root "backend\desktop_entry.py"
$distDir = Join-Path $root "dist"
$outputExe = Join-Path $outputDir "$appName.exe"
$iconSource = Join-Path $root "assets\app-icon.png"
$iconPath = Join-Path $env:TEMP "bilibili-comment-danmaku-tool.ico"

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

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

function Convert-PngToIcon {
    param([string]$PngFile, [string]$IconFile)

    if (-not (Test-Path $PngFile)) {
        throw "Missing icon source: $PngFile"
    }
    $source = [System.Drawing.Image]::FromFile($PngFile)
    $frames = New-Object System.Collections.Generic.List[object]
    $stream = [System.IO.File]::Create($IconFile)
    $writer = New-Object System.IO.BinaryWriter($stream)
    try {
        foreach ($size in @(256, 128, 64, 48, 32, 16)) {
            $bitmap = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $memory = New-Object System.IO.MemoryStream
            try {
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $graphics.Clear([System.Drawing.Color]::Transparent)
                $graphics.DrawImage($source, 0, 0, $size, $size)
                $bitmap.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png)
                $frames.Add([PSCustomObject]@{
                    Size = [int]$size
                    Data = $memory.ToArray()
                }) | Out-Null
            } finally {
                $memory.Dispose()
                $graphics.Dispose()
                $bitmap.Dispose()
            }
        }

        $writer.Write([UInt16]0)
        $writer.Write([UInt16]1)
        $writer.Write([UInt16]$frames.Count)
        $offset = 6 + (16 * $frames.Count)
        foreach ($frame in $frames) {
            $sizeByte = if ($frame.Size -eq 256) { 0 } else { $frame.Size }
            $writer.Write([byte]$sizeByte)
            $writer.Write([byte]$sizeByte)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([UInt16]1)
            $writer.Write([UInt16]32)
            $writer.Write([UInt32]$frame.Data.Length)
            $writer.Write([UInt32]$offset)
            $offset += $frame.Data.Length
        }
        foreach ($frame in $frames) {
            $writer.Write([byte[]]$frame.Data)
        }
    } finally {
        $writer.Dispose()
        $stream.Dispose()
        $source.Dispose()
    }
}

Convert-PngToIcon -PngFile $iconSource -IconFile $iconPath

$nuitkaArgs = @(
    "--standalone",
    "--assume-yes-for-downloads",
    "--output-dir=$releaseRoot",
    "--output-filename=$appName.exe",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=$iconPath",
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
using System.Runtime.InteropServices;
using System.Threading;
using System.Drawing;
using System.Windows.Forms;

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        return Launcher.Run(args);
    }
}

class Launcher
{
    [DllImport("kernel32.dll")]
    static extern bool FreeConsole();

    public static int Run(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string target = Path.Combine(root, "_internal", "$appName.exe");
        if (!File.Exists(target))
        {
            MessageBox.Show("Missing runtime executable: " + target, "Bilibili Comment Danmaku Tool", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        if (args.Length > 0 && IsCliMode(args[0]))
        {
            string[] forwarded = BuildForwardedArgs(args);
            return RunConsole(target, root, forwarded);
        }
        FreeConsole();
        string url = "http://127.0.0.1:8001/";
        string logPath = Path.Combine(root, "logs", "app.jsonl");
        var startInfo = new ProcessStartInfo
        {
            FileName = target,
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            Arguments = string.Join(" ", args.Select(Quote)),
        };
        using (var process = Process.Start(startInfo))
        {
            if (process == null)
            {
                MessageBox.Show("Failed to start local service.", "Bilibili Comment Danmaku Tool", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            using (var form = new StatusForm(process, url, logPath))
            {
                Application.Run(form);
            }
            if (!process.HasExited)
            {
                try { process.Kill(); } catch { }
            }
            return process.HasExited ? process.ExitCode : 0;
        }
    }

    static string Quote(string value)
    {
        if (string.IsNullOrEmpty(value)) return "\"\"";
        if (value.IndexOfAny(new[] { ' ', '\t', '\n', '\r', '"' }) < 0) return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }

    static bool IsCliMode(string value)
    {
        string mode = (value ?? "").Trim().ToLowerInvariant();
        return mode == "cli" || mode == "serve" || mode == "server" || mode == "--help" || mode == "-h";
    }

    static string[] BuildForwardedArgs(string[] args)
    {
        string mode = (args[0] ?? "").Trim().ToLowerInvariant();
        if (mode == "cli")
        {
            return new[] { "--cli" }.Concat(args.Skip(1)).ToArray();
        }
        if (mode == "serve" || mode == "server")
        {
            return args.Skip(1).ToArray();
        }
        return new[] { "--cli", "--help" };
    }

    static int RunConsole(string target, string root, string[] args)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = target,
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            Arguments = string.Join(" ", args.Select(Quote)),
        };
        using (var process = Process.Start(startInfo))
        {
            if (process == null) return 1;
            ConsoleCancelEventHandler cancelHandler = (sender, eventArgs) =>
            {
                try
                {
                    if (!process.HasExited) process.Kill();
                }
                catch { }
            };
            Console.CancelKeyPress += cancelHandler;
            try
            {
                var stdoutThread = new Thread(() => process.StandardOutput.BaseStream.CopyTo(Console.OpenStandardOutput()));
                var stderrThread = new Thread(() => process.StandardError.BaseStream.CopyTo(Console.OpenStandardError()));
                stdoutThread.Start();
                stderrThread.Start();
                process.WaitForExit();
                stdoutThread.Join();
                stderrThread.Join();
                return process.ExitCode;
            }
            finally
            {
                Console.CancelKeyPress -= cancelHandler;
            }
        }
    }

}

class StatusForm : Form
{
    readonly Process process;
    readonly Label statusLabel;
    readonly LinkLabel urlLink;
    readonly Label logLabel;

    public StatusForm(Process process, string url, string logPath)
    {
        this.process = process;
        Text = "Bilibili Comment Danmaku Tool";
        Width = 520;
        Height = 230;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = true;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        statusLabel = new Label
        {
            Text = "Starting local service. The browser will open shortly.",
            Left = 24,
            Top = 24,
            Width = 450,
            Height = 26,
            Font = new Font(Font.FontFamily, 10, FontStyle.Bold)
        };
        urlLink = new LinkLabel
        {
            Text = url,
            Left = 24,
            Top = 62,
            Width = 450,
            Height = 26
        };
        urlLink.LinkClicked += (sender, eventArgs) => Process.Start(new ProcessStartInfo(urlLink.Text) { UseShellExecute = true });

        logLabel = new Label
        {
            Text = "Logs: " + logPath,
            Left = 24,
            Top = 100,
            Width = 450,
            Height = 42
        };
        var closeButton = new Button
        {
            Text = "Stop service and exit",
            Left = 330,
            Top = 148,
            Width = 145,
            Height = 32
        };
        closeButton.Click += (sender, eventArgs) => Close();

        Controls.Add(statusLabel);
        Controls.Add(urlLink);
        Controls.Add(logLabel);
        Controls.Add(closeButton);

        process.OutputDataReceived += (sender, eventArgs) =>
        {
            string line = eventArgs.Data ?? "";
            if (line.StartsWith("Open: ", StringComparison.OrdinalIgnoreCase))
            {
                string actualUrl = line.Substring("Open: ".Length).Trim();
                BeginInvoke((Action)(() =>
                {
                    urlLink.Text = actualUrl;
                    statusLabel.Text = "Service started. Browser URL:";
                }));
            }
        };
        process.ErrorDataReceived += (sender, eventArgs) => { };

        var timer = new System.Windows.Forms.Timer { Interval = 1000 };
        timer.Tick += (sender, eventArgs) =>
        {
            if (process.HasExited)
            {
                statusLabel.Text = "Service has exited.";
                timer.Stop();
            }
            else
            {
                statusLabel.Text = "Service started. Browser URL:";
            }
        };
        timer.Start();
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
    }
}
"@
$launcherCode | Set-Content -Encoding UTF8 $launcherSource
$frameworkDir = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319"
$csc = Join-Path $frameworkDir "csc.exe"
if (-not (Test-Path $csc)) {
    $frameworkDir = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319"
    $csc = Join-Path $frameworkDir "csc.exe"
}
if (-not (Test-Path $csc)) {
    throw "C# compiler was not found."
}
& $csc /nologo /target:exe /win32icon:"$iconPath" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /out:"$outputExe" "$launcherSource"
if ($LASTEXITCODE -ne 0) {
    throw "Launcher compilation failed with exit code $LASTEXITCODE"
}
Remove-Item -Force -LiteralPath $launcherSource

New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "logs") | Out-Null

foreach ($leftover in @("desktop_entry.build", "desktop_entry.dist", "desktop_entry.onefile-build", "data")) {
    $leftoverPath = Join-Path $releaseRoot $leftover
    if (Test-Path $leftoverPath) {
        Remove-Item -Recurse -Force -LiteralPath $leftoverPath
    }
}
if (Test-Path $iconPath) {
    Remove-Item -Force -LiteralPath $iconPath
}

Write-Host "Built release folder: $outputDir"
