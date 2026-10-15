@echo off
setlocal
rem Temporary workaround for this machine only: exclude logical CPUs 6 and 7.
rem This changes only the launched process affinity, never the system settings.
rem Normal cross-platform startup remains: .venv\Scripts\python.exe tools\run_app.py
if not "%NUMBER_OF_PROCESSORS%"=="32" (
    echo This workaround was verified only for the diagnosed 32-thread machine.
    exit /b 2
)
if not exist "%~dp0.venv\Scripts\python.exe" exit /b 2
start "" /b /wait /affinity FFFFFF3F "%~dp0.venv\Scripts\python.exe" "%~dp0tools\run_app.py"
exit /b %errorlevel%
