# 동적 사이트 전환 + 웹 기반 딥 리서치 트리거 설계

Date: 2026-04-20
Status: Draft (awaiting user review)

## 배경

현재 market-digest 웹사이트는 `web.build()` 로 사전 생성한 정적 HTML 을 Caddy 가 서빙한다.
읽기 전용 가정 아래 설계했으나, 다음 요구가 추가되며 전제가 바뀐다.

- **웹에서 딥 리서치 트리거**: 상세 페이지 버튼 → claude -p 실행 → 결과 페이지로 이동
- **한국 주식도 딥 리서치** 지원

정적 사이트 + 사이드카 백엔드는 glue 코드가 누적될 리스크. 동적 앱 하나로 통합하는 것이 유지보수상 유리하다.

## 목표

1. FastAPI + Jinja2 기반 동적 서버로 전면 전환
2. 웹에서 딥 리서치를 비동기로 요청·진행 표시·완료 후 자동 이동
3. 한국 티커(`^\d{6}$`) 에 대해 한국 공개 자료 소스로 리서치
4. 진행 중 job 을 **전역에서 확인** 가능 (페이지 이동 시 연속성)

## 범위 밖

- 북마크·태그·메모 등 다른 인터랙션 (후속)
- 본문 풀텍스트 검색 (지금은 카드 필드 검색 유지)
- 서버 재시작 후 job 복구 (in-memory 만; 재요청 허용)
- 다중 사용자 (Cloudflare Access 가 이미 단일 사용자 제한)

## 아키텍처

```
  cron: python -m market_digest.run
    ├─ fetchers → inbox/{date}/*.txt
    ├─ claude summarize → {nas}/{YYYY}/{MM}/{DATE}.json
    ├─ enrich (blurbs)
    └─ (web.build() 제거됨 — 더 이상 static HTML 생성 안 함)

  systemd: market-digest-web.service
    └─ uvicorn market_digest.web.app:app --host 127.0.0.1 --port 8087

  Caddy :8086 → reverse_proxy localhost:8087
  Cloudflare Tunnel → Caddy (Cloudflare Access 가 이메일 인증 게이트)

  NAS layout:
  /mnt/nas/market-digest/
    {YYYY}/{MM}/{DATE}.json          (기존 유지)
    blurbs.json                       (기존 유지)
    research/{TICKER}-{DATE}.md       (기존 유지)
    site/                             (삭제 — 더 이상 생성 안 함)
```

## 요청 흐름

### 일반 페이지 (GET)

요청 시 FastAPI 가 JSON 을 읽어 템플릿 렌더:

- `GET /` → 최신 날짜로 302 → `/{latest_date}`
- `GET /{date}` → 카드 페이지 (예: `/2026-04-17`)
- `GET /{date}/{item_id}` → 상세 페이지 (예: `/2026-04-17/kr-company-0`)
- `GET /{date}/{item_id}/research` → 리서치 페이지 (해당 md 없으면 404)
- `GET /search` → 검색 페이지 (클라 JS 가 `/cards.json` fetch)
- `GET /cards.json` → JSON 인덱스 (매 요청마다 모든 날짜 JSON 훑어 생성 — 캐시는 후속)
- `GET /assets/{name}` → `style.css`, `search.js` 정적 파일

### 딥 리서치 API

- `POST /api/research`
  - 요청 body: `{"ticker": "AAPL", "date": "2026-04-17"}`
  - 같은 (ticker, date) 에 진행 중 job 있으면 그 `job_id` 반환 (409 는 과함)
  - 이미 완료된 md 파일이 존재하면 `{"status": "done", "output_url": "/2026-04-17/{id}/research"}` 바로 반환
  - 새 job 시작: 백그라운드 태스크 spawn → 즉시 `{"job_id": "...", "status": "pending"}`

- `GET /api/research/status/{job_id}`
  - `{"status": "pending|running|done|failed", "ticker": "...", "date": "...", "output_url": "..."?, "error": "..."?}`

- `GET /api/research/active`
  - 현재 진행 중인 모든 job 리스트 (헤더 배지 용도)
  - `[{"job_id": "...", "ticker": "...", "date": "..."}, ...]`

## 컴포넌트

### `market_digest/web/app.py` (신규 — `builder.py` 대체)

FastAPI 애플리케이션. 모듈 수준 `app = FastAPI(...)` + `_env`, `_nas_dir`.

주요 함수:

- `startup()`: `_nas_dir` 을 `config.yaml` 의 `nas_report_dir` 로 세팅. 템플릿 env 생성.
- 라우트 핸들러 (위 URL 목록)

내부 헬퍼 (기존 `builder.py` 에서 이전):

- `_load_digest(date: str) -> Digest | None`
- `_list_dates() -> list[str]` (NAS glob, 정렬)
- `_prev_next(dates, date) -> tuple[str | None, str | None]`
- `_flat_ids(digest) -> list[str]`
- `_research_md_path(ticker, date) -> Path`
- `render_card_page(digest, ...)`, `render_detail_page(...)`, `render_research_page(...)`, `render_search_page()` — 기존 로직 그대로, 반환값만 FastAPI `HTMLResponse`

### `market_digest/web/jobs.py` (신규)

In-memory job tracker.

```python
@dataclass
class Job:
    job_id: str
    ticker: str
    date: str
    status: Literal["pending", "running", "done", "failed"]
    output_url: str | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class JobTracker:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def find_active(self, ticker: str, date: str) -> Job | None: ...
    def create(self, ticker: str, date: str) -> Job: ...
    def mark_running(self, job_id: str) -> None: ...
    def mark_done(self, job_id: str, output_url: str) -> None: ...
    def mark_failed(self, job_id: str, error: str) -> None: ...
    def get(self, job_id: str) -> Job | None: ...
    def active(self) -> list[Job]: ...
```

단일 인스턴스 — `app.state.jobs`.

### `market_digest/research.py` 리팩터

기존 `run_research()` 를 두 함수로 쪼갠다:

```python
def run_research(*, ticker, date_str, out_path, claude_cli, model, context, dry_run, timeout_sec=600) -> None:
    """기존 CLI 호출. 변경 없음."""

def build_prompt(ticker: str, date_str: str, out_path: Path, context: str | None) -> str:
    """프롬프트 생성 — 신규로 분리. KR 티커면 한국 소스 지시."""
    if re.match(r"^\d{6}$", ticker):
        return _kr_prompt(...)
    return _us_prompt(...)
```

### KR vs US 프롬프트

**US 프롬프트** (기존):
```
{ticker} 종목에 대한 딥 리서치 리포트를 한국어로 작성하라. ...
공개 자료만 사용: Yahoo Finance /analyst, Seeking Alpha 무료 요약,
Motley Fool, Bloomberg 무료 기사, 실적 transcript. ...
```

**KR 프롬프트** (신규):
```
{ticker} 한국 종목에 대한 딥 리서치 리포트를 한국어로 작성하라. 날짜 기준은 {date_str} (KST).
공개 자료만 사용: 네이버 금융 종목분석, 한경 컨센서스, DART 전자공시, 다음 금융,
이데일리·머니투데이·아시아경제 기사, 증권사 분석 요약.
다음 섹션으로 구성: ## 회사 개요, ## 주요 증권사 의견 (증권사명+목표가+요지+출처),
## Thesis, ## 리스크, ## 최근 이벤트, ## 출처.
WebSearch/WebFetch 로 수집하고, 출처 URL 을 각 인용마다 붙여라. ...
완성된 Markdown 을 Write 도구로 {out_path} 에 저장하라.
```

### 백그라운드 태스크 실행

FastAPI `BackgroundTasks` 는 요청-응답 주기에 묶이므로 긴 작업에 부적합. 대신 `asyncio.create_task()` + 동기 함수를 `run_in_executor()` 로 띄운다:

```python
async def _run_job(tracker: JobTracker, job_id: str, ticker: str, date_str: str):
    tracker.mark_running(job_id)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: run_research(
            ticker=ticker, date_str=date_str, out_path=...,
            claude_cli=..., model=..., context=None, dry_run=False,
        ))
        tracker.mark_done(job_id, output_url=f"/{date_str}/{item_id}/research")
    except Exception as exc:
        tracker.mark_failed(job_id, str(exc))
```

단, `run_research` 가 `raise` 하는 시점 전에 파일이 생성되지 않은 케이스 체크. claude 실패 로그는 `logs/` 에 남김.

### 상세 페이지 UI

detail_page.html.j2 수정:

```html
{% if has_research %}
  <p class="source"><a class="research-link" href="{{ item.id }}/research">🔍 딥 리서치 보기</a></p>
{% else %}
  <p class="source">
    <button id="research-btn" data-ticker="{{ item.ticker }}" data-date="{{ digest.date }}">🔍 딥 리서치 시작</button>
    <span id="research-status" class="subtitle"></span>
  </p>
{% endif %}
```

`research.js` (신규):

```javascript
// POST /api/research → 폴링 → 완료 시 location.href 이동
// 페이지 진입 시 /api/research/active 확인해서 이 (ticker, date) 가 진행 중이면 바로 폴링 모드로
```

헤더 전역 배지는 `base.html.j2` 에 추가:

```html
<span id="global-research-badge" class="nav-badge"></span>
```

`base.js` (신규): 주기적으로 `/api/research/active` fetch → 배지 개수 갱신.

## `run.py` 변경

- `from market_digest.web import build as web_build` 제거
- `web_build(nas_dir)` 호출 블록 삭제
- 로그 메시지도 정리

파이프라인 결과: JSON 이 NAS 에 쓰이면 즉시 웹에 반영됨 (앱이 요청 시 읽음).

## 삭제

- `market_digest/web/builder.py` — 그 안의 함수들은 `app.py` 로 이관
- `tests/web/test_build.py` — 정적 산출물 검증이라 무의미, 삭제
- `tests/web/test_collect.py`, `tests/web/test_index.py`, `tests/web/test_render.py` 중 일부 — 라우트 테스트로 재작성
- `site/` 디렉토리 (NAS) — 수동 삭제 (`rm -rf`)

## 설정·배포 변경

### `pyproject.toml`

추가 deps:
- `fastapi>=0.115`
- `uvicorn>=0.30`
- `httpx>=0.27` (FastAPI TestClient 의존)

### `config.yaml`

```yaml
web:
  host: "127.0.0.1"
  port: 8087

# (nas_report_dir 은 그대로)
```

### Caddy

`:8086` 블록을 다음과 같이 교체:

```
:8086 {
  encode gzip
  reverse_proxy localhost:8087
}
```

### systemd (신규)

`deploy/market-digest-web.service.example` 추가:

```
[Unit]
Description=market-digest web app
After=network.target

[Service]
Type=simple
User=sund4y
WorkingDirectory=/home/sund4y/market-digest
ExecStart=/home/sund4y/.local/bin/uv run uvicorn market_digest.web.app:app --host 127.0.0.1 --port 8087
Restart=on-failure
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/home/sund4y/market-digest/.env

[Install]
WantedBy=multi-user.target
```

## 에러 처리

| 상황 | 처리 |
|---|---|
| `GET /{date}` JSON 없음 | 404 + 템플릿 ("수집된 리포트 없음") |
| `GET /{date}/{item_id}` 아이템 ID 없음 | 404 |
| `GET /{date}/{item_id}/research` md 없음 | 404 |
| `POST /api/research` ticker 이미 상세에 없는 경우 | 400 |
| `POST /api/research` 이미 done | 즉시 output_url 반환 (재실행 안 함) |
| claude 실행 실패 | job status = "failed" + error; UI 는 "실패. 재시도?" |
| 서버 재시작 | in-memory job 전부 소실. UI 는 재요청 안내 |
| NAS 경로 없음 | `/cards.json` 은 `[]` 반환, `/` 는 placeholder |

## 테스트

`tests/web/test_app.py` (신규):

- 홈 → 최신 날짜로 redirect
- 카드 페이지 렌더 (prev/next, 빈 날)
- 상세 페이지 렌더
- 상세 페이지에서 research 링크 조건부 표시
- 검색 페이지 렌더
- `/cards.json` 인덱스 형태
- `POST /api/research` 신규 job 생성
- `POST /api/research` 이미 존재하는 md 있으면 바로 done
- `POST /api/research` 같은 ticker+date 중복 요청 → 기존 job_id 반환
- `GET /api/research/status/{id}` 흐름 (pending→running→done, 또는 failed)
- `GET /api/research/active`

`tests/test_jobs.py` (신규): JobTracker 단위 테스트 5~6개

`tests/test_research_cli.py` (수정): KR 티커 프롬프트 분기 테스트 추가

## 단일 구현 플랜으로 가능한 크기인가

규모가 크다 (라우트 ~7개 + 1차 테스트 ~15개 + 템플릿 수정 + deploy notes). 하나의 단일 플랜으로 처리 가능하되 task 가 15~18개 정도 나올 것. 이전 두 플랜과 비슷한 범위.
