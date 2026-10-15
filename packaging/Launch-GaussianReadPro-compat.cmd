@echo off
rem Local workaround for the documented default-scheduler crash on this host.
rem The affinity mask applies only to this app and its child processes.
start "" /b /wait /affinity FFFFFF3F "%~dp0GaussianReadPro.exe" %*
