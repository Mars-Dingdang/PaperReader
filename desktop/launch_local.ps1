param(
    [switch]$NoWindow
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Executable = Join-Path $ProjectRoot "dist\PaperReader\PaperReader.exe"
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "PaperReader.exe not found: $Executable"
}
$env:PAPERREADER_ENV_FILE = Join-Path $ProjectRoot ".env"
$env:DATA_DIR = Join-Path $ProjectRoot "data"
if ($NoWindow) {
    $env:PAPERREADER_NO_WINDOW = "1"
}

$Process = Start-Process -FilePath $Executable -WorkingDirectory (Split-Path -Parent $Executable) -WindowStyle Hidden -PassThru
Write-Output $Process.Id
