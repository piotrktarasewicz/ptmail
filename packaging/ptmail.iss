; Budowanie: packaging\build.ps1, który podaje AppVersion.
; Instalacja dla jednego użytkownika, więc aktualizacje nie pytają o uprawnienia.

[Setup]
AppId={{6E0C1E0B-6B7C-4C57-9F5E-3F5F6C0B7A11}
AppName=PT Mail
AppVersion={#AppVersion}
AppPublisher=Piotr Tarasewicz
AppPublisherURL=https://github.com/piotrktarasewicz/ptmail
DefaultDirName={localappdata}\Programs\PT Mail
DefaultGroupName=PT Mail
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PTMail-Setup-{#AppVersion}
SetupIconFile=..\ptmail\assets\ptmail.ico
UninstallDisplayIcon={app}\PTMail.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "autostart"; Description: "Uruchamiaj PT Mail po zalogowaniu do Windows, schowany w zasobniku"
Name: "desktopicon"; Description: "Utwórz skrót na pulpicie"

[Files]
Source: "..\dist\PTMail\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PT Mail"; Filename: "{app}\PTMail.exe"; AppUserModelID: "PTMail"
Name: "{group}\Odinstaluj PT Mail"; Filename: "{uninstallexe}"
Name: "{userdesktop}\PT Mail"; Filename: "{app}\PTMail.exe"; AppUserModelID: "PTMail"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PT Mail"; ValueData: """{app}\PTMail.exe"" --hidden"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\PTMail"; Flags: dontcreatekey uninsdeletekey

[Run]
Filename: "{app}\PTMail.exe"; Description: "Uruchom PT Mail"; Flags: nowait postinstall skipifsilent
; Aktualizacja idzie bez okien, więc program wraca sam.
Filename: "{app}\PTMail.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM PTMail.exe"; Flags: runhidden; RunOnceId: "ClosePTMail"

[Code]
const
  RunningMutex = 'PTMailRunning';
  WaitStepMs = 200;
  WaitSteps = 50;

{ Przy aktualizacji program zamyka się chwilę po uruchomieniu instalatora. }
function InitializeSetup(): Boolean;
var
  Step: Integer;
begin
  Step := 0;
  while CheckForMutexes(RunningMutex) and (Step < WaitSteps) do
  begin
    Sleep(WaitStepMs);
    Step := Step + 1;
  end;
  Result := True;
  if CheckForMutexes(RunningMutex) and not WizardSilent then
  begin
    MsgBox('PT Mail nadal działa. Zakończ program i uruchom instalator ponownie.', mbError, MB_OK);
    Result := False;
  end;
end;
