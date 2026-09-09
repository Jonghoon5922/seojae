# 인스톨러

`.exe` 하나로 설치되는 데스크톱 앱을 만든다. **uv도 파이썬도 없는 사람이 받아서 바로 쓰는 것**이 목적이다.

```bash
# 1) 파이썬과 의존성까지 통째로 묶는다
.venv\Scripts\pyinstaller.exe installer\seojae.spec --noconfirm --distpath dist\app

# 2) 설치 마법사를 만든다
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\seojae.iss
```

결과: `dist\seojae-setup-<버전>.exe` (버전은 `src/seojae/__init__.py` 에서 온다)

## 두 단계를 이어 붙일 때 종료 코드를 확인하라

**실제로 당한 일이다.** 1단계가 실패했는데 2단계가 그대로 돌아서, 새 이름표를 단
옛날 바이너리가 설치 파일로 나왔다.

```
PermissionError: [WinError 5] 액세스가 거부되었습니다:
  _internal/clr_loader/ffi/dlls/amd64/ClrLoader.dll
```

**서재 앱이 실행 중이면 그 DLL을 붙잡고 있어서 덮어쓰기가 막힌다.** PyInstaller는
실패하지만, 셸에서 `| tail` 로 출력을 줄이면 파이프라인 종료 코드가 `tail` 의 것이
되어 `&&` 뒤가 그대로 실행된다. 그러면 ISCC가 `dist/app` 에 남아 있는 **직전 빌드**를
포장한다. 아무 오류도 안 보이고, 파일 이름만 새 버전이다.

빌드 전에 앱을 닫고, 1단계 종료 코드를 확인한 뒤 2단계로 넘어가라.

## 크기

| | |
|---|---|
| 묶은 폴더 | 252 MB |
| **설치 파일** | **136 MB** (lzma2/max) |

실행 파일이 둘이라(`서재.exe` 창 모드 / `seojae-mcp.exe` 콘솔 모드) 파이썬 코드
묶음이 한 벌 중복된다. 16MB쯤인데, PyInstaller 실행 파일 안은 이미 압축돼 있어서
lzma2로도 더 줄지 않는다. 무거운 `_internal` 은 둘이 공유하므로 이게 전부다.

가장 큰 것은 **kiwipiepy 한국어 모델 104MB**다. 이게 이 앱이 무거운 이유이자
임베딩 모델 없이 한국어 검색이 되는 이유다. 뺄 수는 있지만(정규식 폴백) 조사가 붙은
한국어에서 검색 품질이 크게 떨어진다.

## 정한 것

| 항목 | 결정 | 이유 |
|---|---|---|
| 설치 위치 | 사용자 폴더 (`PrivilegesRequired=lowest`) | **UAC 창이 안 뜬다.** 권한 없는 회사 PC에서도 설치된다 |
| 콘솔 | `서재.exe` 는 `console=False`, `seojae-mcp.exe` 는 `console=True` | 검은 창은 안 띄우되, MCP는 stdio가 필요하다. 창 모드 실행 파일에는 표준 입출력이 없다 |
| 오류 처리 | 로그 파일 + 메시지 상자 | 창 모드에는 콘솔이 없다. 없으면 "아이콘 눌렀는데 아무 일도 안 남"이 된다 |
| 서재 위치 | `내문서\서재`, 설정에 기억 | 아이콘 더블클릭에는 인자가 없다 |
| 제거 | 설정·로그만 지움 + Claude Desktop 등록 해제 | **사용자의 문서(서재 폴더)는 절대 건드리지 않는다** |
| Claude 연동 | 설치 중 체크박스로 자동 등록 | JSON을 손으로 고치게 하지 않는다. 남의 MCP 서버 설정은 안 건드린다 |

## 빠뜨리면 안 되는 것

PyInstaller가 자동으로 못 찾는 것들이라 `seojae.spec`에 명시했다.

- **kiwipiepy 모델** — 없으면 한국어 검색이 정규식 폴백으로 떨어진다
- **`static/index.html`** — 없으면 창이 빈 화면으로 뜬다
- **파서 모듈 전부** — 등록기가 `import` 로 형식을 등록하므로, 안 넣으면 그 형식이 조용히 사라진다
- **uvicorn 하위 모듈** — 런타임에 동적으로 부른다

## 아직 안 한 것

**코드 서명.** 서명하지 않으면 Windows SmartScreen이 "알 수 없는 게시자" 경고를 띄우고,
사용자가 "추가 정보 → 실행"을 눌러야 한다. 인증서는 연 20~40만원대다.

**macOS.** PyInstaller는 크로스 컴파일을 못 한다. Mac에서 따로 빌드해야 한다.
