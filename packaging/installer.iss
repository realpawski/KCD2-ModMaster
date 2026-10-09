; Inno Setup script, run through tools/build_release.py which passes the defines below.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\KCD2ModMaster"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "KCD2 ModMaster"
#define AppExe "KCD2ModMaster.exe"

[Setup]
AppId={{6E0B7D52-3F4A-4C61-9B0E-5A2C8D7F1E43}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=PAWSKI
AppPublisherURL=https://realpawski.de/releases/
AppSupportURL=https://github.com/realpawski/KCD2-ModMaster/issues
AppUpdatesURL=https://github.com/realpawski/KCD2-ModMaster/releases
DefaultDirName={autopf}\KCD2 ModMaster
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=KCD2ModMaster-{#AppVersion}-Setup
SetupIconFile=modmaster.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes
#if FileExists(AddBackslash(SourcePath) + "..\LICENSE")
LicenseFile=..\LICENSE
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Only the program's own runtime folder; settings live in %APPDATA% and the workspace in Documents.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; The in-app updater runs setup silently, so start ModMaster again on its own.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
var
  RemoveUserData: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveUserData := (not UninstallSilent) and
      (MsgBox('Also remove ModMaster settings, caches and logs?' + #13#10 + #13#10 +
              'Your workspace with mods and assets in Documents is always kept, and so is anything ' +
              'installed into the game''s Mods folder.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES);
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
    DelTree(ExpandConstant('{userappdata}\KCD2ModMaster'), True, True, True);
end;
