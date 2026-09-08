; 서재 (Seojae) 설치 마법사 — Inno Setup 6
;
; 빌드 순서:
;   1) .venv\Scripts\pyinstaller.exe installer\seojae.spec --noconfirm --distpath dist\app
;   2) ISCC.exe installer\seojae.iss
;
; 관리자 권한을 요구하지 않는다. 사용자 폴더에 설치하므로 UAC 창이 뜨지 않고,
; 회사 PC처럼 권한이 없는 환경에서도 설치된다.

#define AppName "서재"
#define AppNameEn "Seojae"
#define AppVersion "0.1.0"
#define AppPublisher "Jonghoon5922"
#define AppURL "https://github.com/Jonghoon5922/seojae"
#define AppExe "서재.exe"

[Setup]
AppId={{7C3A9E51-2D48-4C0B-9E6F-8B1A5D2E7F30}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; 사용자 폴더에 설치 — 관리자 권한이 필요 없다
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no

OutputDir=..\dist
OutputBaseFilename=seojae-setup-{#AppVersion}
SetupIconFile=seojae.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

; 232MB를 압축한다. lzma2/max 가 느리지만 결과가 가장 작다
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\app\서재\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\app\서재\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 설정과 로그는 지운다. 사용자의 문서(서재 폴더)는 절대 건드리지 않는다.
Type: filesandordirs; Name: "{localappdata}\seojae"
