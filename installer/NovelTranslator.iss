; Novel Translator — Inno Setup script
; Mirrors SpatialLauncher desktop\installer\SpatialLauncherDesktop.iss
; Steps:
;   1. powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_exe.ps1
;   2. Compile with Inno Setup 6+: iscc installer\NovelTranslator.iss
; Output: installer\NovelTranslator-Setup.exe

#define MyAppName "Novel Translator"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "saogalaxy"
#define MyAppExeName "NovelTranslator.exe"

[Setup]
AppId={{3B4E7A1C-9D2F-4A6B-8C5D-NovelTranslatorApp}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\NovelTranslator\app
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=NovelTranslator-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "publish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall
