<#
.SYNOPSIS
    Creates a Desktop shortcut that launches the GMU Course Search menu.

.DESCRIPTION
    Points a .lnk at gmu-menu.bat in this same directory. Re-running is safe —
    it overwrites the existing shortcut rather than creating duplicates.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-shortcut.ps1
#>

$ErrorActionPreference = 'Stop'

$bat = Join-Path $PSScriptRoot 'gmu-menu.bat'
if (-not (Test-Path $bat)) {
    Write-Error "Can't find gmu-menu.bat next to this script (looked in $PSScriptRoot)."
}

$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'GMU Course Search.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $bat
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Search GMU course offerings and plan your schedule'
$shortcut.WindowStyle = 1
# Graduation-cap-ish icon from the shell library; swap for your own .ico if you like.
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$shortcut.Save()

Write-Host "Created shortcut: $linkPath" -ForegroundColor Green
Write-Host "Double-click it to open the interactive menu."
