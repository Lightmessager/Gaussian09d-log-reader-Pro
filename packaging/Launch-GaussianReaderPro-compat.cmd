@echo off
setlocal
cd /d "%~dp0"
start "" /b /wait /affinity FFFFFF3F "%~dp0GaussianReaderPro.exe" %*
exit /b %errorlevel%
