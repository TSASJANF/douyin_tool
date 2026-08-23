@echo off
rem Restart the WebUI server.
rem Options: restart.bat --port 9000 --host 0.0.0.0
cd /d "%~dp0"
python ctl.py restart %*
if errorlevel 1 pause
