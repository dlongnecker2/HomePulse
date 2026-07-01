@echo off
setlocal

set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"

if not exist logs mkdir logs

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if exist "venv\Scripts\python.exe" set "PYTHON_EXE=venv\Scripts\python.exe"

echo [%date% %time%] Starting HomePulse with %PYTHON_EXE% >> logs\startup.log
"%PYTHON_EXE%" router_monitor.py >> logs\startup.log 2>&1
echo [%date% %time%] HomePulse exited with code %ERRORLEVEL% >> logs\startup.log

popd
endlocal
