@echo off
rem Start the WebUI server in background mode.
rem Logs: logs\webui.log    Stop: stop.bat
rem Options: start.bat --port 9000 --host 0.0.0.0
cd /d "%~dp0"
python ctl.py start %*
if errorlevel 1 pause
