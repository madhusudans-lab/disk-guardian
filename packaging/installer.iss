; Disk Guardian installer (Inno Setup 6). Built by build.ps1, which sets DG_VERSION.
; Per-user install: no administrator rights, no UAC prompt.

#define AppVersion GetEnv("DG_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.2"
#endif
#define AppExeW "diskguardian-w.exe"
#define AppExe "diskguardian.exe"
#define AUMID "DiskGuardian.Agent"

[Setup]
AppId={{6B1E5C2A-3F4D-4E8B-9C1A-D15C6A4D0A11}
AppName=Disk Guardian
AppVersion={#AppVersion}
AppVerName=Disk Guardian {#AppVersion}
AppPublisher=Disk Guardian contributors
VersionInfoDescription=Disk Guardian setup
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\DiskGuardian
DisableDirPage=yes
DefaultGroupName=Disk Guardian
DisableProgramGroupPage=yes
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=DiskGuardian-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExeW}
UninstallDisplayName=Disk Guardian
LicenseFile=..\LICENSE
CloseApplications=yes

[Files]
Source: "..\dist\DiskGuardian\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Each shortcut needs its own AppUserModelID: Start collapses shortcuts that share one.
; "Disk status" carries the bare AUMID that notify.py uses for toasts.
Name: "{group}\Disk status"; Filename: "{app}\{#AppExeW}"; Parameters: "status"; AppUserModelID: "{#AUMID}"; Comment: "Free space on every drive"
Name: "{group}\Clean junk now"; Filename: "{app}\{#AppExeW}"; Parameters: "clean --tier safe --yes"; AppUserModelID: "{#AUMID}.CleanJunk"; Comment: "Delete crash dumps, old temp files and other junk"
Name: "{group}\Clean caches"; Filename: "{app}\{#AppExeW}"; Parameters: "clean --tier cache --yes"; AppUserModelID: "{#AUMID}.CleanCaches"; Comment: "Clear browser, app and download caches (they rebuild themselves)"
Name: "{group}\Deep clean (administrator)"; Filename: "{app}\{#AppExeW}"; Parameters: "deep-clean"; AppUserModelID: "{#AUMID}.DeepClean"; Comment: "Also clean Windows temp and update caches (asks for permission)"
Name: "{group}\Open report"; Filename: "{app}\{#AppExeW}"; Parameters: "open-report"; AppUserModelID: "{#AUMID}.Report"; Comment: "What uses space on your drives"
Name: "{group}\Open quarantine"; Filename: "{app}\{#AppExeW}"; Parameters: "open-quarantine"; AppUserModelID: "{#AUMID}.Quarantine"; Comment: "Files moved aside, restorable for 7 days"
Name: "{group}\Settings"; Filename: "{app}\{#AppExeW}"; Parameters: "open-settings"; AppUserModelID: "{#AUMID}.Settings"
Name: "{group}\Uninstall Disk Guardian"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "task install"; Flags: runhidden waituntilterminated; StatusMsg: "Setting up the background check..."
Filename: "{app}\{#AppExe}"; Parameters: "scan --quick"; Flags: runhidden nowait
Filename: "{app}\{#AppExeW}"; Parameters: "status"; Description: "Show disk status now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "task remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTask"

[Code]
function HasEntries(Dir: String): Boolean;
var
  R: TFindRec;
begin
  Result := False;
  if FindFirst(Dir + '\*', R) then
  begin
    try
      repeat
        if (R.Name <> '.') and (R.Name <> '..') then
        begin
          Result := True;
          Exit;
        end;
      until not FindNext(R);
    finally
      FindClose(R);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data, Msg, Extra: String;
  I: Integer;
  Letter: String;
  Full: Boolean;
begin
  if (CurUninstallStep <> usPostUninstall) or UninstallSilent then
    Exit;
  Data := ExpandConstant('{localappdata}\DiskGuardian');
  Full := HasEntries(Data + '\quarantine');
  Extra := '';
  for I := Ord('C') to Ord('Z') do
  begin
    Letter := Chr(I);
    if DirExists(Letter + ':\.DiskGuardian') then
    begin
      Extra := Extra + ' ' + Letter + ':';
      if HasEntries(Letter + ':\.DiskGuardian\quarantine') then
        Full := True;
    end;
  end;
  if not DirExists(Data) and (Extra = '') then
    Exit;
  Msg := 'Also delete Disk Guardian''s settings, reports and quarantine?';
  if Full then
    Msg := 'Your quarantine still holds files that Disk Guardian moved aside. ' +
           'Deleting it removes them for good. Choose No to keep them (you can open the folder later).' + #13#10#13#10 + Msg;
  if MsgBox(Msg, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(Data, True, True, True);
    for I := Ord('C') to Ord('Z') do
      if DirExists(Chr(I) + ':\.DiskGuardian') then
        DelTree(Chr(I) + ':\.DiskGuardian', True, True, True);
  end;
end;
