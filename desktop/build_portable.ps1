param(
    [string]$NpmPath = "",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = (Get-Content (Join-Path $ProjectRoot "frontend\package.json") -Raw | ConvertFrom-Json).version

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
    & $NpmPath ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    & $NpmPath run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally {
    Pop-Location
}

& $PythonPath -m PyInstaller --clean --noconfirm --distpath (Join-Path $ProjectRoot "dist") --workpath (Join-Path $ProjectRoot "build") (Join-Path $ProjectRoot "desktop\PaperReader.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$PortableDir = Join-Path $ProjectRoot "dist\PaperReader"
Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $PortableDir "config.env") -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "desktop\README_zh.md") -Destination (Join-Path $PortableDir "使用说明.txt") -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "desktop\create_shortcut.ps1") -Destination $PortableDir -Force

$ReleaseDir = Join-Path $ProjectRoot "release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$ZipPath = Join-Path $ReleaseDir "PaperReader-v$Version-Windows-x64.zip"
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PortableDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
$Hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLower()
"$Hash  $([IO.Path]::GetFileName($ZipPath))" | Set-Content -Encoding ascii -Path "$ZipPath.sha256"
Write-Host "Portable package: $ZipPath"
