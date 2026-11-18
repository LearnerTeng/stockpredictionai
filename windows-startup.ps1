param(
    [Parameter(Mandatory)]
    [ValidateSet('Install', 'Uninstall', 'Start', 'Stop', 'Status')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$name = 'StockPredictionAI'
$launcher = Join-Path $PSScriptRoot 'start-all.ps1'
$task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($task -and $task.Actions.Arguments -notlike ('*-File "' + $launcher + '" *')) {
    throw 'A StockPredictionAI task belongs to a different checkout. Inspect it in Task Scheduler.'
}

switch ($Action) {
    'Install' {
        $account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
        $shell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
        $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
            $launcher + '" -Background -Python "' + $python + '"'
        $launch = New-ScheduledTaskAction -Execute $shell -Argument $arguments -WorkingDirectory $PSScriptRoot
        # 登录后延迟启动，为用户会话和 Docker Desktop 留出初始化时间。
        # Delay startup after sign-in to give the user session and Docker Desktop time to initialize.
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
        $trigger.Delay = 'PT30S'
        $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
        $settingsArgs = @{
            MultipleInstances = 'IgnoreNew'; RestartCount = 5; RestartInterval = (New-TimeSpan -Minutes 2)
            ExecutionTimeLimit = [TimeSpan]::Zero; AllowStartIfOnBatteries = $true
            DontStopIfGoingOnBatteries = $true; Hidden = $true
        }
        $settings = New-ScheduledTaskSettingsSet @settingsArgs
        $taskArgs = @{TaskName = $name; Action = $launch; Trigger = $trigger; Principal = $principal; Settings = $settings}
        Register-ScheduledTask @taskArgs -Force | Out-Null
        Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
    }
    'Uninstall' {
        if ($task.State -eq 'Running') { throw 'Run -Action Stop and wait for shutdown first.' }
        if ($task) { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
    }
    'Start' { Start-ScheduledTask -TaskName $name }
    'Stop' { & $launcher -Stop }
    'Status' {
        if ($task) {
            Get-ScheduledTask -TaskName $name | Select-Object TaskName, State, Actions
            Get-ScheduledTaskInfo -TaskName $name
        } else { Write-Output 'StockPredictionAI login task is not installed.' }
    }
}
