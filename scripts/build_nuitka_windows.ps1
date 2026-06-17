$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$releaseRoot = Join-Path $root "release"
$appName = "bilibili-comment-danmaku-tool"
$outputDir = Join-Path $releaseRoot $appName
$internalDir = Join-Path $outputDir "_internal"
$entry = Join-Path $root "backend\desktop_entry.py"
$distDir = Join-Path $root "dist"
$outputExe = Join-Path $outputDir "$appName.exe"
$iconPath = Join-Path $releaseRoot "bilibili-tool.ico"

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

function New-BilibiliIcon {
    param([string]$IconFile)

    $bitmap = New-Object System.Drawing.Bitmap 256, 256
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $pink = [System.Drawing.Color]::FromArgb(255, 251, 114, 153)
    $white = [System.Drawing.Color]::White
    $dark = [System.Drawing.Color]::FromArgb(255, 62, 48, 58)
    $bodyBrush = New-Object System.Drawing.SolidBrush $pink
    $whiteBrush = New-Object System.Drawing.SolidBrush $white
    $darkBrush = New-Object System.Drawing.SolidBrush $dark
    $pen = New-Object System.Drawing.Pen $white, 14
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round

    $bodyPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $diameter = 68
    $bodyPath.AddArc(34, 58, $diameter, $diameter, 180, 90)
    $bodyPath.AddArc(154, 58, $diameter, $diameter, 270, 90)
    $bodyPath.AddArc(154, 132, $diameter, $diameter, 0, 90)
    $bodyPath.AddArc(34, 132, $diameter, $diameter, 90, 90)
    $bodyPath.CloseFigure()
    $graphics.FillPath($bodyBrush, $bodyPath)
    $graphics.DrawLine($pen, 82, 62, 54, 28)
    $graphics.DrawLine($pen, 174, 62, 202, 28)
    $graphics.FillEllipse($whiteBrush, 70, 100, 36, 36)
    $graphics.FillEllipse($whiteBrush, 150, 100, 36, 36)
    $graphics.FillEllipse($darkBrush, 84, 114, 10, 10)
    $graphics.FillEllipse($darkBrush, 164, 114, 10, 10)
    $graphics.FillRectangle($whiteBrush, 92, 162, 72, 10)

    $icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
    $stream = [System.IO.File]::Create($IconFile)
    try {
        $icon.Save($stream)
    } finally {
        $stream.Dispose()
        $icon.Dispose()
        $bodyPath.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

New-BilibiliIcon -IconFile $iconPath

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
    public static int Run(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string target = Path.Combine(root, "_internal", "$appName.exe");
        if (!File.Exists(target))
        {
            MessageBox.Show("Missing runtime executable: " + target, "Bilibili Comment Danmaku Tool", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
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

        var timer = new Timer { Interval = 1000 };
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
& $csc /nologo /target:winexe /win32icon:"$iconPath" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /out:"$outputExe" "$launcherSource"
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
