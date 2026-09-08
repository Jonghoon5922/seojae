"""한국어 형태소 토크나이저.

색인과 질의에 같은 토크나이저를 쓴다. 이게 이 프로젝트의 검색 품질 근거다.
kiwipiepy를 쓰되, 없거나 초기화에 실패하면 정규식 토크나이저로 떨어진다(동작은 항상 되게).
"""

from __future__ import annotations

import re
import threading

# 검색에 의미가 있는 품사만 남긴다.
# 체언·용언 어간·부사·외국어(SL)·한자(SH)·숫자(SN)·어근(XR)
_KEEP_PREFIXES = ("NN", "NR", "NP", "VV", "VA", "VX", "MAG", "MAJ", "SL", "SH", "SN", "XR")

# 조사·어미만 남은 1글자 노이즈 제거용
_STOP = {"하", "되", "있", "없", "것", "수", "때", "등", "및", "그", "이", "저"}

_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")

_kiwi = None
_kiwi_lock = threading.Lock()
_kiwi_failed = False


def _get_kiwi():
    global _kiwi, _kiwi_failed
    if _kiwi is not None or _kiwi_failed:
        return _kiwi
    with _kiwi_lock:
        if _kiwi is None and not _kiwi_failed:
            try:
                from kiwipiepy import Kiwi

                _kiwi = Kiwi()
            except Exception:  # 모델 없음 등 — 폴백으로 계속 동작
                _kiwi_failed = True
    return _kiwi


def _fallback_tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def tokenize(text: str) -> list[str]:
    """텍스트를 검색 토큰 목록으로. 색인·질의 양쪽에서 동일하게 쓴다."""
    if not text or not text.strip():
        return []

    kiwi = _get_kiwi()
    if kiwi is None:
        return _fallback_tokens(text)

    tokens: list[str] = []
    try:
        for token in kiwi.tokenize(text):
            if not token.tag.startswith(_KEEP_PREFIXES):
                continue
            form = token.form.lower()
            if len(form) == 1 and form in _STOP:
                continue
            tokens.append(form)
    except Exception:
        return _fallback_tokens(text)

    # 영문·숫자 원형과 그 조각을 함께 넣는다.
    # 원형: "MNz310Bean001" 을 그대로 찾을 수 있게
    # 조각: "getUserName" 을 "user name" 으로도 찾을 수 있게
    seen = set(tokens)
    for word in _WORD_RE.findall(text):
        if not any(c.isascii() and c.isalnum() for c in word):
            continue
        for piece in _identifier_tokens(word):
            if piece not in seen:
                seen.add(piece)
                tokens.append(piece)

    return tokens


# camelCase / PascalCase / snake_case / kebab-case 를 쪼갠다.
# 연속 대문자는 한 덩어리로 둔다 (HTTPServer → http, server)
_IDENT_PARTS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

# 코드에 지천으로 깔려 검색에 도움이 안 되는 조각
_IDENT_STOP = {"get", "set", "is", "has", "the", "a", "an", "of", "to", "in", "on"}


def _identifier_tokens(word: str) -> list[str]:
    """식별자 하나에서 원형과 조각을 뽑는다."""
    lowered = word.lower()
    out = [lowered]

    parts = [p.lower() for p in _IDENT_PARTS.findall(word)]
    if len(parts) < 2:  # 쪼갤 것이 없다
        return out

    for part in parts:
        if len(part) > 1 and part not in _IDENT_STOP and part != lowered:
            out.append(part)
    return out


def tokens_to_fts(tokens: list[str]) -> str:
    """FTS5에 저장할 문자열. 토큰을 공백으로 이어 붙인다."""
    return " ".join(tokens)


def build_match_query(query: str) -> str:
    """질의 문자열을 FTS5 MATCH 식으로. 토큰 OR 결합 후 BM25로 정렬한다."""
    tokens = tokenize(query)
    if not tokens:
        return ""
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    quoted = ['"' + t.replace('"', '""') + '"' for t in seen]
    return " OR ".join(quoted)
