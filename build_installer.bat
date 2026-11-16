@echo off
REM ============================================================================
REM  Membuat installer Setup.exe dari hasil build_exe.bat.
REM  Butuh Inno Setup 6 (gratis): winget install JRSoftware.InnoSetup
REM  Hasil: installer_output\CyberForensicEvidenceSearch-Setup-v*.exe + *.bin
REM  Opsi: set NOPAUSE=1 agar tidak berhenti di akhir.
REM ============================================================================
setlocal
cd /d %~dp0

if not exist "dist\ForensicEvidenceSearch\ForensicEvidenceSearch.exe" (
    echo [GAGAL] Jalankan build_exe.bat terlebih dahulu.
    goto :akhir
)

set "ISCC="
for %%P in ("D:\Tools\InnoSetup6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
    if exist "%%~P" set "ISCC=%%~P"
)
if not defined ISCC (
    for /f "delims=" %%P in ('where ISCC 2^>nul') do set "ISCC=%%P"
)
if not defined ISCC (
    echo [GAGAL] Inno Setup 6 tidak ditemukan. Install: winget install JRSoftware.InnoSetup
    goto :akhir
)

echo === Membuat installer dengan %ISCC% (bisa 10-30 menit) ===
if exist "installer_output" rmdir /s /q "installer_output"
"%ISCC%" "installer\ForensicEvidenceSearch.iss"
if errorlevel 1 (
    echo [GAGAL] Pembuatan installer gagal.
    goto :akhir
)
echo.
echo === SELESAI ===
dir /b installer_output
echo Upload SEMUA file di installer_output ke GitHub Releases.

:akhir
if not "%NOPAUSE%"=="1" pause
