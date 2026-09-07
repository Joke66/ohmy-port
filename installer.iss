; OhmyPort 安装脚本（Inno Setup 6）
; 用法：ISCC.exe /DMyAppVersion=<版本号> installer.iss
; 或直接编译（使用下方默认版本号）

#ifndef MyAppVersion
  #define MyAppVersion "1.7.0"
#endif

#define MyAppName "OhmyPort"
#define MyAppPublisher "ShineZhang"
#define MyAppExeName "OhmyPort.exe"

[Setup]
AppId={{B4E1C7A2-3D5F-4E8B-9A1C-6D2E7F8A9B0C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=OhmyPort_Setup_v{#MyAppVersion}
SetupIconFile=my-icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
