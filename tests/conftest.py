from __future__ import annotations

from pathlib import Path

import pytest

README = """---
name: 업무규정
description: 회사 취업규칙과 경비 지침. 휴가, 출장비, 근무시간 질문에 사용.
tags: [규정, 총무]
updated: 2026-09-01
---

# 업무규정

- 휴가규정.md
"""

VACATION = """# 휴가 규정

## 연차 휴가
입사 1년 미만 직원은 매월 1일의 연차가 발생한다.
1년 이상 근속하면 15일이 부여된다.

## 병가
연간 60일까지 사용할 수 있다. 3일을 넘으면 진단서를 낸다.
"""

TRAVEL = """# 출장 지침

## 국내 출장
숙박비는 1박 8만원까지 실비로 정산한다.

## 해외 출장
항공권은 이코노미가 원칙이다.
"""


@pytest.fixture
def shelf(tmp_path: Path) -> Path:
    """컬렉션 하나 + 인박스 파일 하나가 있는 최소 서재."""
    rules = tmp_path / "업무규정"
    rules.mkdir()
    (rules / "README.md").write_text(README, encoding="utf-8")
    (rules / "휴가규정.md").write_text(VACATION, encoding="utf-8")
    (rules / "출장지침.md").write_text(TRAVEL, encoding="utf-8")

    inbox = tmp_path / "_inbox"
    inbox.mkdir()
    (inbox / "미분류메모.md").write_text("# 정리 안 된 메모\n연차 관련 낙서.\n", encoding="utf-8")

    return tmp_path
