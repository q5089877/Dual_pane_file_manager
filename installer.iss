[Setup]
AppId={{A7B8C9D0-E1F2-4A3B-8C5D-6E7F8A9B0C1D}
AppName=DualPaneFileManager
AppVersion=1.0.0
AppPublisher=SHL
; --- 修正後的路徑寫法 ---
DefaultDirName={%USERPROFILE}\DevRepositories\SHL\DualPaneApp
; -----------------------
DisableDirPage=yes
DefaultGroupName=DualPaneFileManager
OutputBaseFilename=DualPaneFileManager_SHL_Setup
Compression=lzma
SolidCompression=yes
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\DualPaneFileManager.exe
PrivilegesRequired=lowest

[Languages]
; 只保留預設英文，避免找不到語言包報錯
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 抓取所有 PyInstaller 產出的檔案
Source: "dist\DualPaneFileManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 保護設定檔
Source: "dist\DualPaneFileManager\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\DualPaneFileManager"; Filename: "{app}\DualPaneFileManager.exe"
Name: "{autodesktop}\DualPaneFileManager"; Filename: "{app}\DualPaneFileManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DualPaneFileManager.exe"; Description: "{cm:LaunchProgram,DualPaneFileManager}"; Flags: nowait postinstall skipifsilent
