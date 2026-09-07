param(
    [string]$TargetPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $TargetPath) {
    $TargetPath = Join-Path $PSScriptRoot "PaperReader.exe"
    if (-not (Test-Path -LiteralPath $TargetPath)) {
        $TargetPath = Join-Path $ProjectRoot "dist\PaperReader\PaperReader.exe"
    }
}
$TargetPath = (Resolve-Path -LiteralPath $TargetPath).Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "PaperReader.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
$Shortcut.IconLocation = "$TargetPath,0"
$Shortcut.Description = "PaperReader 英文论文翻译与 AI 文献阅读"
$Shortcut.Save()
Write-Host "Shortcut created: $ShortcutPath"
