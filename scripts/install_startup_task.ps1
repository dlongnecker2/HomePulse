param(
    [string]$TaskName = "HomePulse"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Resolve-Path (Join-Path $ScriptDir "..")
$Launcher = Join-Path $ProjectDir "scripts\start_homepulse.bat"
$LogDir = Join-Path $ProjectDir "logs"

if (-not (Test-Path $Launcher)) {
    throw "Launcher not found: $Launcher"
}

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$Action = New-ScheduledTaskAction -Execute $Launcher -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Start HomePulse at Windows user logon." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "Action: $Launcher"
Write-Host "Start in: $ProjectDir"
Write-Host "Startup log: $(Join-Path $LogDir 'startup.log')"
