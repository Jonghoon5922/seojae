# 서재 (Seojae)

폴더에 문서를 꽂아두면 Claude가 꺼내 읽고, 미분류 파일은 인박스에 던져두면 Claude가 정리해주는 **로컬 RAG MCP 서버**. 패키지 `seojae-mcp`, CLI `seojae`.

**작업 시작 전 `SPEC.md`를 먼저 읽는다.** 설계 결정은 전부 거기에 있고, 확정된 사항이다.

## 핵심 원칙

- 이 프로젝트 코드는 **LLM을 호출하지 않는다.** 검색(R)과 분류용 재료만 제공하고, 생성(G)과 분류 판단은 사용자의 Claude가 한다.
- 접근 범위는 **루트 폴더 1개.** 바깥 경로는 어떤 경우에도 읽지 않고 쓰지 않는다.
- 모든 검색 결과에는 출처(파일, 위치)가 붙는다.
- 파일을 옮기는 동작은 항상 되돌릴 수 있어야 한다 (이동 로그 + `undo`).
- 로컬 우선: 네트워크 전송 없음, 웹 UI는 127.0.0.1만.

## 두 개의 축

| 축 | 이 도구 | Claude |
|---|---|---|
| 꺼내 읽기 | 색인·검색·출처 | 컬렉션 선택, 답변 생성 |
| 꽂아 넣기 | 발췌 제공·파일 이동·되돌리기 | 어느 컬렉션인지 판단 |

## 스택

Python 3.11+, uv, FastMCP, SQLite FTS5, kiwipiepy, pypdf, python-docx, watchdog, FastAPI

## 진행 상태

- [x] 스펙 확정 (SPEC.md)
- [x] 환경 세팅 (uv, git)
- [ ] 1단계: 골격·파서·청킹·BM25 색인·`status`/`reindex`
- [ ] 2단계: 검색 축 MCP 도구 4개 + instructions 주입, Claude Code 실사용 검증
- [ ] 3단계: 파일 감시 증분 색인, `init`
- [ ] 4단계: 인박스 + 정리 축 (`list_inbox`, `file_document`, `undo`)
- [ ] 5단계: 웹 UI (서재 화면 + 인박스 화면)
- [ ] 6단계: 로컬 임베딩, `.mcpb`, 배포

단계를 끝내면 위 체크박스를 갱신한다.

## 테스트 데이터

`testdata\seojae\` 를 루트로 사용. 첫 컬렉션 `bxm-guide`는 `C:\poc\internal-docs\workspace\docs\` 와 `templates\bxm-architecture.md` 복사본. 고객 원본 소스(`asis\`)는 넣지 않는다. `testdata\`는 git에 커밋하지 않는다.

## 새 세션 시작 문구

```
SPEC.md 읽고 다음 단계 진행해줘
```
