@echo off
setlocal

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "BACKEND_PORT=8765"
set "HTTPS_PORT=8443"
set "STATE_DIR=%LOCALAPPDATA%\CalcChain"
set "CADDY_EXE=%APP_DIR%\caddy\caddy.exe"
set "CADDYFILE=%APP_DIR%\caddy\Caddyfile.lan"
set "CADDY_STORAGE=%STATE_DIR%\caddy"

for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "DOCUMENTS_DIR=%%D"
if not defined DOCUMENTS_DIR set "DOCUMENTS_DIR=%USERPROFILE%\Documents"
set "PROJECTS_DIR=%DOCUMENTS_DIR%\CalcChainProjects"

if defined CALCCHAIN_LAN_IP (
    set "LAN_IP=%CALCCHAIN_LAN_IP%"
) else (
    for /f "usebackq delims=" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ip = $null; try { $socket = [System.Net.Sockets.Socket]::new([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp); $socket.Connect('8.8.8.8', 65530); $ip = $socket.LocalEndPoint.Address.ToString(); $socket.Dispose() } catch {}; if (-not $ip -or $ip -like '127.*' -or $ip -like '169.254.*') { $addresses = [System.Net.Dns]::GetHostEntry([System.Net.Dns]::GetHostName()).AddressList; $ip = $addresses | Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and $_.IPAddressToString -notlike '127.*' -and $_.IPAddressToString -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddressToString }; if (-not $ip) { $ip = '127.0.0.1' }; $ip"`) do set "LAN_IP=%%A"
)
if not defined LAN_IP set "LAN_IP=127.0.0.1"

set "LOCAL_URL=http://127.0.0.1:%BACKEND_PORT%/"
set "LAN_URL=https://%LAN_IP%:%HTTPS_PORT%/"

call :select_python
if errorlevel 1 exit /b 1

call :ensure_dirs

call :server_lan_ready
if errorlevel 3 (
    echo CalcChain backend is running on %LOCAL_URL%, but the web interface is not available.
    echo Close the existing backend window and start CalcChain LAN mode again.
    pause
    exit /b 1
)
if errorlevel 2 (
    echo CalcChain is already running on %LOCAL_URL%, but not in LAN mode.
    echo Close the existing backend window or use another port.
    pause
    exit /b 1
)
if errorlevel 1 (
    call :start_backend
    call :wait_for_server
    if errorlevel 1 exit /b 1
)

call :https_ready
if errorlevel 1 (
    call :start_caddy
    call :wait_for_https
    if errorlevel 1 exit /b 1
)

call :pair
if errorlevel 1 exit /b 1

echo.
echo CalcChain LAN mode is running.
echo.
echo Open this address from another device in the same LAN:
echo %LAN_URL%
echo.
echo Pairing code:
echo %PAIRING_CODE%
echo.
echo The code is one-time and expires after a few minutes.
echo To generate another code later, run calcchain-lan-pair.bat.
echo The HTTPS certificate is self-signed. The browser may ask you to confirm it.
echo Keep this window open while users connect.
echo.
start "" "%LAN_URL%"
pause
call "%APP_DIR%\calcchain-stop.bat" --no-pause
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

:ensure_dirs
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%" >nul 2>nul
if not exist "%PROJECTS_DIR%" mkdir "%PROJECTS_DIR%" >nul 2>nul
if not exist "%CADDY_STORAGE%" mkdir "%CADDY_STORAGE%" >nul 2>nul
exit /b 0

:start_backend
set "LOG_DIR=%STATE_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$process = Start-Process -FilePath '%PYTHON_EXE%' -WorkingDirectory '%APP_DIR%' -ArgumentList @('-m','calcchain_backend.cli','serve','--lan','--lan-bind-local','--host','127.0.0.1','--port','%BACKEND_PORT%','--app-root','%APP_DIR%','--state-dir','%STATE_DIR%','--projects-dir','%PROJECTS_DIR%','--plugin-root','%APP_DIR%\plugins','--static-dir','%APP_DIR%\web') -WindowStyle Hidden -RedirectStandardOutput '%LOG_DIR%\backend-lan.out.log' -RedirectStandardError '%LOG_DIR%\backend-lan.err.log' -PassThru; Set-Content -Path '%STATE_DIR%\backend-lan.pid' -Value $process.Id"
exit /b 0

:start_caddy
if not exist "%CADDY_EXE%" (
    echo Caddy executable was not found: "%CADDY_EXE%"
    pause
    exit /b 1
)
if not exist "%CADDYFILE%" (
    echo Caddy config was not found: "%CADDYFILE%"
    pause
    exit /b 1
)
set "CALCCHAIN_LAN_HOST=%LAN_IP%"
set "CALCCHAIN_HTTPS_PORT=%HTTPS_PORT%"
set "CALCCHAIN_BACKEND_PORT=%BACKEND_PORT%"
set "CALCCHAIN_CADDY_STORAGE=%CADDY_STORAGE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$process = Start-Process -FilePath '%CADDY_EXE%' -WorkingDirectory '%APP_DIR%' -ArgumentList @('run','--config','%CADDYFILE%','--adapter','caddyfile') -WindowStyle Hidden -RedirectStandardOutput '%LOG_DIR%\caddy.out.log' -RedirectStandardError '%LOG_DIR%\caddy.err.log' -PassThru; Set-Content -Path '%STATE_DIR%\caddy.pid' -Value $process.Id"
exit /b 0

:server_lan_ready
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $info = Invoke-RestMethod -TimeoutSec 1 '%LOCAL_URL%api/server/info'; if ($info.mode -ne 'lan') { exit 2 }; $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%LOCAL_URL%'; if ($page.StatusCode -eq 200) { exit 0 }; exit 3 } catch [System.Net.WebException] { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { exit 3 }; exit 1 } catch { exit 1 }" >nul 2>nul
exit /b %ERRORLEVEL%

:https_ready
curl.exe -k -s -o nul -w "%%{http_code}" "%LAN_URL%" | findstr /r "^200$" >nul 2>nul
exit /b %ERRORLEVEL%

:wait_for_server
echo Starting CalcChain LAN backend...
for /l %%I in (1,1,40) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $info = Invoke-RestMethod -TimeoutSec 1 '%LOCAL_URL%api/server/info'; if ($info.mode -ne 'lan') { exit 2 }; $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%LOCAL_URL%'; if ($page.StatusCode -eq 200) { exit 0 }; exit 3 } catch [System.Net.WebException] { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { exit 3 }; exit 1 } catch { exit 1 }" >nul 2>nul
    if not errorlevel 1 exit /b 0
    if errorlevel 3 (
        echo CalcChain backend started, but the web interface is not available.
        echo Make sure "%APP_DIR%\web\index.html" exists.
        pause
        exit /b 1
    )
    if errorlevel 2 (
        echo CalcChain backend started, but not in LAN mode.
        pause
        exit /b 1
    )
    timeout /t 1 /nobreak >nul
)
echo CalcChain backend did not start on %LOCAL_URL%.
echo Check logs or run the backend command manually.
pause
exit /b 1

:wait_for_https
echo Starting CalcChain HTTPS proxy...
for /l %%I in (1,1,40) do (
    curl.exe -k -s -o nul -w "%%{http_code}" "%LAN_URL%" | findstr /r "^200$" >nul 2>nul
    if not errorlevel 1 exit /b 0
    timeout /t 1 /nobreak >nul
)
echo CalcChain HTTPS proxy did not start on %LAN_URL%.
echo Check that port %HTTPS_PORT% is free and Windows Firewall allows Caddy.
pause
exit /b 1

:pair
for /f "usebackq delims=" %%C in (`"%PYTHON_EXE%" -m calcchain_backend.cli pair 2^>nul`) do set "PAIRING_CODE=%%C"
if not defined PAIRING_CODE (
    echo Could not generate pairing code.
    echo Make sure the LAN backend is running under this Windows user.
    pause
    exit /b 1
)
exit /b 0
