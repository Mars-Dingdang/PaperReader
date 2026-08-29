param(
    [string]$TargetPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $TargetPath) {
    $TargetPath = Join-Path $ProjectRoot "dist\PaperReader\PaperReader.exe"
}
$TargetPath = (Resolve-Path -LiteralPath $TargetPath).Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "PaperReader.lnk"
$LocalLauncher = Join-Path $ProjectRoot "desktop\launch_local.ps1"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$LocalLauncher`""
$Shortcut.WorkingDirectory = $ProjectRoot
$IconPath = Join-Path $ProjectRoot "desktop\assets\PaperReader.ico"
$Shortcut.IconLocation = if (Test-Path -LiteralPath $IconPath) { "$IconPath,0" } else { "$TargetPath,0" }
$Shortcut.Description = "PaperReader 英文论文翻译与 AI 文献阅读"
$Shortcut.Save()
Write-Host "Shortcut created: $ShortcutPath"
