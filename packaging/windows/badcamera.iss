; Inno Setup script. Build after pyinstaller, from the repo root: iscc packaging\windows\badcamera.iss
; Presets and captures go to %APPDATA%\BadCamera because Program Files is read-only (see gpu.data_dir).
[Setup]
AppName=BadCamera
AppVersion=1.1
AppPublisher=rosarydigital
DefaultDirName={autopf}\BadCamera
DefaultGroupName=BadCamera
OutputDir=..\..
OutputBaseFilename=BadCamera-windows-x64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\BadCamera.exe

[Files]
Source: "..\..\dist\BadCamera\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\BadCamera"; Filename: "{app}\BadCamera.exe"
Name: "{autodesktop}\BadCamera"; Filename: "{app}\BadCamera.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\BadCamera.exe"; Description: "Start BadCamera"; Flags: nowait postinstall skipifsilent
