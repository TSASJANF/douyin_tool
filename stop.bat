@echo off
rem Stop the WebUI server.
cd /d "%~dp0"
python ctl.py stop
if errorlevel 1 pause
