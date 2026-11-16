@echo off
REM ============================================================================
REM  Build EXE standalone Forensic Evidence Text Search (untuk DIBAGIKAN ke orang lain
REM  yang TIDAK punya Python). Jalankan skrip ini SEKALI di komputer developer
REM  (yang sudah punya Python + dependency project ini ter-install).
REM
REM  Hasil build ada di folder dist\ForensicEvidenceSearch\ -- copy/zip SELURUH
REM  folder itu ke komputer lain. Di sana pengguna tinggal double-click
REM  ForensicEvidenceSearch.exe di dalamnya. Tidak perlu install Python apa pun.
REM ============================================================================
setlocal
cd /d %~dp0

echo === 1. Menyiapkan virtual environment khusus untuk build ===
if not exist ".venv_build" (
    python -m venv --system-site-packages .venv_build
)
if errorlevel 1 (
    echo [GAGAL] Python tidak ditemukan. Install Python 3.10+ dulu di komputer developer ini.
    pause
    exit /b 1
)

echo === 2. Install PyInstaller (terisolasi, tidak mengubah environment utama) ===
.venv_build\Scripts\python -m pip install --upgrade pip >nul
.venv_build\Scripts\python -m pip install pyinstaller

echo === 3. Memastikan semua model (CLIP, Whisper, EasyOCR) sudah ada offline ===
set NEED_MODELS=0
if not exist "models\hf_home" set NEED_MODELS=1
if not exist "models\whisper" set NEED_MODELS=1
if not exist "models\easyocr\latin_g2.pth" set NEED_MODELS=1
if "%NEED_MODELS%"=="1" (
    .venv_build\Scripts\python scripts\download_model.py
) else (
    echo Semua model sudah ada di folder models, dilewati.
)

echo === 4. Building EXE (bisa beberapa menit, ukurannya besar karena bundel PyTorch) ===
.venv_build\Scripts\python -m PyInstaller --noconfirm --clean --name ForensicEvidenceSearch --windowed ^
  --collect-all numpy --collect-all scipy ^
  --collect-all torch --collect-all torchvision --collect-all open_clip --collect-all timm ^
  --collect-all huggingface_hub --collect-all safetensors --collect-all faiss --collect-all cv2 ^
  --collect-all imagehash --collect-all PySide6 ^
  --collect-all easyocr --collect-all faster_whisper --collect-all ctranslate2 --collect-all av ^
  --collect-all onnxruntime --collect-all rapidfuzz --collect-all fitz --collect-all pymupdf ^
  --collect-all docx --collect-all pptx --collect-all openpyxl --collect-all skimage ^
  --exclude-module transformers --exclude-module tensorflow --exclude-module tensorflow.keras ^
  --add-data "models\hf_home;models\hf_home" ^
  --add-data "models\whisper;models\whisper" ^
  --add-data "models\easyocr;models\easyocr" ^
  main.py

echo === 5. Menyalin ffmpeg/ffprobe/ffplay (dibutuhkan untuk video/audio) ===
if not exist "dist\ForensicEvidenceSearchin" mkdir "dist\ForensicEvidenceSearchin"
for %%T in (ffmpeg ffprobe ffplay) do (
    for /f "delims=" %%P in ('where %%T 2^>nul') do copy /y "%%P" "dist\ForensicEvidenceSearchin\" >nul
)

echo === 6. Menyalin skrip pembersih data ke dalam folder distribusi ===
copy /y "hapus_semua_data.bat" "dist\ForensicEvidenceSearch\hapus_semua_data.bat" >nul

echo.
echo === SELESAI ===
echo Hasil build: dist\ForensicEvidenceSearch\
echo Zip/copy seluruh folder tsb ke komputer lain. Pengguna akhir tinggal
echo double-click ForensicEvidenceSearch.exe di dalamnya -- tidak perlu Python,
echo tidak perlu internet (model CLIP sudah ikut ter-bundel di dalamnya).
echo Untuk uninstall bersih: hapus folder ini + jalankan hapus_semua_data.bat
echo yang ikut disertakan di dalamnya (lihat README bagian "Cara uninstall").
pause
