@echo off
rem BQC local web UI launcher (P8). Data goes to %LOCALAPPDATA%\bqc\data\
cd /d "%~dp0"
bqc.exe serve
pause
