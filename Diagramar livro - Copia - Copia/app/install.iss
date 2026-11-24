; install.iss - Inno Setup script para Diagramar Livro
; Compile com: iscc install.iss
; Requer Inno Setup 6.2+ (https://jrsoftware.org/isinfo.php)

#define MyAppName "Diagramar Livro"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Enzo Andrade"
#define MyAppURL "https://github.com/enzio/DiagramarLivro"
#define MyAppExeName "DiagramarLivro.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
OutputDir=dist
OutputBaseFilename=Setup_{#MyAppName}_v{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstall=x64
ArchitecturesAllowed=x64

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 0,6.1

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "fonts\*"; DestDir: "{app}\fonts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\fonts"

[Code]
function InitializeSetup(): Boolean;
begin
  // Verifica se tem Tesseract instalado
  if not RegKeyExists(HKLM, 'SOFTWARE\Tesseract-OCR') and
     not RegKeyExists(HKCU, 'SOFTWARE\Tesseract-OCR') then
  begin
    if MsgBox('O Tesseract OCR não foi detectado no sistema.' + #13#10 +
              'Ele é NECESSÁRIO para processar PDFs escaneados (OCR).' + #13#10#13#10 +
              'Deseja continuar mesmo assim? (Você pode instalar depois em:' + #13#10 +
              'https://github.com/UB-Mannheim/tesseract/wiki)', mbConfirmation, MB_YESNO) = IDNO then
      Result := False
    else
      Result := True;
  end
  else
    Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Copia fontes para pasta de fontes do Windows (opcional)
    // Descomente se quiser instalar fontes automaticamente:
    // InstallFont(ExpandConstant('{app}\fonts\VeraHumana95-Regular.ttf'));
    // InstallFont(ExpandConstant('{app}\fonts\VeraHumana95-Bold.ttf'));
    // InstallFont(ExpandConstant('{app}\fonts\Marcellus-Regular.ttf'));
  end;
end;