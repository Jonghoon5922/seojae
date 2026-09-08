# 서재 (Seojae) — 스펙 (확정본)

> 폴더에 문서를 꽂아두면 Claude가 꺼내 읽는 로컬 RAG MCP 서버.
> 미분류 파일은 인박스에 던져두면 Claude가 정리해준다.
> 패키지명 `seojae-mcp`, CLI 명령 `seojae`.

## 1. 한 줄 정의

사용자가 **루트 폴더 1개** 아래에 하위 폴더(=컬렉션)를 만들고 문서를 넣으면,
도구가 자동으로 색인해서 MCP 서버로 노출한다.
**검색(R)도 분류 판단도 사용자의 Claude가 하고, 이 도구는 재료와 손만 제공한다.**
**개발자(나)는 LLM을 호출하지 않는다. 호스팅 서버도 없다.** (비용 0, 데이터 유출 0)

## 2. 두 개의 축

| 축 | 흐름 | 이 도구의 역할 | Claude의 역할 |
|---|---|---|---|
| **꺼내 읽기 (검색)** | 질문 → 컬렉션 선택 → 청크 검색 → 출처 있는 답변 | 색인·검색·출처 | 컬렉션 선택, 답변 생성 |
| **꽂아 넣기 (정리)** | `_inbox\`에 파일 투입 → 내용 발췌 노출 → 분류 판단 → 이동 | 발췌 제공·파일 이동·되돌리기 | 어느 컬렉션인지 판단, 이름 제안 |

두 축 모두 같은 원칙을 따른다: **판단은 사용자의 LLM이, 실행은 로컬 도구가.**

## 3. 확정된 설계 결정

| 항목 | 결정 | 이유 |
|---|---|---|
| 접근 범위 | 실행 시 지정한 루트 폴더 1개. 바깥은 절대 접근 불가 | 사용자가 "Claude가 어디까지 보나"를 명확히 알게 |
| 컬렉션 | 루트 직속 하위 폴더 = 컬렉션. 그 아래 하위 폴더는 컬렉션 내부 구조로 함께 색인 | 폴더 정리 = 지식베이스 설계 |
| 인박스 | `{root}\_inbox\` = 미분류 투입구. 루트 직속 파일도 인박스로 취급 | 던져두면 나중에 정리하는 자리 |
| 인박스 색인 | 색인은 하되 컬렉션 검색 결과에는 기본 제외 (`include_inbox=true`로 포함) | 정리 안 된 것이 답변을 오염시키지 않게 |
| 컬렉션 정의 | 각 폴더의 `README.md` 프론트매터 (`name`, `description` 필수, `tags`, `updated` 선택) | 스킬 SKILL.md와 같은 관습. description이 Claude의 라우팅 근거 |
| README 없을 때 | 폴더명을 name, 파일명·헤딩을 모아 description 자동 생성 | 동작은 항상 되게 |
| 검색 엔진 | 1단계 BM25(SQLite FTS5) + 한국어 형태소(kiwipiepy). 임베딩은 6단계(로컬 모델, 옵션) | 모델 없이 즉시 동작. RAG의 R을 가볍게 시작 |
| 생성(G)·분류 판단 | 사용자의 Claude가 수행 | A 구조 (사용자의 LLM) |
| 파일 형식 | md, txt, pdf, docx | 1단계 범위 |
| 청킹 | 마크다운 헤딩 / PDF 페이지 / docx 문단 단위. 청크마다 출처(파일, 위치) 저장 | 출처 반환이 신뢰의 핵심 |
| 색인 저장 | `{root}\.seojae\index.db` (SQLite 파일 1개). 삭제하면 재색인 | 단순 |
| 증분 색인 | 파일 해시로 변경분만. watchdog 파일 감시 | 파일 추가하면 자동 반영 |
| 파일 이동 | 루트 내부로만. 덮어쓰기 금지(충돌 시 접미사). 이동 로그 남겨 `undo` 가능 | 되돌릴 수 없는 정리는 안 함 |
| 중복 제거 | 같은 본문의 청크는 상위 1건만 반환하고 나머지는 `also_in`으로 표시 | 같은 절이 개별·통합 설계서에 복사돼 상위 K개를 잡아먹는 문제 (실측 확인) |
| 수기 확인 | 로컬 웹 UI (`seojae ui`, 127.0.0.1 전용) | 사용자가 Claude 없이도 직접 봄 |
| 배포 | Python 패키지(uvx). `.mcpb` 번들은 6단계 | 로컬 설치형 |
| 보안 | `..` 경로 탈출 차단, 루트 밖 심볼릭 링크 무시, UI는 localhost만 바인딩 | |

## 4. MCP 도구

### 검색 축

| 도구 | 입력 | 반환 |
|---|---|---|
| `list_collections` | 없음 | `[{name, description, tags, doc_count, updated}]` |
| `list_documents` | `collection` | `[{id, title, path, pages, indexed_at}]` |
| `search` | `query`, `collection?`, `top_k=5`, `include_inbox=false` | `[{text, collection, source, location, score}]` |
| `get_document` | `id`, `section?` | 원문 텍스트 (섹션·페이지 단위) |

### 정리 축

| 도구 | 입력 | 반환 |
|---|---|---|
| `list_inbox` | `limit=20` | `[{id, filename, size, added_at, excerpt}]` — 분류 판단용 본문 발췌 포함 |
| `file_document` | `id`, `collection`, `new_name?` | 실제 파일 이동 + 재색인. 이동 로그 기록 |
| `describe_collection` | `collection` | 그 컬렉션의 문서 제목·헤딩·발췌 모음 — README를 쓰기 위한 재료 |
| `write_collection_readme` | `collection`, `name`, `description`, `tags?` | README.md 프론트매터 갱신 (본문 보존, 기존 파일 백업) |

`file_document`는 파일을 실제로 옮긴다. 되돌리기는 CLI `seojae undo`로 한다.

**책장 설명도 AI가 쓴다.** `describe_collection`으로 재료를 받아 Claude가 description을 작성하고
`write_collection_readme`로 저장한다. 사람은 README.md를 직접 고치거나 웹 UI에서 수정하면 된다.
description이 곧 라우팅 근거이므로, 설명이 좋아지면 검색 정확도가 통째로 올라간다.

서버 instructions에 컬렉션 description 목록을 자동 주입한다:

```
이 서재에는 다음 컬렉션이 있다. 질문에 맞는 컬렉션을 골라 search를 호출하라.
- 업무규정: 회사 취업규칙·경비·출장 지침…
- bxm-guide: BXM 프레임워크 규약과 NEFSS→BXM 전환 가이드…

정리 안 된 파일이 3건 있다. list_inbox로 확인하고 file_document로 분류할 수 있다.
```

## 5. CLI

| 명령 | 동작 |
|---|---|
| `seojae init <root>` | 루트 초기화, `_inbox\` 및 예시 폴더·README 골격 생성 |
| `seojae serve <root>` | 색인 후 MCP(stdio) 서버 + 파일 감시 |
| `seojae ui <root>` | 로컬 웹 UI 실행 (localhost:8765) |
| `seojae status <root>` | 컬렉션별 문서 수, 인박스 건수, 마지막 색인 시각, 실패 파일 |
| `seojae reindex <root>` | 전체 재색인 |
| `seojae undo <root>` | 마지막 파일 이동 되돌리기 |

## 6. README.md 형식 (컬렉션 정의)

```markdown
---
name: bxm-guide
description: BXM 프레임워크 규약과 NEFSS→BXM 전환 가이드. Service/Bean/DBIO 계층 구조, .omm 문법, 예외 처리 규약, 전환 원칙 질문에 사용.
tags: [BXM, NEFSS, 전환]
updated: 2026-09-01
---

# BXM 전환 가이드
- bxm-architecture.md — BXM 규약 정본
- nefss-bxm-전환가이드.md — 전환 절차, 대응표
```

- `description`은 "어떤 질문에 이 컬렉션을 써야 하는지"를 적는다 (스킬 description과 같은 역할)
- 프론트매터 아래 본문은 사람용 설명이며 검색 대상에 포함, 검색 시 약간 가중
- 인박스 분류 시 Claude가 읽는 판단 근거도 이 `description`이다

## 7. 웹 UI (MVP)

두 화면.

**서재 화면 (검색 확인)**
- 좌측: 컬렉션 트리(문서 수), 상태(마지막 색인, 실패 건수), 재색인 버튼
- 우측: 검색창(Claude와 **동일한 검색 함수**), 결과 목록(출처·점수), 문서 보기(청크 경계·하이라이트)
- 목적: Claude가 답한 근거를 같은 검색어로 재현, PDF 파싱 품질 확인

**인박스 화면 (정리)**
- 미분류 파일 목록 + 발췌 미리보기
- 각 파일을 컬렉션으로 이동 (드롭다운 또는 드래그)
- Claude가 `file_document`로 옮긴 내역과 되돌리기 버튼
- 목적: AI 분류 결과를 사람이 승인·수정하는 자리

구현: FastAPI + 정적 HTML 한 장. 별도 빌드 도구 없음

## 8. 내부 구조

```
_inbox\  ──┐
컬렉션 폴더 ─┴→ 파일 감시 → 파서(md/txt/pdf/docx) → 청킹 → SQLite(FTS5 BM25 + kiwi 토큰)
                                                            ├── MCP 서버(stdio)  ← Claude
                                                            └── 웹 UI(localhost) ← 사람
                       파일 이동(file_document) ← 분류 판단 ← Claude
```

스택: Python 3.11+, FastMCP, SQLite FTS5, kiwipiepy, pypdf, python-docx, watchdog, FastAPI, uv

## 9. 구현 단계

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 | 골격, 파서, 청킹, BM25 색인, `status`/`reindex` | 테스트 데이터 색인 후 CLI로 검색 결과 확인 |
| 2 | 검색 축 MCP 도구 4개 + instructions 주입 | Claude Code에서 연결해 실제 질문 → 출처 있는 답변 |
| 3 | 파일 감시 증분 색인, `init` | 파일 추가 시 자동 반영 |
| 4 | 인박스 + 정리 축 (`list_inbox`, `file_document`, `undo`, `describe_collection`, `write_collection_readme`) | 인박스에 파일 던지고 Claude에게 "정리해줘" → 올바른 컬렉션으로 이동 + 책장 설명 자동 작성 |
| 5 | 웹 UI (서재 화면 + 인박스 화면) | 검색·문서 보기·재색인·수동 분류 동작 |
| 6 (이후) | 로컬 임베딩 하이브리드, `.mcpb` 번들, 패키지 배포 | |

## 10. 테스트 데이터

`C:\poc\internal-docs\workspace\docs\` 와 `templates\bxm-architecture.md` 를 `testdata\seojae\bxm-guide\` 로 복사해서 첫 컬렉션으로 쓴다.
(고객 원본 소스 `asis\` 는 포함하지 않는다)

## 11. 배경 (왜 이 제품인가)

- AI 시장용 개인 프로젝트(포트폴리오/학습). 이전 프로젝트: tokenbill(토큰 사용량), aicv
- 후보 검토 결과 "사용자의 LLM이 돌고 나는 도구만 제공하는" 구조(A)로 한정 — LLM 비용 부담 없음

### 경쟁 현황 (2026-09 조사)

"로컬 폴더를 RAG로 색인해 MCP로 노출"은 이미 여러 구현이 있다.

| 프로젝트 | 성격 |
|---|---|
| shinpr/mcp-local-rag | 가장 가까움. PDF·DOCX·MD 색인, 하이브리드 검색, MCP+CLI |
| Daniel-Barta/mcp-rag-server | 코드 저장소 색인, 임베딩(로컬/OpenAI), 출처 반환 |
| sebastianhutter/local-rag | Obsidian·이메일·Calibre·RSS·git을 프로젝트 단위 색인 |
| weston-barger/ragtag-mcp | 심플 벡터DB 색인·검색 |
| bixentemal/mcp-ragnar | txt/md/pdf/docx, 문장 윈도우 검색 |

**전부 검색 도구다.** 차별점은 다음 네 가지에 둔다.

1. **폴더 = 컬렉션 + README 프론트매터 라우팅** — 남들은 전체 색인 한 덩어리에 top_k를 던진다. 우리는 Claude가 "어느 서랍을 열지" 먼저 고르게 한다. 문서가 늘어날수록 격차가 커진다
2. **한국어 형태소 검색** — 위 프로젝트는 전부 영어권. 한국어 문서에서 임베딩 없이 쓸 만한 것이 없다
3. **미분류 인박스 + AI 정리** — 검색만이 아니라 정리해주는 도구. 위 다섯 중 아무도 하지 않는다
4. **모델 다운로드 0** — 설치 즉시 동작. 임베딩은 옵션

## 12. 임베딩이 필요한가 (1단계 실측)

테스트 데이터 576문서 / 19,640청크로 측정한 결과.

| 질문 | 결과 |
|---|---|
| "예외 처리는 어떻게 해야 하나" (문서 어휘와 일치) | 정확한 절을 1위로 |
| "omm 파일 문법" | 규약 정본을 1위로 |
| "에러 났을 때 어떻게 처리하지" (에러 ≠ 예외) | 실패 — 무관한 문서 |
| "데이터베이스 접근 계층" (문서는 DBIO) | 실패 — 무관한 문서 |

BM25의 한계는 **어휘 불일치**에서만 나타난다. 결론:

- **기본은 BM25 유지.** 고객이 AI라는 점이 여기서 유리하다. 사람은 검색어를 한 번 던지고 말지만
  Claude는 결과가 부실하면 말을 바꿔 재검색한다. 키워드 검색의 최대 약점을 고객이 메운다
- **재검색을 유도하는 것이 1순위 대책.** `search`가 최고 점수를 함께 돌려주고, 점수가 낮으면
  그 컬렉션의 주요 용어를 힌트로 붙인다 → Claude가 스스로 다시 검색한다 (2단계에서 구현)
- **임베딩은 그 뒤에도 남는 격차에 대해서만.** 다국어 모델은 최소 100MB대 다운로드 + CPU 추론이라
  "설치 즉시 동작"이라는 차별점을 정면으로 깎는다. 6단계 옵션으로 유지한다

## 13. 로드맵 (아주 나중 이야기)

| 단계 | 형태 | 비고 |
|---|---|---|
| 지금 | 로컬 전용 (stdio MCP + 로컬 웹 UI) | 데이터가 사용자 PC를 떠나지 않음 |
| 다음 | 사용자가 직접 세운 서버 (사내 공용 서재) | 여러 사람이 같은 서재를 열람 |
| 그 다음 | 내가 호스팅하는 서비스 | 계정·권한·과금이 붙음 |

이 로드맵을 위해 지금 지키는 것: **파일 접근은 전부 `paths.py`를 통과한다.**
저장소가 로컬 파일시스템에서 다른 것으로 바뀌어도 갈아끼울 지점을 한 곳으로 모아둔다.
파서·청킹·토크나이저는 저장소를 모른다.
