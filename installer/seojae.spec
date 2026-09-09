# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 설정.

파이썬과 의존성까지 통째로 묶는다. uv도 파이썬도 없는 사람이 받아서 바로 쓸 수 있게
하는 것이 목적이다.

**실행 파일이 둘이다.** 파이썬이 `python.exe` 와 `pythonw.exe` 로 나뉜 것과 같은 이유다.

    서재.exe        창 모드. 아이콘을 더블클릭하면 앱 창이 뜬다
    seojae-mcp.exe  콘솔 모드. Claude Desktop이 stdio로 대화한다

창 모드 실행 파일에는 표준 입출력이 없어서 MCP 프로토콜이 오갈 통로가 없다. 그래서
하나로는 안 된다. 무거운 자원(`_internal`, 104MB 모델 포함)은 COLLECT 하나에 모아
둘이 공유하므로 늘어나는 것은 파이썬 코드 묶음뿐이다.

빌드:
    .venv\\Scripts\\pyinstaller.exe installer\\seojae.spec --noconfirm

빠뜨리면 안 되는 것 셋:
  1. kiwipiepy 모델 (104MB) — 없으면 한국어 형태소 검색이 정규식 폴백으로 떨어진다
  2. static/index.html — 없으면 창이 빈 화면으로 뜬다
  3. openpyxl·python-pptx 가 런타임에 여는 자원 파일
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

SPEC_DIR = Path(SPECPATH)
PROJECT = SPEC_DIR.parent

datas = []
binaries = []
hiddenimports = []

# 한국어 형태소 모델. 이게 이 앱이 무거운 이유이자, 한국어 검색이 되는 이유다.
for package in ("kiwipiepy", "kiwipiepy_model"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# 문서 파서들이 런타임에 여는 템플릿·스키마
for package in ("openpyxl", "pptx", "docx"):
    datas += collect_data_files(package)

# 우리 정적 파일 (웹 UI 한 장)
datas += [(str(PROJECT / "src" / "seojae" / "static" / "index.html"), "seojae/static")]

# 등록기가 import 로 형식을 등록하므로, 파서 모듈이 전부 들어가야 한다
hiddenimports += [
    "seojae.parsers.markdown",
    "seojae.parsers.plain",
    "seojae.parsers.pdf_file",
    "seojae.parsers.docx_file",
    "seojae.parsers.hwpx_file",
    "seojae.parsers.tabular",
    "seojae.parsers.slides",
    "seojae.parsers.markup",
    "seojae.parsers.image",
    # 웹 서버가 동적으로 부르는 것들
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "webview.platforms.winforms",
    # 두 진입점이 각각 끌어오는 것. 양쪽 분석 결과를 같게 맞춘다
    "seojae.cli",
    "seojae.server",
    "seojae.app",
    "seojae.bootstrap",
    "seojae.desktop_config",
]

def analyze(entry):
    """두 진입점을 같은 조건으로 분석한다."""
    return Analysis(
        [str(SPEC_DIR / entry)],
        pathex=[str(PROJECT / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        excludes=[
            # 개발 도구는 빼서 크기를 줄인다
            "tkinter", "pytest", "IPython", "matplotlib", "PIL.ImageQt",
        ],
        noarchive=False,
    )


app_analysis = analyze("launcher.py")
mcp_analysis = analyze("mcp_launcher.py")

ICON = str(PROJECT / "installer" / "seojae.ico")

app_exe = EXE(
    PYZ(app_analysis.pure),
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name="서재",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 검은 콘솔 창이 뜨지 않게
    icon=ICON,
)

mcp_exe = EXE(
    PYZ(mcp_analysis.pure),
    mcp_analysis.scripts,
    [],
    exclude_binaries=True,
    name="seojae-mcp",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # stdio가 MCP 통로다. 콘솔 모드여야 표준 입출력이 있다
    icon=ICON,
)

# 실행 파일 둘, 자원은 한 벌. 양쪽 분석 결과를 합쳐 빠지는 것이 없게 한다.
COLLECT(
    app_exe,
    mcp_exe,
    app_analysis.binaries + mcp_analysis.binaries,
    app_analysis.datas + mcp_analysis.datas,
    strip=False,
    upx=False,
    name="서재",
)
