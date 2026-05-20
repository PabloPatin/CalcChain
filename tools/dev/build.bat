@echo off

set VENV_DIR=.\.venv
set BUILD_DIR=.\_BUILD
set SPEC_FILE=tools\dev\build.spec

call %VENV_DIR%\Scripts\activate.bat
if errorlevel 1 echo ERROR & pause & exit 1

pyinstaller --distpath %BUILD_DIR%\dist --workpath %BUILD_DIR%\build --noconfirm --clean %SPEC_FILE%
if errorlevel 1 echo ERROR & pause & exit 1
