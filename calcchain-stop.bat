@echo off
setlocal

set "STATE_DIR=%LOCALAPPDATA%\CalcChain"
set "NO_PAUSE="
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"

echo Stopping CalcChain...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$stateDir = '%STATE_DIR%'; $pidFiles = @('backend-local.pid','backend-lan.pid','caddy.pid'); foreach ($name in $pidFiles) { $path = Join-Path $stateDir $name; if (Test-Path -LiteralPath $path) { $raw = Get-Content -LiteralPath $path -ErrorAction SilentlyContinue | Select-Object -First 1; $pidValue = 0; if ([int]::TryParse($raw, [ref]$pidValue)) { $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue; if ($process) { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue } }; Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue } }; foreach ($port in @(8765, 8443)) { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 } | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"

echo CalcChain stop request completed.
if not defined NO_PAUSE pause
exit /b 0
