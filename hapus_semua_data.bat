@echo off
REM ==========================================================================
REM  Menghapus SEMUA data hasil analisis (DATA_ANALISIS di samping aplikasi):
REM  teks ekstraksi, hash, audit log, index foto, dan paket bukti diamankan.
REM  Folder barang bukti asli TIDAK tersentuh.
REM ==========================================================================
setlocal
cd /d %~dp0
echo Akan menghapus: %~dp0DATA_ANALISIS
echo PERINGATAN: termasuk paket "bukti_diamankan" dan audit log. Pastikan sudah diarsip.
set /p ANS=Ketik YES untuk melanjutkan: 
if /I not "%ANS%"=="YES" (
    echo Dibatalkan.
    pause
    exit /b 0
)
if exist "%~dp0DATA_ANALISIS" rmdir /s /q "%~dp0DATA_ANALISIS"
if exist "%LOCALAPPDATA%\PhotoSimilaritySearch" rmdir /s /q "%LOCALAPPDATA%\PhotoSimilaritySearch"
echo Selesai.
pause
