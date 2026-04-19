# 애널리스트 데이터 확장 + 온디맨드 딥 리서치 설계

Date: 2026-04-20
Status: Draft (awaiting user review)

## 배경

현재 미국 쪽 데이터 품질이 빈약하다.

- `yfinance.upgrades_downgrades` 는 티커·하우스·before→after 등급만 반환하고 목표가·코멘트·원문 URL 이 없다.
- 결과적으로 Claude 가 상세본에 쓸 내용이 `"BNP Paribas 가 AAPL 을 Neutral→Outperform 으로 상향"` 한 줄뿐이다.
- `sec_edgar` 는 watchlist 10종목에만 한정돼 있고 메타데이터(URL)만 저장한다.
- watchlist 가 빅테크 위주라 발굴(discovery) 이 안 된다.

## 목표

1. **FMP Free** 로 yfinance 를 교체해 목표가 + 전체 시장 범위(개별 watchlist 초과) 커버.
2. **회사 1줄 소개** (`company_blurb`) 를 각 item 에 자동 첨부해 "이 회사가 뭐 하는 데지?" 를 카드에서 바로 파악.
3. **온디맨드 딥 리서치 CLI** 추가. 관심 티커에 대해 사용자 트리거로 claude -p + WebSearch/WebFetch 호출 → 공개 자료에서 thesis·코멘트·리스크 종합한 마크다운 생성. 웹사이트 상세 페이지에서 링크로 노출.

## 범위 밖

- 본문 fetch (SEC 8-K 첨부 다운로드) — 별도 후속
- SEC watchlist 확장 / 글로벌 피드 — 별도 후속
- Benzinga·Seeking Alpha 유료 API
- 리서치 결과 자동 예약 실행
- 한국 종목 blurb (당장은 name 으로 충분, 한국 데이터 소스 따로)

## 설계

### 1. FMP Free fetcher 교체

**신규**: `market_digest/fetchers/fmp.py`
**제거**: `market_digest/fetchers/yfinance_recs.py`

- 환경 변수 `FMP_API_KEY` 사용 (`.env` / `.env.example` 에 추가).
- **엔드포인트 1**: `/stable/grades-consensus-bulk` 또는 `/v3/upgrades-downgrades-rss-feed` (FMP 문서 확인 후 최종 선정) — 당일 전체 시장 rating 변경 피드.
  - 필터 (fetcher 내부): 시총 $1B+ AND (action == "initiate" OR 목표가 변동 10%+).
  - 시총은 같은 fetcher 에서 `/v3/profile/{ticker}` 호출로 확인 (캐시 사용).
- **엔드포인트 2**: `/v3/price-target/{ticker}` (후속 enrich 단계에서 필요 시 호출) — 개별 티커 최신 목표가 조회.
- inbox 저장 포맷: 기존 yf 파일과 동일 구조 (YAML front matter + 본문 텍스트).
- 한계: FMP Free 는 하루 250 calls. 신규 rating feed 1회 + watchlist 프로필 조회 10~30회 → 여유 있음.
- 실패·rate limit 시 로그 + 해당 날짜는 0건으로 진행 (기존 fetcher 와 동일 정책).

### 2. 회사 1줄 소개 (company_blurb)

**추가 단계**: `market_digest/enrich.py` (신규). `summarize()` 완료 후 `run.py` 가 호출.

```
run.py:
  fetch → summarize → validate → enrich → web.build
```

동작:

1. `{DATE}.json` 로드.
2. 모든 item 의 `(ticker, name)` 수집 → unique set.
3. 각 쌍에 대해 blurb cache 조회 (`/mnt/nas/market-digest/blurbs.json`).
4. cache miss 인 경우:
   - ticker 가 있으면 FMP `/v3/profile/{ticker}` 호출해 `description` 필드 획득.
   - description 과 name 을 claude CLI (Sonnet) 에 넘겨 **한국어 1줄 요약** 생성.
   - cache 에 `{ticker}: {"blurb": "...", "fetched_at": "2026-04-20", "source": "fmp+sonnet"}` 저장.
5. cache hit + `fetched_at` 90일 이내면 기존 blurb 사용.
6. ticker 가 없는 item (한국 "주제" 아이템 등) 은 blurb 없음.
7. 각 item 에 `company_blurb` 필드 주입 → JSON 재저장.

`Item` 스키마:

```python
class Item(BaseModel):
    ...
    company_blurb: str | None = None
```

Claude Sonnet 호출:

- CLI: `claude -p` with `--model claude-sonnet-4-6`, `--allowed-tools ""` (빈 문자열, 도구 차단).
- 프롬프트: `"{ticker} ({name}) 의 사업을 한국어 한 줄로 요약해라. 회사 설명: {description}"`.
- 출력 stdout 한 줄 → 앞뒤 공백 정리 후 cache 저장.

비용 예상: 30 unique ticker × Sonnet 1줄 ≈ 월 $1 미만.

### 3. 딥 리서치 CLI

**신규**: `market_digest/research.py` 실행 진입점.

```
uv run python -m market_digest.research AAPL [--context "포커스..."] [--date 2026-04-20]
```

동작:

1. ticker 인수 받음.
2. 날짜는 `--date` 혹은 오늘 (KST).
3. 출력 경로: `/mnt/nas/market-digest/research/{ticker}-{YYYY-MM-DD}.md`.
4. claude CLI 호출:
   - `--allowed-tools "WebSearch,WebFetch,Read,Write"`
   - `--model claude-opus-4-7` (리서치라 고성능)
   - 프롬프트: `{ticker}` 에 대한 최근 애널리스트 의견·주요 thesis·리스크를 공개 자료 (Seeking Alpha 무료 요약, Yahoo Finance /analyst, Motley Fool, Bloomberg 무료 기사, 실적 transcript 등) 에서 수집. 지정 경로에 Write.
5. 출력 파일 구조:

```markdown
# {TICKER} 딥 리서치 — YYYY-MM-DD

## 회사 개요
...

## 주요 애널리스트 의견
- [하우스] 요약 + 출처 링크

## Thesis
...

## 리스크
...

## 최근 이벤트
...

## 출처
- URL 1
- URL 2
```

`--context` 인수로 사용자가 집중할 주제 지시 가능 (예: "AI 경쟁 리스크 중점").

비용: 1회 $0.2~0.5 (Opus + 웹서치), 사용자 트리거라 예측 가능.

### 4. UI 변경

**카드 페이지**: `card_page.html.j2` — item 의 `company_blurb` 가 있으면 headline 다음 줄에 회색 작은 글자로 표기.

```
[미래에셋] 삼성전자 (005930) — HBM 업황 회복 · Buy 85→95k
한국 메모리반도체·스마트폰·가전 제조사          ← 추가
```

**상세 페이지**: `detail_page.html.j2`
- `company_blurb` 가 있으면 meta 줄 위에 표기
- `/mnt/nas/market-digest/research/{ticker}-{digest.date}.md` 파일이 존재하면 "🔍 딥 리서치" 링크 노출 (해당 md 를 HTML 로 변환해 별도 페이지로 렌더하거나, 원본 md 로 링크)

**build 변경**: `web.build` 가 `research/` 디렉토리 훑어 관련 md 파일 있는 item 에 대해 `site/{date}/{id}.research.html` 생성. 템플릿은 detail 과 유사한 껍질 + 본문 markdown 렌더.

## 데이터 모델 변경

### `Item` 추가 필드

```python
class Item(BaseModel):
    ...
    company_blurb: str | None = None
```

### 신규: blurb 캐시

`/mnt/nas/market-digest/blurbs.json`:

```json
{
  "AAPL": {
    "blurb": "미국 스마트폰·PC·웨어러블 및 서비스 구독 생태계 제공",
    "fetched_at": "2026-04-20",
    "source": "fmp+sonnet"
  }
}
```

## 설정 변경

`config.yaml`:

```yaml
fmp:
  enabled: true
  min_market_cap_usd: 1_000_000_000
  target_change_threshold: 0.10  # 10%
  request_interval_sec: 1

claude:
  ...
  blurb_model: "claude-sonnet-4-6"
  research_model: "claude-opus-4-7"
  blurb_cache_ttl_days: 90

# yfinance 섹션 제거
```

`.env.example`:

```
FMP_API_KEY=
```

## 에러 처리

| 단계 | 실패 | 처리 |
|---|---|---|
| FMP fetcher | rate limit / 네트워크 | 로그 + 해당 날짜 건수 0 처리, 파이프라인 계속 |
| FMP fetcher | API key 없음 | fetcher 비활성 상태 로그, 파이프라인 계속 |
| enrich | FMP profile 실패 | blurb 생략 (None 유지), 다음 item 진행 |
| enrich | Sonnet 호출 실패 | blurb 생략, 로그 |
| enrich | cache 파일 손상 | 무시하고 재생성 |
| research | 웹서치 실패 | md 에 "자료 수집 실패" 섹션 포함, 부분 결과 저장 |
| research | 파일 경로 없음 | md 파일 없음 → UI 에 링크 노출 안 됨 (정상 동작) |

## 테스트

`tests/`:

1. **FMP fetcher**
   - mock HTTP 로 rating feed 응답 → 필터링 로직 (시총 / 목표가 변동 / initiate) 검증
   - inbox .txt 포맷 준수 (YAML front matter + 본문)
2. **enrich**
   - cache hit: API 호출 없음, 기존 blurb 주입
   - cache miss: mock FMP profile + mock subprocess(claude CLI) → blurb 생성 + cache 업데이트
   - ticker 없는 item: blurb None 유지
3. **research CLI**
   - `--dry-run` 플래그 지원 (실제 claude 호출 대신 dummy md 생성) → 인수 파싱·경로 산출 검증
4. **Item 스키마**
   - `company_blurb` 선택 필드로 정상 파싱/누락 OK
5. **UI**
   - 카드 페이지에 blurb 존재 시 렌더, 없으면 공백 없음
   - 상세 페이지에 research md 있으면 링크 렌더

## 파이프라인 변경 요약

```
기존:  fetch → claude summarize → validate → web.build
신규:  fetch (FMP 포함) → claude summarize → validate → enrich → web.build
온디맨드: research CLI 실행 → research/{ticker}-{date}.md → 다음 web.build 에서 링크 자동 노출
```

## 작업 묶음

이 spec 은 4개의 독립적인 부 프로젝트로 구성된다. 순서대로 구현 가능:

1. **SUB-1**: FMP fetcher 교체 (yfinance 제거, FMP 추가, 필터 로직, config + env)
2. **SUB-2**: Item 스키마 확장 + enrich 단계 + blurb 캐시 + CLAUDE.md 에 `company_blurb` 필드 명시
3. **SUB-3**: UI — 카드·상세 페이지에 blurb 노출
4. **SUB-4**: research CLI + UI 에 research 링크 렌더 + research md → HTML 변환 렌더
