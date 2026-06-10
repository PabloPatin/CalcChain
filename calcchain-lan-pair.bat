@echo off
setlocal

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "BACKEND_PORT=8765"
set "HTTPS_PORT=8443"
set "LOCAL_URL=http://127.0.0.1:%BACKEND_PORT%/"

if defined CALCCHAIN_LAN_IP (
    set "LAN_IP=%CALCCHAIN_LAN_IP%"
) else (
    for /f "usebackq delims=" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ip = $null; try { $socket = [System.Net.Sockets.Socket]::new([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp); $socket.Connect('8.8.8.8', 65530); $ip = $socket.LocalEndPoint.Address.ToString(); $socket.Dispose() } catch {}; if (-not $ip -or $ip -like '127.*' -or $ip -like '169.254.*') { $addresses = [System.Net.Dns]::GetHostEntry([System.Net.Dns]::GetHostName()).AddressList; $ip = $addresses | Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and $_.IPAddressToString -notlike '127.*' -and $_.IPAddressToString -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddressToString }; if (-not $ip) { $ip = '127.0.0.1' }; $ip"`) do set "LAN_IP=%%A"
)
if not defined LAN_IP set "LAN_IP=127.0.0.1"
set "LAN_URL=https://%LAN_IP%:%HTTPS_PORT%/"

call :select_python
if errorlevel 1 exit /b 1

call :server_lan_ready
if errorlevel 2 (
    echo CalcChain is running, but not in LAN mode.
    echo Start CalcChain with calcchain-lan.bat first.
    pause
    exit /b 1
)
if errorlevel 1 (
    echo CalcChain LAN backend is not running.
    echo Start CalcChain with calcchain-lan.bat first.
    pause
    exit /b 1
)

call :pair
if errorlevel 1 exit /b 1

echo.
echo CalcChain LAN pairing code:
echo %PAIRING_CODE%
echo.
echo Open this address from another device in the same LAN:
echo %LAN_URL%
echo.
echo The code is one-time and expires after a few minutes.
echo.
pause
exit /b 0

:select_python
if exist "%APP_DIR%\python\python.exe" (
    set "PYTHON_EXE=%APP_DIR%\python\python.exe"
    exit /b 0
)
if exist "%APP_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
    set "PYTHONPATH=%APP_DIR%\apps\backend\src;%APP_DIR%\packages\core\src;%APP_DIR%\packages\plugin_system\src;%PYTHONPATH%"
    exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    exit /b 0
)
echo Python runtime was not found.
echo Expected "%APP_DIR%\python\python.exe" or Python in PATH.
pause
exit /b 1

:server_lan_ready
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $info = Invoke-RestMethod -TimeoutSec 1 '%LOCAL_URL%api/server/info'; if ($info.mode -eq 'lan') { exit 0 }; exit 2 } catch { exit 1 }" >nul 2>nul
exit /b %ERRORLEVEL%

:pair
for /f "usebackq delims=" %%C in (`"%PYTHON_EXE%" -m calcchain_backend.cli pair 2^>nul`) do set "PAIRING_CODE=%%C"
if not defined PAIRING_CODE (
    echo Could not generate pairing code.
    echo Make sure the LAN backend is running under this Windows user.
    pause
    exit /b 1
)
exit /b 0
