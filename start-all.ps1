param(
    [switch]$Stop,
    [switch]$Background,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if ($Stop) {
        & $Python backend/scripts/start_all.py --stop
    } elseif ($Background) {
        $logDir = Join-Path $PSScriptRoot 'backend/local_data/supervisor'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $processArgs = @{
            FilePath = $Python
            ArgumentList = @('backend/scripts/start_all.py')
            WorkingDirectory = $PSScriptRoot
            WindowStyle = 'Hidden'
            RedirectStandardOutput = Join-Path $logDir 'launcher.log'
            RedirectStandardError = Join-Path $logDir 'launcher-error.log'
        }
        $launcherProcess = Start-Process @processArgs -PassThru -Wait
        exit $launcherProcess.ExitCode
    } else {
        & $Python backend/scripts/start_all.py
    }
    $startupExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $startupExitCode
