; Script Inno Setup untuk Noktah
; Build: py -3.10 build_tools/build_installer.py
; (butuh dist\Noktah\ hasil build --onedir)

#define AppName "Noktah"
#define AppVersion "1.0.0"
#define AppPublisher "Rizuki25"
#define AppURL "https://github.com/Rizuki25/Noktah"
#define AppExe "Noktah.exe"

[Setup]
AppId={{7C4B1E52-3A9D-4F6E-9B21-6E0C5F2D8A44}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
LicenseFile=
OutputDir=..\dist
OutputBaseFilename=Noktah-Setup-{#AppVersion}
SetupIconFile=..\assets\noktah.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
MinVersion=10.0
; per-user saja: tidak perlu hak admin, dan tidak ada dialog "semua pengguna"
; yang bisa berujung gagal dengan Error 5 kalau UAC tidak lolos.
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Shortcut:"
Name: "startup"; Description: "Jalankan Noktah otomatis saat login Windows"; GroupDescription: "Autostart:"

[Files]
Source: "..\dist\Noktah\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Jalankan {#AppName} sekarang"; Flags: nowait postinstall skipifsilent
