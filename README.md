# 서재 (Seojae)

[![PyPI](https://img.shields.io/pypi/v/seojae-mcp)](https://pypi.org/project/seojae-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/seojae-mcp)](https://pypi.org/project/seojae-mcp/)
[![License](https://img.shields.io/pypi/l/seojae-mcp)](LICENSE)

**폴더에 문서를 꽂아두면 Claude가 꺼내 읽는 로컬 RAG MCP 서버.**

문서를 폴더에 정리해두면 자동으로 색인해서 MCP로 노출한다.
Claude가 질문에 맞는 책장을 골라 검색하고, **출처(파일·위치)를 붙여** 답한다.

```
질문: "예외 처리 규약이 어떻게 되지?"

Claude → search(query="예외 처리 규약", collection="개발가이드")
       ← 3건, 각각 출처 포함

답변: 업무예외는 DefaultApplicationException으로 던진다.
      (출처: 개발가이드/아키텍처.md · "예외 처리" 절)
```

문서는 **PC를 떠나지 않는다.** 네트워크 전송 없음, 외부 API 호출 없음, 계정 없음.

> [!NOTE]
> 5단계까지 동작한다. [PyPI](https://pypi.org/project/seojae-mcp/)에 배포돼 있고 Claude Desktop용 `.mcpb` 번들도 있다.

---

## 이 프로젝트가 LLM을 부르지 않는 이유

RAG는 **R**etrieval(검색)과 **G**eneration(생성)으로 나뉜다.
보통은 도구가 둘 다 하지만, 서재는 **검색만 한다.**

| | 하는 일 | 누가 |
|---|---|---|
| **R** | 색인·검색·출처 | 서재 (로컬) |
| **G** | 답변 생성 | 사용자의 Claude |

생성을 사용자의 LLM에 맡기면 세 가지가 따라온다.

- **비용 0** — 내가 낼 API 요금이 없다. 사용자도 이미 내고 있는 구독을 그대로 쓴다
- **유출 0** — 문서가 내 서버로 갈 일이 없다. 애초에 서버가 없다
- **모델 선택 자유** — 사용자가 쓰는 모델이 곧 이 도구의 성능이다

같은 원리를 **분류**에도 적용한다. 미분류 파일을 어느 책장에 꽂을지 판단하는 것도
LLM의 일이지만, 서재는 판단하지 않는다. **읽을 재료(본문 발췌)와 옮기는 손(파일 이동)만 제공하고,
판단은 사용자의 Claude가 한다.**

---

## 도서관 비유

| 도서관 | 서재 |
|---|---|
| 반납대·미정리 도서 | `_inbox\` 미분류 파일 |
| 사서가 분류해 배가 | Claude가 판단 → `file_document`가 실제 이동 |
| 서가·청구기호 | 컬렉션 폴더 + `README.md` 프론트매터 |
| 열람 요청 | `search` / `get_document` (출처 포함) |
| **도서관 이용자** | **AI (사용자의 Claude)** |

사서도 손님도 AI지만, **서고와 목록은 로컬에 있다.**

---

## 폴더 구조가 곧 지식베이스 설계다

루트 폴더 하나를 지정한다. 그 **바깥은 어떤 경우에도 읽지 않는다.**

```
내서재\
├── 업무규정\              ← 컬렉션 (책장)
│   ├── README.md             ← 이 책장이 무엇인지 (라우팅 근거)
│   ├── 취업규칙.pdf
│   └── 경비\
│       └── 출장비지침.docx   ← 하위 폴더도 같은 책장으로 색인
├── 개발가이드\
│   ├── README.md
│   └── 아키텍처.md
└── _inbox\                ← 미분류 투입구. 일단 여기 던져둔다
    └── 어제받은문서.pdf
```

각 책장의 `README.md` 프론트매터가 그 책장의 정의다.

```markdown
---
name: 업무규정
description: 회사 취업규칙과 경비 지침. 휴가·출장비·근무시간 질문에 사용.
tags: [규정, 총무]
---

# 업무규정
- 취업규칙.pdf — 근로조건 정본
```

`description`은 "**어떤 질문에 이 책장을 써야 하는지**"를 적는다.
이 문장이 서버 instructions로 주입돼서, Claude가 검색 전에 **어느 서랍을 열지 먼저 고른다.**
README가 없으면 폴더명·파일명·헤딩으로 자동 생성한다 (동작은 항상 되게).

---

## 다른 로컬 RAG MCP 서버와 뭐가 다른가

"로컬 폴더를 RAG로 색인해 MCP로 노출"하는 구현은 이미 여럿 있다
([mcp-local-rag](https://github.com/shinpr/mcp-local-rag),
[mcp-rag-server](https://github.com/Daniel-Barta/mcp-rag-server),
[ragtag-mcp](https://github.com/weston-barger/ragtag-mcp) 등).
**전부 검색 도구다.** 서재는 네 가지를 다르게 한다.

### 1. 책장을 먼저 고르게 한다

남들은 전체 색인 한 덩어리에 `top_k`를 던진다.
서재는 컬렉션마다 설명을 붙여 Claude가 범위를 좁히고 들어가게 한다.
문서가 늘어날수록 이 차이가 커진다.

### 2. 한국어 형태소 검색

kiwipiepy로 형태소를 분석해 색인한다. **색인과 질의에 같은 토크나이저를 쓴다.**
"연차 휴가는 며칠인가요?" → `연차 · 휴가 · 며칠` 로 쪼개 검색한다.
위 프로젝트들은 전부 영어권이라 한국어 문서에서 임베딩 없이 쓸 만한 것이 없다.

### 3. docx의 표를 읽는다

한국 업무 문서, 특히 설계서는 **내용의 대부분이 표 안에 있다.**
python-docx로 문단만 훑는 일반적인 구현은 이걸 통째로 놓친다.
서재는 본문 요소를 문서 순서대로(문단·표 섞어서) 훑어 표까지 추출한다.

### 4. 미분류 인박스 + AI 정리

검색만 하는 게 아니라 **정리해주는** 도구다.
`_inbox\`에 파일을 던져두고 "정리해줘"라고 하면 Claude가 내용을 읽고 책장에 꽂는다.
책장 설명(`README.md`)도 Claude가 쓴다.

```
_inbox\20260907_회의록.md
   ↓  list_inbox — 본문 발췌 + 고를 수 있는 책장 목록
   ↓  Claude가 읽고 판단 (이 도구는 판단하지 않는다)
   ↓  file_document(document_id, "업무규정")
업무규정\20260907_회의록.md   → 곧바로 검색에 잡힌다
```

여기서도 원칙은 같다. **판단은 사용자의 Claude가, 실행은 로컬 도구가.**
`list_inbox`는 분류를 제안하지 않는다. 읽을 재료와 선택지만 준다.

그리고 **모델 다운로드가 0이다.** 설치하면 바로 동작한다.

---

## 검색 품질 실측

한국어 업무 문서 **576건**(md 281 + docx 294, 21MB)으로 측정했다.

| 항목 | 결과 |
|---|---|
| 최초 색인 | 82초 / 19,640청크 / **파싱 실패 0건** |
| 재색인 (변경 없음) | **0.5초** (파일 해시로 스킵) |
| 색인 크기 | SQLite 파일 1개 |

검색 정확도는 **어휘가 일치하느냐**에 갈린다.

| 질문 유형 | 결과 |
|---|---|
| 문서가 쓰는 말로 물음 | 정확한 절을 1위로 반환 |
| 문서에 없는 동의어로 물음 | **빗나감** |

BM25의 정직한 한계다. 임베딩을 붙이는 대신 이렇게 대응한다.

**`search`는 검색어가 각각 몇 개 문서에 나오는지를 항상 함께 돌려준다.**
못 찾았을 때는 그 책장에서 **실제로 쓰는 용어**를 붙여준다. 아래는 실제 응답이다.

```json
{
  "query": "데이터베이스 연결 풀 설정",
  "term_document_counts": { "데이터": 0, "베이스": 0, "연결": 0, "설정": 0 },
  "document_count": 3,
  "results": [],
  "hint": "결과가 없다. 이 서재가 쓰지 않는 말: 데이터, 베이스, 연결, 설정.
           '개발가이드' 책장에서 실제로 쓰는 용어: 계층, repository, 예외, 아키텍처,
           의존, 트랜잭션, service, controller, … 이 용어들로 바꿔 다시 검색하라."
}
```

점수에 임계값을 걸어 "실패했다"고 판정하지 않는다. BM25 점수의 절대값은 질의마다 달라
믿을 수 없기 때문이다. **사실만 돌려주고 판단은 손님이 한다.**

`hint`가 붙는 경우는 둘뿐이다 — 결과가 없거나, **내용어의 절반 이상이 색인에 없을 때.**
잘 된 검색에는 붙지 않는다.

```json
{
  "query": "연차 휴가 며칠",
  "term_document_counts": { "연차": 1, "휴가": 1, "며칠": 0 },
  "results": [ { "source": "업무규정/취업규칙.md", "location": "취업규칙 > 연차 유급휴가", … } ],
  "hint": ""
}
```

"며칠"은 문서에 없지만 검색은 성공했다. 이럴 때 재검색하라고 하면 잔소리가 된다 —
사실(`며칠: 0`)만 보여주고 판단은 맡긴다.

여기서 고객이 AI라는 점이 유리하게 작용한다.
사람은 검색어를 한 번 던지고 말지만, **Claude는 결과가 부실하면 말을 바꿔 다시 검색한다.**
키워드 검색의 최대 약점을 손님이 메운다.

### 시도했다가 버린 규칙 둘

재검색을 유도하는 장치가 **오탐을 내면 없느니만 못하다.** 두 규칙을 실측으로 폐기했다.

| 버린 규칙 | 반증한 사례 |
|---|---|
| 색인에 없는 말이 하나라도 섞이면 | "연차 휴가 며칠" — 검색은 정확한데 "며칠" 때문에 발동 |
| 검색어가 전부 흔한 말이면 (25% 이상) | "예외 처리는 어떻게" — 예외 47%, 처리 68%로 둘 다 흔하지만 결과는 정확 |

두 번째가 특히 반직관적이다. **문서 집합이 동질적이면 도메인 용어가 원래 흔하다.**
576건이 전부 같은 주제인 서재에서 "예외"가 47%에 나오는 건 당연하고, 그게 쓸모없다는 뜻이 아니다.
그 가중은 BM25가 이미 IDF로 처리한다.

남은 두 규칙은 실측에서 **오탐 0건**이다. 대신 동의어 불일치는 여전히 놓친다 —
단어가 색인에 있긴 한데 엉뚱한 문서에 있을 때. [SPEC.md](SPEC.md) 12절에 한계로 기록해뒀다.

---

## 시작하기

[uv](https://docs.astral.sh/uv/)만 있으면 설치할 것이 없다. `uvx`가 알아서 받아 실행한다.

```bash
uvx seojae-mcp init 내서재
```

```
서재를 만들었다: C:\내서재

  + 내서재\
  + 내서재\_inbox\
  + 내서재\_inbox\여기에-던져두세요.txt
  + 내서재\예시책장\
  + 내서재\예시책장\README.md
```

폴더를 만들고 문서를 넣은 뒤 색인한다. **폴더 하나가 책장 하나다.**

```bash
uvx seojae-mcp reindex 내서재
```

```
서재: C:\내서재
색인 완료 1.9초 — 새로 읽음 7 / 변경 없음 0 / 실패 0 / 삭제 0 / 청크 17
```

상태를 본다.

```bash
uvx seojae-mcp status 내서재
```

```
마지막 색인: 2026-09-08T15:07:03+09:00

┌────────────┬──────┬──────┬────────┬─────────────────────────────────────────────────┐
│ 컬렉션     │ 문서 │ 청크 │ README │ 설명                                            │
├────────────┼──────┼──────┼────────┼─────────────────────────────────────────────────┤
│ 개발가이드 │    3 │    8 │ O      │ 서비스 아키텍처 규약과 코딩 컨벤션. 계층 구조,  │
│            │      │      │        │ 예외 처리, 네이밍 규칙 질문에 사용.             │
│ 업무규정   │    3 │    8 │ O      │ 회사 취업규칙과 경비 지침. 휴가·출장비·근무시간 │
│            │      │      │        │ 질문에 사용.                                    │
│ _inbox     │    1 │    1 │ 자동   │ 아직 어느 책장에도 꽂히지 않은 파일.            │
│            │      │      │        │ list_inbox로 확인하고 분류한다.                 │
└────────────┴──────┴──────┴────────┴─────────────────────────────────────────────────┘
```

README가 없는 폴더는 `자동`으로 표시되고, 폴더명·파일명·헤딩으로 설명을 만들어 쓴다.

검색해본다. **Claude가 쓰는 것과 완전히 같은 함수다.**

```bash
uvx seojae-mcp search 내서재 "연차 휴가 며칠" -k 2
```

```
1. 업무규정 업무규정/취업규칙.md · 취업규칙 > 연차 유급휴가 · score 4.2771
## 연차 유급휴가
1년간 80퍼센트 이상 출근한 근로자에게 15일의 연차 유급휴가를 부여한다.
계속 근로 기간이 1년 미만인 근로자에게는 1개월 개근 시 1일의 휴가를 준다.
3년 이상 계속 근로한 경우 최초 1년을 초과하는 매 2년마다 1일을 가산한다.
```

출처가 파일 경로에서 끝나지 않고 **헤딩 경로**(`취업규칙 > 연차 유급휴가`)까지 붙는다.
PDF는 `p.7`, docx는 절 제목이 같은 자리에 들어간다.

### Claude Desktop — 더블클릭 설치

[Releases](https://github.com/Jonghoon5922/seojae/releases)에서 `seojae-0.1.0.mcpb`를 받아
**더블클릭**하면 설치 화면이 뜬다. 거기서 서재로 쓸 폴더를 고르면 끝이다.

> uv가 미리 깔려 있어야 한다 (`winget install --id astral-sh.uv` 또는 `brew install uv`).
> 서재 본체는 첫 실행 때 자동으로 받는다.
> macOS는 GUI 앱이 셸 PATH를 물려받지 않으므로 `brew`로 설치하는 편이 안전하다.

### Claude Code — 설정 세 줄

`.mcp.json`(Claude Code) 또는 Claude Desktop 설정에 이 세 줄을 넣는다.
**미리 설치할 것도, 서버를 띄워둘 것도 없다.** Claude가 필요할 때 실행하고 끝나면 정리한다.

```json
{
  "mcpServers": {
    "seojae": {
      "command": "uvx",
      "args": ["seojae-mcp", "serve", "C:/내서재"]
    }
  }
}
```

세션을 새로 열면 도구 8개가 붙는다.

**꺼내 읽기**

| 도구 | 하는 일 |
|---|---|
| `list_collections` | 책장 목록과 설명 |
| `list_documents` | 한 책장의 문서 목록 |
| `search` | 검색 (출처·점수·재검색 힌트 포함) |
| `get_document` | 문서 원문 (`section`으로 부분만) |

**꽂아 넣기**

| 도구 | 하는 일 |
|---|---|
| `list_inbox` | 미분류 파일 + 분류 판단용 발췌 + 고를 수 있는 책장 |
| `file_document` | 파일을 책장으로 이동 (되돌릴 수 있게 기록) |
| `describe_collection` | 책장 설명을 쓸 재료 (제목·헤딩·발췌·빈출어) |
| `write_collection_readme` | 쓴 설명을 README 프론트매터로 저장 |

서버가 뜰 때 **책장 목록과 설명이 instructions로 자동 주입된다.**
Claude는 어떤 책장이 있는지 알고 시작한다.

---

## CLI

```
seojae init      <root>          서재 골격 생성 (인박스·예시 책장·README 틀)
seojae reindex   <root>          루트 전체 색인 (변경분만)
seojae status    <root>          컬렉션별 문서 수·마지막 색인·실패 파일
seojae documents <root>          색인된 문서 목록
seojae search    <root> <query>  검색
seojae show      <root> <id>     문서 원문 보기
seojae inbox     <root>          미분류 파일 목록 (Claude가 보는 것과 같은 내용)
seojae moves     <root>          파일을 옮긴 기록
seojae undo      <root>          마지막 이동·README 수정 되돌리기
seojae serve     <root>          MCP(stdio) 서버 + 파일 감시
```

`init`은 **이미 있는 파일을 절대 덮어쓰지 않는다.** 쓰던 폴더에 다시 실행해도 안전하다.

---

## 웹 UI — 사람이 근거를 확인하는 자리

```bash
uvx seojae-mcp ui 내서재
```

`http://127.0.0.1:8765`. **127.0.0.1에만 바인딩한다.** 네트워크에 열리지 않는다.

화면은 셋이다.

- **검색** — 왼쪽에 책장, 오른쪽에 검색. 결과마다 출처·점수·검색어별 문서 수가 붙는다.
  출처를 누르면 그 문서가 **헤딩 목차로 펼쳐지고 찾던 대목만 열린 채** 표시된다
- **인박스** — 미분류 파일의 발췌를 보고 책장을 골라 옮긴다 (Claude가 한 분류를 사람이 고치는 자리)
- **기록** — 옮긴 내역과 되돌리기

여기서 중요한 건 **UI가 Claude와 같은 검색 함수를 호출한다**는 점이다.
따로 만든 검색이면 "근거 재현"이 아니라 흉내다. 테스트로 두 결과가 같은지 확인한다.

```python
web = client.get("/api/search", params={"q": query}).json()
direct = search(conn, query)            # Claude가 쓰는 그 함수
assert [r["source"] for r in web["results"]] == [h.source for h in direct]
```

MCP 서버와 웹 UI는 **한 프로세스에서 같은 색인을 공유**한다.
Claude가 파일을 옮기면 브라우저를 새로고침하는 즉시 반영된다.

---

## 파일을 옮길 때의 규칙

AI가 파일을 옮긴다는 건 겁나는 일이다. 그래서 규칙을 코드로 강제한다.

| 규칙 | 어떻게 |
|---|---|
| 루트 밖으로 안 나간다 | 책장 이름에 경로·`..`·예약어 금지, 이동 직전 재확인 |
| 아무것도 덮어쓰지 않는다 | 이름이 겹치면 `이름 (2).md`. README는 고치기 전에 사본을 남긴다 |
| 전부 되돌릴 수 있다 | 모든 이동을 기록 → `seojae undo` |
| 확장자를 안 바꾼다 | 확장자가 바뀌면 파서가 달라진다 |
| 새 책장은 명시적으로만 | 없는 책장은 거부하고 **있는 책장을 알려준다.** 만들려면 플래그가 필요하다 |
| 남의 파일은 안 건드린다 | undo로 폴더를 치울 때 그 사이 다른 파일이 들어왔으면 남긴다 |

거부당하면 이렇게 돌아온다 — Claude가 다음에 뭘 해야 할지 알 수 있게.

```
'없는책장' 책장이 없다. 있는 책장: 개발가이드, 업무규정.
새로 만들려면 create_collection=true로 다시 호출하라.
```

---

## 폴더에 넣으면 끝

`serve`가 떠 있는 동안에는 재색인 명령을 칠 일이 없다. 파일을 넣거나 고치거나 지우면
알아서 따라온다.

| 동작 | 검색에 반영되기까지 |
|---|---|
| 파일 생성 | 1.3초 |
| 파일 수정 | 1.3초 |
| 파일 삭제 | 0.2초 |

파일 시스템 이벤트를 그대로 믿으면 안 되는 경우가 둘 있어서, 그만큼만 기다린다.

- **에디터는 저장 한 번에 이벤트를 여러 개 뱉는다** (쓰기 → 임시파일 → 이름 변경 …).
  마지막 이벤트 이후 1초 잠잠해지면 그때 한 번만 처리한다
- **복사가 끝나기 전에 이벤트가 먼저 온다.** 윈도우에서 큰 파일을 복사하면 생성 이벤트
  시점에 파일이 아직 잠겨 있다. 실패하면 0.5 / 1.5 / 3초 뒤 다시 시도한다

삭제는 기다리지 않는다. 지운 파일이 검색 결과에 남아 있는 쪽이 더 나쁘다.

---

## 어떻게 동작하나

```
_inbox\  ──┐
컬렉션 폴더 ─┴→ 파서(md/txt/pdf/docx) → 청킹 → SQLite (FTS5 BM25 + 형태소 토큰)
                                                  ├── MCP 서버(stdio) ← Claude
                                                  └── 웹 UI(localhost) ← 사람
```

**파서** — 마크다운은 헤딩 경로, PDF는 페이지, docx는 문단과 표.
청크마다 출처를 붙인다. 출처 없는 검색 결과는 만들지 않는다.

**청킹** — 헤딩·페이지 경계를 넘어 합치지 않는다. 출처가 흐려지면 안 되니까.

**색인** — `{root}\.seojae\index.db` 하나. 지우면 전체 재색인된다.
파일 해시로 변경분만 다시 읽는다.

**중복 제거** — 같은 본문이 여러 문서에 복사돼 있으면 상위 1건만 돌려주고
나머지는 `also_in`으로 알려준다. (실제 문서에서 개별 설계서와 통합 설계서가
상위 결과를 나눠 먹는 문제가 있었다)

---

## 설계 원칙

- **루트 폴더 하나.** 바깥은 읽지도 쓰지도 않는다. 경로를 다루는 코드는 전부
  [`paths.py`](src/seojae/paths.py)를 통과한다. `..` 탈출과 루트 밖 심볼릭 링크를 막는다
- **모든 검색 결과에 출처가 붙는다.** 파일 경로와 위치(헤딩·페이지)
- **파일을 옮기는 동작은 되돌릴 수 있어야 한다.** 이동 로그 + `undo`
- **로컬 우선.** 네트워크 전송 없음, 웹 UI는 127.0.0.1만 바인딩

---

## 진행 상태

- [x] 스펙 확정 ([SPEC.md](SPEC.md))
- [x] **1단계** — 골격·파서·청킹·형태소 BM25 색인·CLI
- [x] **2단계** — 검색 축 MCP 도구 4개 + instructions 주입
- [x] **3단계** — 파일 감시 증분 색인, `init`
- [x] **4단계** — 인박스 + 정리 축 (분류·되돌리기·책장 설명 작성)
- [x] **5단계** — 웹 UI (검색 근거 재현 + 인박스 정리)
- [x] **패키지 배포** — [PyPI `seojae-mcp`](https://pypi.org/project/seojae-mcp/)
- [x] **`.mcpb` 번들** — Claude Desktop 더블클릭 설치
- [ ] 로컬 임베딩 (옵션)

설계 결정과 그 근거는 전부 [SPEC.md](SPEC.md)에 있다.

---

## 스택

Python 3.11+ · [uv](https://docs.astral.sh/uv/) · MCP Python SDK · SQLite FTS5 ·
[kiwipiepy](https://github.com/bab2min/kiwipiepy) · pypdf · python-docx · watchdog · FastAPI

### 소스에서 개발하려면

```bash
git clone https://github.com/Jonghoon5922/seojae.git
cd seojae
uv sync
uv run pytest
```

`uv run seojae <명령>` 으로 실행한다. 웹 UI를 띄우려면 `uv run seojae ui testdata/내서재`.

---

## English

**Seojae** (서재, "study" / personal library) is a local RAG MCP server for Korean documents.

Drop files into folders, and Claude reads them back with citations.
Each top-level folder is a *collection* whose `README.md` front matter describes
**what questions it answers** — injected into the server instructions so Claude picks
the right shelf before searching, instead of throwing `top_k` at one big index.

**It never calls an LLM.** It does retrieval only; generation stays with the user's Claude.
No API cost, no data leaving the machine, no server.

Built for Korean: morphological indexing via kiwipiepy (same tokenizer for indexing and
querying), and a docx parser that walks paragraphs *and tables* in document order —
Korean design documents keep most of their content inside tables, which paragraph-only
parsers silently drop.

Measured on 576 real Korean business documents (21MB): 82s initial index,
19,640 chunks, zero parse failures, 0.5s incremental reindex.

Instead of guessing whether a search failed, `search` always returns how many documents
each query term appears in — so the model can tell "not in this library" from
"too common to discriminate" and re-query in the library's own vocabulary.

A watcher keeps the index current while the server runs — drop a file in and it is
searchable in about a second, with no reindex command. Filesystem events are not trusted
directly: editors emit several per save (debounced), and on Windows a large file is still
locked when its creation event arrives (retried).

Status: stages 1–5 of 6 complete. See [SPEC.md](SPEC.md) (Korean) for design decisions.

---

## 라이선스

MIT
