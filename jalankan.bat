@echo off
REM ============================================================================
REM  Jalankan Cyber Forensic Evidence Search dari source code TANPA jendela CMD.
REM  Memakai pythonw.exe (Python versi tanpa konsol); jendela ini menutup sendiri.
REM  Error (bila ada) ditampilkan sebagai pesan dan dicatat di
REM  DATA_ANALISIS\app_error.log.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "TMP=%~dp0_tmp"
set "TEMP=%~dp0_tmp"
if not exist "%TMP%" mkdir "%TMP%"

set "PYW="
REM 1) virtual environment project (bila dibuat sesuai README)
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
REM 2) pythonw.exe di folder yang sama dengan python.exe yang aktif di PATH
if not defined PYW (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PYW if exist "%%~dpPpythonw.exe" set "PYW=%%~dpPpythonw.exe"
    )
)
if not defined PYW (
    echo [GAGAL] Python tidak ditemukan. Install Python 3.11 lalu requirements.txt ^(lihat README^),
    echo         atau gunakan versi installer yang tidak membutuhkan Python.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0main.py"
exit /b 0
