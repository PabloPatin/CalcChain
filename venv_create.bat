@echo off

set VENV_DIR=.\.venv
set WHEELS_DIR=.\wheels

call :prepare
call :create_venv
call :install_reqs

goto:eof


:prepare
	if not exist "%VENV_DIR%" goto skip_overwrite

	set /p overwrite=Venv directory already exists. Press Enter to overwrite:

	echo Deleting old venv...
	rmdir /S /Q "%VENV_DIR%" || call :error "rmdir failed"

	:skip_overwrite

	mkdir "%VENV_DIR%"
	if errorlevel 1 call :error "mkdir failed"

	goto:eof


:create_venv
	echo Creating virtual env...
	python -m venv "%VENV_DIR%"
	if errorlevel 1 call :error "venv create failed"

	goto:eof


:install_reqs
	echo Activating virtual env...
	call "%VENV_DIR%\Scripts\activate.bat"
	if errorlevel 1 call :error "venv activate failed"

	if not exist "%WHEELS_DIR%" call :error "whl dir not found"

	echo Installing whl packages...
	pip install --no-index --find-links="%WHEELS_DIR%" -r requirements.txt
	if errorlevel 1 call :error "whl packages install failed"

	goto:eof


:error
	echo Error: %~1
	pause
	exit 1
