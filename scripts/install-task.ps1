[CmdletBinding(DefaultParameterSetName = 'Days')]
param(
    [Parameter(ParameterSetName = 'Days')][ValidateRange(1,365)][int]$Days = 2,
    [Parameter(ParameterSetName = 'Days')][ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')][string]$At = '09:00',
    [Parameter(ParameterSetName = 'Minutes', Mandatory = $true)][ValidateRange(5,44640)][int]$Minutes,
    [switch]$Enable
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $root '.venv\Scripts\python.exe'
$worker = Join-Path $root 'scripts\scheduled-run.py'
$config = Join-Path $root 'config.json'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Run install.ps1 first.' }
if ($Enable) {
    $settingsJson = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
    $proofFile = Join-Path $root 'data\wps-inspection\production-readiness.json'
    if (-not (Test-Path -LiteralPath $proofFile)) { throw 'WPS append verification is incomplete. Task must remain disabled.' }
    $proof = Get-Content -LiteralPath $proofFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not ($settingsJson.wps.enabled -and $proof.account_section_append_verified -and $proof.existing_format_preserved -and $proof.writer_implemented)) {
        throw 'WPS writer is not verified. Task must remain disabled.'
    }
}
$action = New-ScheduledTaskAction -Execute $exe -Argument "-X utf8 `"$worker`"" -WorkingDirectory $root
if ($PSCmdlet.ParameterSetName -eq 'Minutes') {
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
} else {
    $existingTask = Get-ScheduledTask -TaskName DouyinViralCollect -ErrorAction SilentlyContinue
    $chinaNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'China Standard Time')
    $taskStart = $chinaNow.Date.AddDays($Days).Add([TimeSpan]::Parse($At))
    $trigger = New-ScheduledTaskTrigger -Daily -DaysInterval $Days -At $taskStart
    $trigger.StartBoundary = $taskStart.ToString("yyyy-MM-dd'T'HH:mm:ss") + '+08:00'
    if ($existingTask -and $existingTask.Triggers.Count -eq 1 -and [int]$existingTask.Triggers[0].DaysInterval -eq $Days -and $existingTask.Triggers[0].StartBoundary -like ('*T' + $At + ':00*')) {
        $trigger.StartBoundary = $existingTask.Triggers[0].StartBoundary
    }
}
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Collect every two days; append only after WPS account-section and formatting verification.'
$definition.Settings.Enabled = [bool]$Enable
Register-ScheduledTask -TaskName DouyinViralCollect -InputObject $definition -Force | Out-Null
$task = Get-ScheduledTask -TaskName DouyinViralCollect
[pscustomobject]@{ TaskName = $task.TaskName; State = [string]$task.State; StartBoundary = $task.Triggers[0].StartBoundary; DaysInterval = $Days } | ConvertTo-Json -Compress