# MCPB 번들 소스

Claude Desktop에 더블클릭으로 설치되는 `.mcpb` 파일을 만드는 자리다.

```bash
npx @anthropic-ai/mcpb validate mcpb/manifest.json
npx @anthropic-ai/mcpb pack mcpb dist/seojae-0.1.0.mcpb
```

## 왜 코드를 번들에 넣지 않았나

서재 본체는 [PyPI](https://pypi.org/project/seojae-mcp/)에 있고, 번들은 **실행 방법만** 담는다.
그래서 6KB다.

파이썬 서버를 번들로 만드는 방법은 셋인데, 앞의 둘은 우리에게 맞지 않았다.

| 방법 | 왜 안 썼나 |
|---|---|
| `type: "python"` + 의존성 동봉 | kiwipiepy가 컴파일 확장이라 플랫폼별 바이너리가 필요하다. numpy까지 합치면 수십 MB를 OS별로 따로 빌드해야 한다 |
| `type: "uv"` (호스트가 파이썬 관리) | 매니페스트 문서에는 있으나 **CLI 2.1.2의 검증기가 아직 거부한다** (`python \| node \| binary`만 허용). 나중에 열리면 이쪽으로 옮기는 게 맞다 |
| **`type: "binary"` + `uvx`** | 지금 쓰는 방식. `uvx seojae-mcp serve <폴더>` 를 그대로 실행한다 |

## 대가

**사용자 PC에 uv가 필요하다.** "더블클릭 설치"라는 말이 완전히 참은 아니다.
매니페스트 설명에 설치 명령을 적어뒀고, 서재 본체는 첫 실행 때 uv가 PyPI에서 알아서 받는다.

**macOS 주의** — GUI 앱은 셸의 PATH를 물려받지 않는다.
`curl | sh` 로 설치하면 `~/.local/bin` 에 들어가서 Claude Desktop이 `uvx`를 못 찾을 수 있다.
`brew install uv` 를 권한다.

## 파일

| 파일 | 역할 |
|---|---|
| `manifest.json` | 번들 정의. `user_config.root` 가 설치 UI의 폴더 선택기가 된다 |
| `icon.png` | 512×512 |
| `server.py` | `entry_point` 로 선언된 진입점. 실제 기동은 `uvx`가 하지만, `uv run --directory . server.py <폴더>` 로도 뜬다 |
| `pyproject.toml` | 위 폴백이 의존성을 찾을 수 있게 두는 것. `seojae-mcp` 하나만 참조한다 |

## 서명

지금은 서명하지 않았다. Claude Desktop이 "서명되지 않음"으로 표시한다.
서명하려면 인증서가 필요하다 (`mcpb sign`).
