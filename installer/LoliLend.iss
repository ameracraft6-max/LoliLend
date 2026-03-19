#define MyAppName "LoliLend"
#define MyAppPublisher "LoliLend"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error SourceDir must point to the PyInstaller onedir dist folder.
#endif
#ifndef OutputDir
  #define OutputDir "dist\installer"
#endif

[Setup]
AppId={{D1B31A6E-7A2E-4B7A-A7AE-1D7D92FDCA10}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
OutputDir={#OutputDir}
OutputBaseFilename=LoliLend-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=yes
UninstallDisplayIcon={app}\LoliLend.exe
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#AppVersion}
SetupLogging=no
SetupIconFile={#SourcePath}\app.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#SourceDir}\LoliLend\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\LoliLend.exe"
Name: "{autoprograms}\{#MyAppName}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\LoliLend.exe"

[Run]
Filename: "{app}\LoliLend.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
