; ============================================================================
;  Installer Cyber Forensic Evidence Search
;  Karya Alfin Aqila Muzaki - https://github.com/AlfinAqilaMuzaki/forensic_evidence_search
;
;  Dibangun oleh build_installer.bat dari folder dist\ForensicEvidenceSearch
;  (hasil build_exe.bat). Karena ukurannya besar (model AI offline), installer
;  dipecah menjadi Setup.exe + beberapa file .bin (masing-masing < 2 GB, batas
;  GitHub Releases). Semua file harus berada di folder yang sama saat instalasi.
; ============================================================================

#define AppName      "Cyber Forensic Evidence Search"
#define AppVersion   "2.3.0"
#define AppPublisher "Alfin Aqila Muzaki"
#define AppURL       "https://github.com/AlfinAqilaMuzaki/forensic_evidence_search"
#define AppExe       "ForensicEvidenceSearch.exe"

[Setup]
AppId={{B6C1E7A4-5F2D-4C8E-9A3B-2E7F1D4C6A90}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=(c) 2026 {#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
; Default per-user (tanpa hak admin): %LOCALAPPDATA%\Programs\... - folder ini
; bisa ditulis aplikasi untuk menyimpan DATA_ANALISIS. Pengguna boleh memilih
; drive lain (mis. D:\) di halaman lokasi instalasi.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
OutputDir=..\installer_output
OutputBaseFilename=CyberForensicEvidenceSearch-Setup-v{#AppVersion}
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=1990000000
ReserveBytes=0

[Languages]
Name: "id"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=Instalasi
SetupWindowTitle=Instalasi - %1
WelcomeLabel1=Selamat datang di instalasi [name]
WelcomeLabel2=Program ini akan memasang [name/ver] di komputer Anda.%n%nAlat forensik digital offline karya Alfin Aqila Muzaki untuk mencari kalimat di video, audio, foto, dan dokumen, serta mencari foto mirip.%n%nTidak perlu menginstal Python atau aplikasi lain. Klik Lanjut untuk meneruskan.
ButtonBack=< &Kembali
ButtonNext=&Lanjut >
ButtonInstall=&Pasang
ButtonFinish=&Selesai
ButtonCancel=Batal
ButtonBrowse=&Pilih...
ButtonYes=&Ya
ButtonNo=&Tidak
WizardSelectDir=Pilih Lokasi Instalasi
SelectDirDesc=Di mana [name] akan dipasang?
SelectDirLabel3=[name] akan dipasang di folder berikut. Data hasil analisis juga disimpan di folder ini (subfolder DATA_ANALISIS), jadi pilih drive dengan ruang kosong yang cukup.
SelectDirBrowseLabel=Klik Lanjut untuk meneruskan, atau Pilih... untuk memilih folder lain (contoh: D:\Cyber Forensic Evidence Search).
DiskSpaceGBLabel=Dibutuhkan ruang kosong minimal [gb] GB.
WizardSelectTasks=Pilih Tugas Tambahan
SelectTasksDesc=Tugas tambahan apa yang ingin dijalankan?
SelectTasksLabel2=Pilih tugas tambahan, lalu klik Lanjut.
WizardReady=Siap Memasang
ReadyLabel1=Instalasi siap memasang [name] di komputer Anda.
ReadyLabel2a=Klik Pasang untuk mulai, atau Kembali untuk mengubah pengaturan.
WizardInstalling=Sedang Memasang
InstallingLabel=Mohon tunggu, [name] sedang dipasang (beberapa menit karena ukuran model AI besar)...
FinishedHeadingLabel=Instalasi [name] selesai
FinishedLabel=[name] sudah terpasang. Buka lewat ikon di Desktop atau menu Start.
ClickFinish=Klik Selesai untuk menutup instalasi.
SelectDiskLabel2=Masukkan Disk %1 lalu klik OK.%n%nFile %2 tidak ditemukan. Pastikan SEMUA file installer (Setup.exe dan semua file .bin) sudah diunduh lengkap dan berada di folder yang SAMA, lalu klik OK.
ExitSetupTitle=Batalkan Instalasi
ExitSetupMessage=Instalasi belum selesai. Jika dibatalkan sekarang, program tidak akan terpasang.%n%nKeluar dari instalasi?
ConfirmUninstall=Hapus %1 beserta semua komponennya?%n%nCatatan: folder DATA_ANALISIS (hasil analisis & paket bukti) TIDAK ikut dihapus.
UninstalledAll=%1 berhasil dihapus dari komputer Anda.

[CustomMessages]
id.DesktopIcon=Buat ikon di &Desktop
id.ExtraGroup=Pintasan:
id.RunNow=Jalankan {#AppName} sekarang

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:ExtraGroup}"

[Files]
Source: "..\dist\ForensicEvidenceSearch\*"; DestDir: "{app}"; Excludes: "\DATA_ANALISIS,\_tmp,\_tmp_build,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\app.ico"; Comment: "Alat forensik digital karya {#AppPublisher}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\app.ico"; Comment: "Alat forensik digital karya {#AppPublisher}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:RunNow}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_tmp"
Type: files; Name: "{app}\DATA_ANALISIS\selftest_log.txt"
