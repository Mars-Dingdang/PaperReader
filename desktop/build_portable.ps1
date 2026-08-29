param(
    [string]$NpmPath = "",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $NpmPath) {
    $NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $NpmCommand) {
        $NpmCommand = Get-Command npm -ErrorAction SilentlyContinue
    }
    if (-not $NpmCommand) {
        throw "npm was not found. Install Node.js or pass -NpmPath explicitly."
    }
    $NpmPath = $NpmCommand.Source
}

if (-not $PythonPath) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $PythonCommand) {
        throw "Python was not found. Install Python or pass -PythonPath explicitly."
    }
    $PythonPath = $PythonCommand.Source
}

Push-Location (Join-Path $ProjectRoot "frontend")
try {
    & $NpmPath run build
} finally {
    Pop-Location
}

& $PythonPath -m PyInstaller --clean --noconfirm (Join-Path $ProjectRoot "desktop\PaperReader.spec")

$PortableDir = Join-Path $ProjectRoot "dist\PaperReader"
Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $PortableDir "config.env") -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "desktop\README_zh.md") -Destination (Join-Path $PortableDir "使用说明.txt") -Force

$ReleaseDir = Join-Path $ProjectRoot "release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$ZipPath = Join-Path $ReleaseDir "PaperReader-Windows-x64.zip"
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PortableDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "Portable package: $ZipPath"
