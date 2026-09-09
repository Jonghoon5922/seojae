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
#define McpExe "seojae-mcp.exe"

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
; Claude Desktop 설정 파일에 MCP 서버 항목 하나를 더한다. 남의 설정은 건드리지 않고
; 고치기 전에 백업을 남긴다. 끄고 설치해도 나중에 직접 등록할 수 있다.
Name: "claudereg"; Description: "Claude Desktop에 서재를 등록합니다 (Claude가 이 서재를 검색할 수 있게 됩니다)"; GroupDescription: "연동:"

[Files]
Source: "..\dist\app\서재\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
; Claude Desktop이 stdio로 대화하는 콘솔 실행 파일. 창 모드 exe로는 MCP를 띄울 수 없다.
Source: "..\dist\app\서재\{#McpExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\app\서재\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; 설치가 끝나면 Claude Desktop 설정에 등록한다. 서재 폴더 경로는 넘기지 않는다 —
; 서버가 앱과 같은 설정을 보고 스스로 찾으므로, 설정 화면에서 서재를 옮기면 따라간다.
Filename: "{app}\{#McpExe}"; Parameters: "register"; StatusMsg: "Claude Desktop에 등록하는 중..."; Flags: runhidden waituntilterminated; Tasks: claudereg
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 제거할 때 등록도 지운다. 안 지우면 Claude Desktop이 없는 실행 파일을 계속 부른다.
Filename: "{app}\{#McpExe}"; Parameters: "unregister"; Flags: runhidden waituntilterminated; RunOnceId: "seojae_mcp_unregister"

[UninstallDelete]
; 설정과 로그는 지운다. 사용자의 문서(서재 폴더)는 절대 건드리지 않는다.
Type: filesandordirs; Name: "{localappdata}\seojae"
