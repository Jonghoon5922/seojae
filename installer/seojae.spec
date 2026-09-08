# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 설정.

`seojae app` 을 파이썬과 의존성까지 통째로 묶어 하나의 실행 파일로 만든다.
uv도 파이썬도 없는 사람이 받아서 바로 쓸 수 있게 하는 것이 목적이다.

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
]

analysis = Analysis(
    [str(SPEC_DIR / "launcher.py")],
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

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="서재",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 검은 콘솔 창이 뜨지 않게
    icon=str(PROJECT / "installer" / "seojae.ico"),
)

COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="서재",
)
