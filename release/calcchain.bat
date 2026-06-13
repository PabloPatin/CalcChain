@echo off
setlocal

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "PORT=8765"
set "HOST=127.0.0.1"
set "BASE_URL=http://%HOST%:%PORT%/"
set "STATE_DIR=%LOCALAPPDATA%\CalcChain"

for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "DOCUMENTS_DIR=%%D"
if not defined DOCUMENTS_DIR set "DOCUMENTS_DIR=%USERPROFILE%\Documents"
set "PROJECTS_DIR=%DOCUMENTS_DIR%\CalcChainProjects"

call :select_python
if errorlevel 1 exit /b 1

call :ensure_dirs

call :server_local_ready
if errorlevel 3 (
    echo CalcChain backend is running on %BASE_URL%, but the web interface is not available.
    echo Close the existing backend window and start CalcChain again.
    pause
    exit /b 1
)
if errorlevel 2 (
    echo CalcChain is already running on %BASE_URL%, but not in local mode.
    echo Close the existing backend window or use another port.
    pause
    exit /b 1
)
if errorlevel 1 (
    call :start_backend
    call :wait_for_server
    if errorlevel 1 exit /b 1
)

start "" "%BASE_URL%"
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
exit /b 0

:start_backend
set "LOG_DIR=%STATE_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$process = Start-Process -FilePath '%PYTHON_EXE%' -WorkingDirectory '%APP_DIR%' -ArgumentList @('-m','calcchain_backend.cli','serve','--host','%HOST%','--port','%PORT%','--app-root','%APP_DIR%','--state-dir','%STATE_DIR%','--projects-dir','%PROJECTS_DIR%','--plugin-root','%APP_DIR%\plugins','--static-dir','%APP_DIR%\web') -WindowStyle Hidden -RedirectStandardOutput '%LOG_DIR%\backend-local.out.log' -RedirectStandardError '%LOG_DIR%\backend-local.err.log' -PassThru; Set-Content -Path '%STATE_DIR%\backend-local.pid' -Value $process.Id"
exit /b 0

:server_local_ready
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $info = Invoke-RestMethod -TimeoutSec 1 '%BASE_URL%api/server/info'; if ($info.mode -ne 'local') { exit 2 }; $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%BASE_URL%'; if ($page.StatusCode -eq 200) { exit 0 }; exit 3 } catch [System.Net.WebException] { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { exit 3 }; exit 1 } catch { exit 1 }" >nul 2>nul
exit /b %ERRORLEVEL%

:wait_for_server
echo Starting CalcChain...
for /l %%I in (1,1,40) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $info = Invoke-RestMethod -TimeoutSec 1 '%BASE_URL%api/server/info'; if ($info.mode -ne 'local') { exit 2 }; $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%BASE_URL%'; if ($page.StatusCode -eq 200) { exit 0 }; exit 3 } catch [System.Net.WebException] { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { exit 3 }; exit 1 } catch { exit 1 }" >nul 2>nul
    if not errorlevel 1 exit /b 0
    if errorlevel 3 (
        echo CalcChain backend started, but the web interface is not available.
        echo Make sure "%APP_DIR%\web\index.html" exists.
        pause
        exit /b 1
    )
    if errorlevel 2 (
        echo CalcChain backend started, but not in local mode.
        pause
        exit /b 1
    )
    timeout /t 1 /nobreak >nul
)
echo CalcChain backend did not start on %BASE_URL%.
echo Check logs or run the backend command manually.
pause
exit /b 1
