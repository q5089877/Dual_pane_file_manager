[Setup]
AppId={{A7B8C9D0-E1F2-4A3B-8C5D-6E7F8A9B0C1D}
AppName=DualPaneFileManager
AppVersion=1.4.0
AppPublisher=SHL
; ?�設安�???%USERPROFILE%\DevRepositories\SHL\DualPaneApp
; 符�??�司規�?路�?，使?�者�??�在安�??�修??
DefaultDirName={%USERPROFILE}\DevRepositories\SHL\DualPaneApp
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName=DualPaneFileManager
OutputBaseFilename=DualPaneFileManager_SHL_Setup
Compression=lzma
SolidCompression=yes
OutputDir=Output
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\DualPaneFileManager.exe
PrivilegesRequired=lowest

[Languages]
; ?��??��?設英?��??��??��??��?言?�報??
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ?��??�??PyInstaller ?�出?��?�?
Source: "dist\DualPaneFileManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 保護設�?�?
Source: "dist\DualPaneFileManager\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\DualPaneFileManager"; Filename: "{app}\DualPaneFileManager.exe"
Name: "{autodesktop}\DualPaneFileManager"; Filename: "{app}\DualPaneFileManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DualPaneFileManager.exe"; Description: "{cm:LaunchProgram,DualPaneFileManager}"; Flags: nowait postinstall skipifsilent
