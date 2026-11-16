@echo off
REM Jalankan Forensic Evidence Text Search dari source (butuh Python + requirements.txt).
cd /d %~dp0
set TMP=%~dp0_tmp
set TEMP=%~dp0_tmp
if not exist "%TMP%" mkdir "%TMP%"
python main.py
