# 마켓 다이제스트 웹 버전 설계

Date: 2026-04-19
Status: Draft (awaiting user review)

## 배경

현재 market-digest 는 매일 장마감 후 리포트를 요약하여
(1) `{YYYY}/{MM}/{DATE}.md` 를 NAS 에 저장하고
(2) Telegram 으로 카드 리스트를 전송한다.

두 채널이 분리되어 있어 한 날의 1줄 요약과 상세를 함께 탐색하거나,
과거 기록을 되짚기가 불편하다.

## 목표

Telegram 을 **모바일 웹페이지로 완전히 대체**한다.

- 한 페이지에서 1줄 카드와 상세를 함께 본다
- 과거 날짜를 이전/다음으로 이동하며 훑는다
- 종목·티커·하우스 텍스트 검색
- 모바일 우선 디자인 (단일 사용자, 개인용)
- 외부 노출은 기존 `sund4y-tunnel` (Cloudflare Tunnel) 경유

## 범위 밖 (Out of scope)

- body_md 풀텍스트 검색
- 검색 스니펫 / 하이라이트
- 북마크·태그·메모 등 쓰기 기능
- 다중 사용자 / 앱 레벨 인증 (필요하면 Tunnel 층 Cloudflare Access)
- region/category 체크박스 필터
- RSS / 이메일 알림

## 아키텍처

```
run.py ─┬─ fetchers (변경 없음)
        ├─ claude -p
        │     └─ Writes {YYYY}/{MM}/{DATE}.json   (신규·유일 출력)
        └─ web.build(nas_dir)                     (신규 단계)
              └─ /mnt/nas/market-digest/site/
                   ├─ index.html         (최신 날짜 내용 복사)
                   ├─ 2026-04-19.html    (카드 리스트)
                   ├─ 2026-04-19/
                   │    ├─ kr-company-0.html   (개별 상세)
                   │    └─ ...
                   ├─ search.html
                   ├─ cards.json         (검색 인덱스)
                   └─ assets/{style.css, search.js}

Caddy :PORT ── root * /mnt/nas/market-digest/site
Cloudflare Tunnel (sund4y-tunnel) ── ingress host → Caddy
```

원칙:

- **JSON = 단일 소스** (MD 파일 없음)
- **web.build 는 멱등** — 언제 돌려도 현재 NAS 상태로 전체 재생성
- **상시 프로세스는 Caddy 하나** — 정적 파일만 서빙

## 데이터 모델

### `{YYYY}/{MM}/{DATE}.json` (Claude 출력)

```json
{
  "date": "2026-04-19",
  "groups": [
    {
      "region": "kr",
      "category": "company",
      "title": "국내 기업리포트",
      "items": [
        {
          "id": "kr-company-0",
          "house": "미래에셋",
          "ticker": "005930",
          "name": "삼성전자",
          "headline": "HBM 업황 회복, 목표가 상향",
          "opinion": "Buy",
          "target": "85,000 → 95,000",
          "body_md": "- 목표가 85k→95k\n- 2Q 부터 실적 개선\n- ...",
          "url": "https://..."
        }
      ]
    }
  ]
}
```

- `region`: `"kr" | "us"`
- `category`: `"company" | "industry" | "8k" | "rating"`
- 필수: `date`, `groups[].region`, `groups[].category`, `groups[].title`,
  `items[].id`, `items[].headline`, `items[].body_md`
- 선택: `house`, `ticker`, `name`, `opinion`, `target`, `url`
- 빈 날: `{"date": "...", "groups": []}`
- `id` 규칙: `{region}-{category}-{index}` (그룹 안 0 부터, 영문·숫자만)

### `site/cards.json` (검색 인덱스)

```json
[
  {
    "date": "2026-04-19",
    "id": "kr-company-0",
    "region": "kr",
    "category": "company",
    "house": "미래에셋",
    "ticker": "005930",
    "name": "삼성전자",
    "headline": "HBM 업황 회복, 목표가 상향",
    "opinion": "Buy",
    "target": "85,000 → 95,000"
  }
]
```

- 날짜 내림차순
- `body_md` 제외 (검색 범위 외)
- 전 날짜를 flatten 하여 하나의 배열

## 사이트 구조

### 카드 페이지 `site/{DATE}.html`

sticky 헤더:
- ◀ (이전 JSON 존재 시 링크, 없으면 disabled)
- `{DATE} ({요일})`
- ▶
- 🔍 (→ `/search.html`)

본문:
- `groups` 순서대로 h2 그룹 타이틀 + 카드 리스트
- 카드 1줄 형태: `[house] name — headline · opinion target`
- 카드는 `<a href="{DATE}/{id}.html">` 로 상세 페이지 링크

빈 날: `groups: []` → "오늘 수집된 리포트 없음" 단문

### 상세 페이지 `site/{DATE}/{id}.html`

sticky 헤더:
- ← `{DATE}` (카드 페이지로)
- ◀▶ (같은 날짜 내 이전·다음 카드)

본문:
- h1: `name (ticker)` + `[house]` 태그
- 메타 줄: opinion / target
- body_md 렌더 (markdown-it-py)
- 원문 링크

### `index.html`

최신 날짜 카드 페이지 내용을 **그대로 복사**. 심볼릭 링크는 피함
(Caddy + NAS + Cloudflare 조합에서 가장 단순).

### `search.html`

- 입력 필드만 (체크박스 필터 없음)
- 입력 변화시 `cards.json` 에서 `name + ticker + house + headline`
  서브스트링 필터 (대소문자 무시)
- 결과 카드 탭 → `{date}/{id}.html`

### 디자인

- 모바일 우선, max-width 640px 센터
- 시스템 폰트 (Apple SF / Samsung One / Roboto) — 외부 폰트 호출 없음
- vanilla CSS 단일 파일, vanilla JS 단일 파일 (`search.js`)
- `prefers-color-scheme: dark` 대응
- 프레임워크 없음
- markdown-it-py 로 `body_md` → HTML

## 파이프라인 변경

### `CLAUDE.md` 재작성

- 출력은 `{nas_report_dir}/{YYYY}/{MM}/{DATE}.json` 단일 파일 (`Write`)
- 본 설계 문서의 JSON 스키마 인용
- 텔레그램 / stdout 카드 규칙 삭제
- 필터·편집 원칙 유지 (중복 제거, 노이즈 제거, 우선순위)
- 실패 처리: 빈 날은 `groups: []`
- 서두·메타 출력 금지 규칙 유지

### `market_digest/summarize.py`

- 반환 타입에서 `telegram_markdown` 제거
- `detail_path` → `json_path` 로 이름 변경
- 프롬프트와 예상 산출물 경로를 `.json` 으로

### `market_digest/run.py`

- 텔레그램 전송 단계 제거 (send/TelegramConfig 관련 코드)
- summarize 결과 JSON 검증 (pydantic) → 실패 시
  `logs/{DATE}-invalid.json` 덤프 + 에러 로그
- `web.build(nas_dir)` 호출 (산출 경로를 로그)
- `--dry-run`: JSON 은 `./out/` 에, site 는 `./out/site/` 에 빌드

### `market_digest/web.py` (신규)

- `build(nas_dir: Path) -> Path`
  - `{YYYY}/{MM}/{DATE}.json` glob 수집
  - pydantic 으로 파싱, 실패 스킵 + 로그
  - 날짜 정렬 → prev/next 계산
  - Jinja2 로 카드/상세/검색 템플릿 렌더
  - markdown-it-py 로 body_md 변환
  - `nas_dir/site.tmp/` 에 빌드 → 완료 후 `site/` 로 원자적 swap
- 템플릿: `market_digest/web/templates/`
- 자산: `market_digest/web/assets/` → 빌드 시 그대로 복사

### 제거되는 파일

- `market_digest/telegram.py`
- `.env.example` / `.env` 에서 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 제거 안내
- `tests/test_telegram.py` (있다면)

### 과거 `.md` 파일

- 덮어쓰지 않음 — NAS 에 그대로 둠
- 빌드는 JSON 만 읽음. MD 가 섞여 있어도 무시

## 배포

### Caddy

```Caddyfile
:PORT {
  root * /mnt/nas/market-digest/site
  encode gzip
  file_server
}
```

- `apt install caddy`
- `/etc/caddy/Caddyfile` 에 위 블록 추가
- `systemctl enable --now caddy`
- `PORT` 는 현재 사용 중이지 않은 값 (예: 8088) — 설치 시 확정

### Cloudflare Tunnel

- 기존 `sund4y-tunnel` 에 새 ingress 를 **Cloudflare 대시보드**에서 추가
- 예: `market-digest.<domain>` → `http://localhost:8088`
- 로컬 config 파일은 사용하지 않음 (원격 관리)

## 에러 처리

| 단계      | 실패 유형           | 처리 |
|-----------|---------------------|------|
| Claude    | JSON 파싱 실패      | `logs/{DATE}-invalid.json` 덤프, summarize 실패 반환 |
| Claude    | 빈 인박스           | `{"groups": []}` 저장 |
| web.build | 개별 JSON 파싱 실패 | 해당 날짜 스킵, 로그, 인덱스·site 에서 제외 |
| web.build | 전체 예외           | run.py 에서 catch, 로그, 다음 실행 때 재빌드 |
| web.build | swap 실패           | 이전 `site/` 유지 |

## 테스트

`tests/web/`:

1. JSON 스키마 — pydantic 정상 / 필수 필드 누락 / 잘못된 타입 케이스
2. `build()` 산출물 존재 — 2~3일 fixture → 기대 파일 경로 모두 생성
3. 카드 페이지 링크 — 카드 `<a>` 가 올바른 상세 경로를 가리키는지
4. prev/next — 3일 fixture 중간 날짜 ◀▶, 첫날·끝날 비활성
5. 빈 날 — "오늘 수집된 리포트 없음" 텍스트 렌더
6. cards.json 인덱스 — 전 날짜 flatten, 필수 필드, 날짜 내림차순
