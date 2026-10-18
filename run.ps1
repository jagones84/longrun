# Longrun launcher (Windows): bootstrap the one required dependency, run, and open the WebUI.
# Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Get-Command py -ErrorAction SilentlyContinue
$pyArgs = @("-3")
if (-not $py) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    $pyArgs = @()
}
if (-not $py) {
    Write-Error "Python 3 not found on PATH. Install it from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH')."
    exit 127
}

$versionText = & $py.Source @pyArgs --version 2>&1
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch "Python\s+(\d+)\.(\d+)") {
    Write-Error "Could not read the Python version. Install Python 3.10 or newer."
    exit 2
}
$pythonMajor = [int]$Matches[1]
$pythonMinor = [int]$Matches[2]
if ($pythonMajor -lt 3 -or ($pythonMajor -eq 3 -and $pythonMinor -lt 10)) {
    Write-Error "Longrun requires Python 3.10 or newer. Install it from https://www.python.org/downloads/windows/."
    exit 2
}

& $py.Source @pyArgs -m pip show PyYAML *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the required PyYAML package for this Python..."
    & $py.Source @pyArgs -m pip install --user PyYAML
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Could not install PyYAML. Check your internet connection, then rerun this command."
        exit 3
    }
}

$port = 8790
for ($i = 0; $i -lt $args.Count - 1; $i++) {
    if ($args[$i] -eq "--port") {
        $parsedPort = 0
        if ([int]::TryParse($args[$i + 1], [ref]$parsedPort) -and $parsedPort -gt 0) {
            $port = $parsedPort
        }
    }
}
$url = "http://127.0.0.1:$port/"

# Reuse an already-running instance instead of creating a port-conflict error.
try {
    $ready = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/setup/status" `
        -UseBasicParsing -TimeoutSec 2
    if ($ready.StatusCode -eq 200) {
        Write-Host "Longrun is already running. Opening $url"
        Start-Process $url
        exit 0
    }
} catch {}

$browserJob = $null
if ($env:LONGRUN_NO_BROWSER -ne "1") {
    $browserJob = Start-Job -ArgumentList $url -ScriptBlock {
        param($target)
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            try {
                $ready = Invoke-WebRequest -Uri ($target + "api/setup/status") `
                    -UseBasicParsing -TimeoutSec 2
                if ($ready.StatusCode -eq 200) {
                    Start-Process $target
                    break
                }
            } catch {}
            Start-Sleep -Seconds 1
        }
    }
}

Write-Host "Starting Longrun. Press Ctrl+C in this window to stop it."
$exitCode = 0
try {
    & $py.Source @pyArgs (Join-Path $PSScriptRoot "server.py") @args
    $exitCode = $LASTEXITCODE
} finally {
    if ($browserJob) {
        Stop-Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
exit $exitCode
