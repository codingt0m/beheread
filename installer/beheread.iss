; Installateur Inno Setup de Beheread.
;
; Compile par build.bat apres PyInstaller :
;   ISCC.exe /DAppVersion=x.y.z installer\beheread.iss
; -> dist\Beheread-Setup-x.y.z.exe
;
; Installation PAR UTILISATEUR par defaut (aucun droit administrateur, aucune
; demande UAC) : dans %LOCALAPPDATA%\Programs\Beheread, associations de
; fichiers dans le registre de l'utilisateur. Une installation pour tous les
; utilisateurs reste possible (choix propose au lancement).
;
; Les donnees de lecture (%APPDATA%\MangaReaderPy) ne sont jamais touchees par
; l'installation ni par la desinstallation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{1C6AB04A-EF5B-4356-85C6-9DE0F0329AB4}
AppName=Beheread
AppVersion={#AppVersion}
AppVerName=Beheread {#AppVersion}
AppPublisher=Beheread
DefaultDirName={autopf}\Beheread
DefaultGroupName=Beheread
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Beheread-Setup-{#AppVersion}
SetupIconFile=..\beheread\resources\icon.ico
UninstallDisplayIcon={app}\Beheread.exe
UninstallDisplayName=Beheread
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
; ferme Beheread s'il est ouvert (sinon ses fichiers seraient verrouilles)
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "assoc"; Description: "Ouvrir les fichiers CBZ, CBR et EPUB avec Beheread"; GroupDescription: "Associations de fichiers :"
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
Source: "..\dist\Beheread\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; restes d'une version precedente (bibliotheques renommees entre deux versions)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Beheread"; Filename: "{app}\Beheread.exe"
Name: "{autodesktop}\Beheread"; Filename: "{app}\Beheread.exe"; Tasks: desktopicon
; raccourci du Bureau cree pour l'ancienne version (C:\Program Files) :
; redirige vers la nouvelle, sinon il lancerait l'ancienne version
Name: "{userdesktop}\Beheread"; Filename: "{app}\Beheread.exe"; Check: DesktopShortcutPointsToOldInstall

[Registry]
; types de fichiers declares par Beheread (HKA : registre de l'utilisateur, ou
; de la machine pour une installation pour tous)
Root: HKA; Subkey: "Software\Classes\Beheread.cbz"; ValueType: string; ValueData: "Livre CBZ (Beheread)"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Beheread.cbz\DefaultIcon"; ValueType: string; ValueData: """{app}\Beheread.exe"",0"
Root: HKA; Subkey: "Software\Classes\Beheread.cbz\shell\open\command"; ValueType: string; ValueData: """{app}\Beheread.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Beheread.cbr"; ValueType: string; ValueData: "Livre CBR (Beheread)"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Beheread.cbr\DefaultIcon"; ValueType: string; ValueData: """{app}\Beheread.exe"",0"
Root: HKA; Subkey: "Software\Classes\Beheread.cbr\shell\open\command"; ValueType: string; ValueData: """{app}\Beheread.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Beheread.epub"; ValueType: string; ValueData: "Livre EPUB (Beheread)"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Beheread.epub\DefaultIcon"; ValueType: string; ValueData: """{app}\Beheread.exe"",0"
Root: HKA; Subkey: "Software\Classes\Beheread.epub\shell\open\command"; ValueType: string; ValueData: """{app}\Beheread.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Beheread.pdf"; ValueType: string; ValueData: "Document PDF (Beheread)"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Beheread.pdf\DefaultIcon"; ValueType: string; ValueData: """{app}\Beheread.exe"",0"
Root: HKA; Subkey: "Software\Classes\Beheread.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\Beheread.exe"" ""%1"""
; « Ouvrir avec » : Beheread est propose pour les quatre formats
Root: HKA; Subkey: "Software\Classes\.cbz\OpenWithProgids"; ValueType: string; ValueName: "Beheread.cbz"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.cbr\OpenWithProgids"; ValueType: string; ValueName: "Beheread.cbr"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.epub\OpenWithProgids"; ValueType: string; ValueName: "Beheread.epub"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "Beheread.pdf"; ValueData: ""; Flags: uninsdeletevalue
; application par defaut pour CBZ / CBR / EPUB (option cochee par defaut) ;
; jamais pour les PDF, qui gardent le lecteur PDF habituel de l'utilisateur
Root: HKA; Subkey: "Software\Classes\.cbz"; ValueType: string; ValueData: "Beheread.cbz"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.cbr"; ValueType: string; ValueData: "Beheread.cbr"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.epub"; ValueType: string; ValueData: "Beheread.epub"; Tasks: assoc

[Run]
Filename: "{app}\Beheread.exe"; Description: "Lancer Beheread"; Flags: nowait postinstall skipifsilent

[Code]
{ Ancienne installation par l'ancien script (copie dans C:\Program Files, avant
  la version 0.2). Elle ne connait pas la base de donnees de la 0.2 : lancee
  par erreur, elle afficherait une bibliotheque vide. }
function OldInstallExe(): String;
begin
  Result := ExpandConstant('{commonpf64}\Beheread\Beheread.exe');
end;

function OldInstallPresent(): Boolean;
begin
  Result := FileExists(OldInstallExe()) and
            (CompareText(ExpandConstant('{app}\Beheread.exe'), OldInstallExe()) <> 0);
end;

function DesktopShortcutPointsToOldInstall(): Boolean;
var
  Shell, Link: Variant;
  LinkPath: String;
begin
  Result := False;
  LinkPath := ExpandConstant('{userdesktop}\Beheread.lnk');
  Log('Verification du raccourci : ' + LinkPath);
  if not FileExists(LinkPath) then
    Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(LinkPath);
    { l'installateur est un programme 32 bits : Windows lui presente la cible
      « C:\Program Files\... » d'un raccourci sous la forme
      « C:\Program Files (x86)\... » ; les deux formes designent l'ancienne version }
    Result := (CompareText(Link.TargetPath, OldInstallExe()) = 0) or
              (CompareText(Link.TargetPath, ExpandConstant('{commonpf32}\Beheread\Beheread.exe')) = 0);
    Log('Raccourci ' + LinkPath + ' -> ' + Link.TargetPath);
  except
    Log('Lecture du raccourci impossible : ' + GetExceptionMessage);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and OldInstallPresent() then
  begin
    Log('Ancienne version presente : ' + OldInstallExe());
    SuppressibleMsgBox(
      'Une ancienne version de Beheread est encore installée dans :' + #13#10 +
      ExtractFileDir(OldInstallExe()) + #13#10#13#10 +
      'Elle ne sait pas lire les données de cette nouvelle version : supprimez ce dossier ' +
      '(droits administrateur requis) pour ne pas la lancer par erreur. Si un raccourci ' +
      'du Bureau la lançait, il a été redirigé vers la nouvelle version.',
      mbInformation, MB_OK, IDOK);
  end;
end;
