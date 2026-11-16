@echo off
REM ============================================================================
REM  Build EXE portable Cyber Forensic Evidence Search (karya Alfin Aqila Muzaki)
REM  https://github.com/AlfinAqilaMuzaki/forensic_evidence_search
REM
REM  Hasil: dist\ForensicEvidenceSearch\ForensicEvidenceSearch.exe (+ semua library,
REM  model AI offline, dan FFmpeg). Folder ini yang dibungkus menjadi installer
REM  oleh build_installer.bat.
REM
REM  Jalankan di komputer developer yang sudah: pip install -r requirements.txt
REM  Opsi: set NOPAUSE=1 sebelum menjalankan agar tidak berhenti di akhir.
REM ============================================================================
setlocal
cd /d %~dp0

REM File sementara & cache PyInstaller di folder project (bukan drive C).
set "TMP=%~dp0_tmp_build"
set "TEMP=%~dp0_tmp_build"
set "PYINSTALLER_CONFIG_DIR=%~dp0_tmp_build\pyinstaller"
if not exist "%TMP%" mkdir "%TMP%"

echo === 1. Menyiapkan virtual environment khusus build ===
if not exist ".venv_build" (
    python -m venv --system-site-packages .venv_build
)
if errorlevel 1 (
    echo [GAGAL] Python tidak ditemukan. Install Python 3.11 terlebih dahulu.
    goto :akhir
)

echo === 2. Install PyInstaller (terisolasi, environment utama tidak berubah) ===
.venv_build\Scripts\python -m pip install --upgrade pip >nul
.venv_build\Scripts\python -m pip install pyinstaller

echo === 3. Memastikan semua model (CLIP, Whisper, EasyOCR) ada offline ===
set NEED_MODELS=0
if not exist "models\hf_home" set NEED_MODELS=1
if not exist "models\whisper" set NEED_MODELS=1
if not exist "models\easyocr\latin_g2.pth" set NEED_MODELS=1
if "%NEED_MODELS%"=="1" (
    .venv_build\Scripts\python scripts\download_model.py
) else (
    echo Semua model sudah ada di folder models, dilewati.
)

echo === 4. Building EXE (10-40 menit) ===
.venv_build\Scripts\python -m PyInstaller --noconfirm --clean --name ForensicEvidenceSearch --windowed ^
  --icon "assets\app.ico" ^
  --collect-all numpy --collect-all scipy ^
  --collect-all torch --collect-all torchvision --collect-all open_clip --collect-all timm ^
  --collect-all huggingface_hub --collect-all safetensors --collect-all faiss --collect-all cv2 ^
  --collect-all imagehash ^
  --collect-all easyocr --collect-all faster_whisper --collect-all ctranslate2 --collect-all av ^
  --collect-all onnxruntime --collect-all rapidfuzz --collect-all fitz --collect-all pymupdf ^
  --collect-all docx --collect-all pptx --collect-all openpyxl --collect-all skimage ^
  --exclude-module transformers --exclude-module tensorflow --exclude-module tensorflow.keras ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick3D ^
  --add-data "models\hf_home;models\hf_home" ^
  --add-data "models\whisper;models\whisper" ^
  --add-data "models\easyocr;models\easyocr" ^
  --add-data "assets;assets" ^
  main.py
if errorlevel 1 (
    echo [GAGAL] PyInstaller gagal. Lihat pesan di atas.
    goto :akhir
)

set "DIST=dist\ForensicEvidenceSearch"

echo === 5. Menyalin ffmpeg / ffprobe / ffplay ke %DIST%\bin ===
if not exist "%DIST%\bin" mkdir "%DIST%\bin"
for %%T in (ffmpeg ffprobe ffplay) do (
    if exist "bin\%%T.exe" (
        copy /y "bin\%%T.exe" "%DIST%\bin\" >nul
    ) else (
        for /f "delims=" %%P in ('where %%T 2^>nul') do copy /y "%%P" "%DIST%\bin\" >nul
    )
)
for %%T in (ffmpeg ffprobe ffplay) do (
    if not exist "%DIST%\bin\%%T.exe" echo [PERINGATAN] %%T.exe tidak ditemukan - fitur video/audio tidak akan jalan.
)

echo === 6. Menyalin file pendukung ===
copy /y "hapus_semua_data.bat" "%DIST%\hapus_semua_data.bat" >nul
copy /y "README.md" "%DIST%\README.md" >nul

echo === 7. Self-test EXE hasil build ===
start "" /wait "%DIST%\ForensicEvidenceSearch.exe" --selftest
if exist "%DIST%\DATA_ANALISIS\selftest_log.txt" (
    type "%DIST%\DATA_ANALISIS\selftest_log.txt" | findstr /b /c:"[" /c:"SELFTEST"
    rmdir /s /q "%DIST%\DATA_ANALISIS"
) else (
    echo [PERINGATAN] selftest_log.txt tidak terbentuk.
)

echo.
echo === SELESAI ===
echo Hasil build : %DIST%\ForensicEvidenceSearch.exe
echo Langkah berikut: build_installer.bat  (membuat Setup.exe untuk dibagikan)

:akhir
if not "%NOPAUSE%"=="1" pause
