[Setup]
AppId={{A7B8C9D0-E1F2-4A3B-8C5D-6E7F8A9B0C1D}
AppName=DualPaneFileManager
AppVersion=1.3.0
AppPublisher=SHL
; ?è¨­å®‰è???%USERPROFILE%\DevRepositories\SHL\DualPaneApp
; ç¬¦å??¬å¸è¦å?è·¯å?ï¼Œä½¿?¨è€…ä??¯åœ¨å®‰è??‚ä¿®??
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
; ?ªä??™é?è¨­è‹±?‡ï??¿å??¾ä??°è?è¨€?…å ±??
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ?“å??€??PyInstaller ?¢å‡º?„æ?æ¡?
Source: "dist\DualPaneFileManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; ä¿è­·è¨­å?æª?
Source: "dist\DualPaneFileManager\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\DualPaneFileManager"; Filename: "{app}\DualPaneFileManager.exe"
Name: "{autodesktop}\DualPaneFileManager"; Filename: "{app}\DualPaneFileManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DualPaneFileManager.exe"; Description: "{cm:LaunchProgram,DualPaneFileManager}"; Flags: nowait postinstall skipifsilent
