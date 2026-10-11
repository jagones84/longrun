<#
  Open the Longrun WebUI in a SECURE context so the browser microphone works.

  Why: the app is served over plain HTTP on a LAN IP (e.g. http://192.168.1.37:8790).
  Browsers treat that as an INSECURE origin, so the Web Speech API and getUserMedia
  are blocked (the 🎙 button explains this). `http://localhost` IS a secure context,
  so forwarding the DGX port to localhost makes voice input work natively.

  Usage (from a Windows PowerShell):
      scripts\open-ui-voice.ps1                 # tunnels to ssh host "dgx" on 8790
      scripts\open-ui-voice.ps1 -SshHost dgx_eth
      scripts\open-ui-voice.ps1 -Port 8790
  Or just double-click scripts\open-ui-voice.bat

  Keep this window open while you use the UI; press Enter to close the tunnel.
#>
param(
  [string]$SshHost = "dgx",
  [int]$Port = 8790
)
$ErrorActionPreference = "Stop"

Write-Host "Opening a localhost tunnel to '$SshHost' on port $Port ..." -ForegroundColor Cyan
Write-Host "(the token may be requested once by the page)" -ForegroundColor DarkGray

$tunnel = Start-Process ssh `
  -ArgumentList "-N", "-o", "ExitOnForwardFailure=yes", "-L", "$($Port):localhost:$($Port)", $SshHost `
  -PassThru

Start-Sleep -Seconds 2
Start-Process "http://localhost:$Port/"

Write-Host "Browser opened at http://localhost:$Port/  —  voice input is now allowed (secure context)." -ForegroundColor Green
Write-Host "Press Enter to stop the tunnel."
[void][System.Console]::ReadLine()

Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
Write-Host "Tunnel closed." -ForegroundColor DarkGray
