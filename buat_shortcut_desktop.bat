@echo off
REM ============================================================================
REM  Membuat ikon "Cyber Forensic Evidence Search" di Desktop (versi source code),
REM  supaya aplikasi bisa dibuka dengan double-click tanpa jendela CMD.
REM  Cukup dijalankan SEKALI. (Versi installer sudah membuat ikon Desktop sendiri.)
REM  Opsional: buat_shortcut_desktop.bat "D:\folder\tujuan"  -> buat shortcut di folder lain
REM ============================================================================
setlocal
cd /d "%~dp0"

set "PYW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PYW if exist "%%~dpPpythonw.exe" set "PYW=%%~dpPpythonw.exe"
    )
)
if not defined PYW (
    echo [GAGAL] Python tidak ditemukan. Install Python 3.11 terlebih dahulu ^(lihat README^).
    pause
    exit /b 1
)

set "TARGET_DIR=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = if ('%TARGET_DIR%') { '%TARGET_DIR%' } else { [Environment]::GetFolderPath('Desktop') };" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Cyber Forensic Evidence Search.lnk'));" ^
  "$s.TargetPath = '%PYW%';" ^
  "$s.Arguments = '\"%~dp0main.py\"';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.IconLocation = '%~dp0assets\app.ico';" ^
  "$s.Description = 'Cyber Forensic Evidence Search - karya Alfin Aqila Muzaki';" ^
  "$s.Save(); Write-Host ('Shortcut dibuat: ' + (Join-Path $d 'Cyber Forensic Evidence Search.lnk'))"
if errorlevel 1 (
    echo [GAGAL] Shortcut tidak dapat dibuat.
) else (
    echo Selesai. Buka aplikasi lewat ikon "Cyber Forensic Evidence Search" di Desktop.
)
if "%~1"=="" pause
