@echo off
setlocal

set PYTHON_DIR=%~dp0python
set PYTHON_EXE=%PYTHON_DIR%\python.exe
set SITE_PACKAGES=%PYTHON_DIR%\Lib\site-packages

if exist "%SITE_PACKAGES%" rmdir /s /q "%SITE_PACKAGES%"
mkdir "%SITE_PACKAGES%"

uv pip install ^
  --python "%PYTHON_EXE%" ^
  --target "%SITE_PACKAGES%" ^
  --system ^
  pip setuptools wheel ^
  .\packages\core ^
  .\packages\plugin_system ^
  .\apps\backend ^
  packaging ^
  tomlkit ^
  keyring ^
  fastapi ^
  pydantic ^
  "uvicorn[standard]"

"%PYTHON_EXE%" -c "import pip, fastapi, uvicorn, pydantic, packaging, tomlkit, keyring; print('CalcChain embedded runtime ok')"

endlocal