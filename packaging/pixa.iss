; Inno Setup script for the Windows installer.  Build the app folder first, then:
;   pyinstaller --noconfirm packaging/pixa.spec
;   iscc /DAppVersion=0.1.0 packaging\pixa.iss
; Produces Pixa-windows-x86_64-setup.exe in the repository root.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef OutputName
  #define OutputName "Pixa-windows-x86_64-setup"
#endif

[Setup]
; Keep AppId unchanged between releases so new versions upgrade in place.
AppId={{8C5B1E0F-6D0B-4B7E-9C56-3E1B0C6F4A27}
AppName=Pixa
AppVersion={#AppVersion}
AppPublisher=Pixa
DefaultDirName={autopf}\Pixa
DefaultGroupName=Pixa
DisableProgramGroupPage=yes
; Installs for the current user without an admin prompt; "for all users" is offered too.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Pixa.exe
OutputDir=..
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Pixa\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; Drop files from the previous version so upgrades don't leave stale libraries behind.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Pixa"; Filename: "{app}\Pixa.exe"
Name: "{autodesktop}\Pixa"; Filename: "{app}\Pixa.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Pixa.exe"; Description: "{cm:LaunchProgram,Pixa}"; Flags: nowait postinstall skipifsilent
; Pixa's own updater runs this installer with /SILENT /RELAUNCH=1: start the new version
; afterwards, as the user rather than as the administrator setup may have run as.
Filename: "{app}\Pixa.exe"; Flags: nowait skipifnotsilent runasoriginaluser; Check: Relaunch

[Code]
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
