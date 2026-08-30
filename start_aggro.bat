@echo off
cd /d "%~dp0"

start /min "" wscript.exe //nologo "%~dp0start_aggro.vbs"

exit /b 0
