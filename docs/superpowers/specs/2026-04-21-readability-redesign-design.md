# 가독성 개선 전면 재디자인 설계

Date: 2026-04-21
Status: Draft (awaiting user review)

## 배경

현재 웹 사이트의 카드·상세 페이지가 한 줄에 모든 정보 (하우스·이름·티커·headline·rating·target·blurb) 를 구겨 넣어 스캔·판독성이 낮다. 이모지(국기·픽토그램)가 톤을 가볍게 만들어 금융 정보 특유의 신뢰감이 떨어진다. 전면 재디자인으로 개선한다.

## 목표

- 정보 위계 선명화: 하우스·이름·헤드라인·메타가 시선 흐름에 맞게 분리
- 방향성 즉시 파악: 좌측 accent bar 색 (녹/빨/회) 이 rating·target 방향을 요약
- 신문/금융 단말 스타일 톤: serif 회사명 + monospace 메타
- 이모지 제거 — 텍스트 뱃지·구분자로 대체

## 범위 밖

- 데이터 모델 변경 (`Item`/`Group` 스키마 그대로)
- 라우팅·API 엔드포인트 변경
- 새로운 기능 추가 (차트·검색·research 모두 현 동작 유지)
- 다크모드 재디자인 (기존 `prefers-color-scheme: dark` 대응은 유지하되 세부 토큰은 후속)

## 디자인 토큰

### 색상

```css
--bg-page: #fafafa
--bg-card: #ffffff
--bg-badge: #eeeeee
--border: #e5e5e5
--border-dashed: #e5e5e5
--fg-primary: #222
--fg-muted: #888
--fg-subtle: #999
--fg-eyebrow: #333
--accent-up: #1a7f1a        /* 녹 = 상승 */
--accent-down: #c22233       /* 빨 = 하락 */
--accent-neutral: #aaaaaa    /* 회 = 중립/불명 */
--link: #0066cc
```

다크모드 대응은 기존 `prefers-color-scheme: dark` 블록에서 --bg-page/card/border 등 재정의. 현 다크 팔레트 유지.

### 타이포그래피

- **본문**: system sans (`-apple-system, "Apple SD Gothic Neo", "Malgun Gothic", Roboto, sans-serif`) — 유지
- **회사명 (h1·카드)**: `'Noto Serif KR', Charter, Georgia, serif` 500/700. Google Fonts 에서 1회 로드 (`display=swap`).
  - 이전 "외부 폰트 호출 금지" 원칙에서 벗어남 — 디자인상 필요 판정
- **eyebrow·meta·티커**: `"SF Mono", Menlo, Consolas, monospace`

### 크기 체계 (모바일 기준, 데스크탑 동일 — max-width 640px)

| 용도 | 크기 | 굵기 | 패밀리 |
|---|---|---|---|
| Card 회사명 | 17px | 700 | Serif |
| Detail h1 | 26px | 700 | Serif |
| Headline (본문 한 줄) | 13~14px | 400 | Sans |
| Eyebrow | 10px (letter-spacing 1px, uppercase) | 400→b600 | Mono |
| Meta strip | 12px | 600 | Mono |
| Blurb | 11~13px italic | 400 | Sans italic |
| Body prose | 14px / line-height 1.65 | 400 | Sans |

## 카드 레이아웃 (최종)

```
┌─┬────────────────────────────────────┐
│ │ KR  메리츠증권 · 005930            │   ← eyebrow
│▮│ 삼성전자  005930                   │   ← serif name + mono ticker
│ │ HBM 업황 회복, 목표가 상향          │   ← headline
│ │ BUY · 85,000 → 95,000              │   ← monospace meta (color-up/down)
│ │ - - - - - - - - - - - - - - - - -  │   ← dashed separator
│ │ 한국 메모리반도체·스마트폰·가전       │   ← italic blurb
└─┴────────────────────────────────────┘
 ↑
 accent bar 4px (green/red/gray)
```

- `KR` / `US` 뱃지: 10px monospace, bg=`--bg-badge`, padding 1-4px, border-radius 2px
- 카드 자체: bg=white, border 1px `--border`, radius 8px, margin-bottom 8px
- `<ul class="cards">` 는 list-style none, padding 0

## 상세 페이지 레이아웃

```
┌──────────────────────────────────────┐
│ ← 2026-04-20   ◀ ▶        검색       │   ← sticky header
├──────────────────────────────────────┤
│ ┃ KR  메리츠증권 · 005930             │
│ ┃                                    │
│ ┃ 삼성전자  005930                    │   ← serif h1 + mono ticker
│ ┃ 한국 메모리반도체·스마트폰·가전       │   ← italic blurb
│ ┃ RATING BUY · TARGET 85,000→95,000  │   ← monospace meta strip
│ ┃ ─────────────────────────────      │   ← bottom-border divider
│ ┃ [body_md rendered prose]           │
│ ┃   • HBM 수요 강세…                  │
│ ┃   • 경쟁사 대비 경쟁력 회복…        │
│ ┃ ─────────────────────────────      │
│ ┃ [ 원문 링크 → ]                     │
│ ┃ [ 네이버 금융에서 차트 보기 ]        │   ← KR 은 링크, US 는 TV 위젯
│ ┃ [ 딥 리서치 시작 ] or 결과 링크     │
└──────────────────────────────────────┘
```

- 좌측 accent bar 는 article 전체 높이 (flex column) 로 확장
- 제목 주변 여백은 카드보다 큼 (8~12px)
- 액션 블록: 원문 → 차트 → 리서치 순, 전부 동일 중립 스타일 (white bg, border)

## 방향 추론 (accent bar 색)

Item 의 accent 방향을 결정하는 순서:

1. `target` 에 arrow (`→` 혹은 `->`) 가 있으면 파싱: 좌우 숫자 비교
   - `"85,000 → 95,000"` → new > old → **up**
   - `"$230 → $190"` → new < old → **down**
   - 값 추출: `re.findall(r"[\d,.]+", side)` 마지막 매치
2. arrow 없으면 `opinion` 텍스트 매핑:
   - Up: `Buy`, `Outperform`, `Overweight`, `Strong Buy`, `Accumulate`, `Market Outperform`
   - Down: `Sell`, `Underperform`, `Underweight`, `Strong Sell`, `Reduce`
   - 그 외 (`Hold`, `Neutral`, `Market Perform`, 빈 값): **neutral**
3. action 정보가 있으면 `upgrade` → up, `downgrade` → down, `initiate`/`maintain` → neutral. 현재 Claude JSON 에는 action 이 item 레벨에 없으므로 (1)(2) 로 충분.
4. 어떤 정보도 없으면 **neutral** (회색).

`category == "industry"` 혹은 ticker 없는 아이템은 accent 자체를 표시하지 않음 (gray 대신 accent bar 제거).

meta strip 및 카드 meta 의 텍스트 색도 같은 방향 규칙:
- up → `var(--accent-up)` 녹
- down → `var(--accent-down)` 빨
- neutral → `var(--fg-primary)` 기본 (검정)

## 지역 뱃지

- ticker 형태로 판정: `^\d{6}$` → `KR`, else → `US`
- 혹은 group.region 필드 사용 (더 정확)
- 카드/상세 공통: 10px mono 대문자, `--bg-badge` 배경, 텍스트 `--fg-eyebrow`

Category 라벨 (eyebrow 의 하우스명 앞) 은 표시하지 않음 — `KR`/`US` 로 충분.

## 그룹 h2 헤딩

카드 페이지의 섹션 헤딩 `<h2>` 도 이모지 제거:
- 기존: `🇰🇷 국내 기업리포트`
- 변경: `국내 기업리포트` (텍스트만). 11~12px monospace 대문자 label + 13~14px sans 라벨을 조합해도 무방.

스펙: 12px mono letter-spacing 1px uppercase color `--fg-muted`, margin `16px 0 8px`.

## 검색 페이지

입력 필드 + 결과 리스트. 결과 카드는 `search.js` 가 렌더하며, **카드 페이지와 동일한 마크업** 을 생성해야 함 (accent bar / eyebrow / name / headline / meta / blurb). 현재 `search.js` 의 결과 템플릿 리터럴을 대폭 재작성.

`cards.json` 에는 direction 힌트 (up/down/neutral) 이 없으므로 **클라이언트에서 동일한 추론 로직 (arrow 파싱 + opinion 사전) 을 JS 로 구현**. 혹은 서버가 `cards.json` 빌드 시 `direction` 필드 추가 — 후자가 단순.

`CardIndexEntry` 에 `direction: Literal["up","down","neutral"] | None = None` 필드 추가하고 `build_cards_index` 에서 계산해 넣기로 결정.

## 전역 리서치 뱃지

이모지 🔍 제거. 단순 `N` 숫자 (파란 원형 뱃지) 로 노출. 클릭 시 active 목록 나열 (간단한 alert 혹은 미니 리스트 — 후속).

현재 `base.js` 는 `🔍 N` 를 출력하므로 `N` 만으로 단축.

## 라벨 & 문구 (한국어 통일)

- 상단 sticky 의 search 링크: `검색`
- 상세 페이지 action 버튼 라벨:
  - `원문 링크 →`
  - `네이버 금융에서 차트 보기` (KR)
  - `딥 리서치 시작` / `딥 리서치 보기` (md 유무에 따라)
- 카드 비어있는 날: `오늘 수집된 리포트 없음` (유지)

## 영향받는 파일

### 생성
(없음 — 기존 파일만 수정)

### 수정
- `market_digest/web/templates/base.html.j2` — `<link>` 로 Noto Serif KR 추가, 뱃지 문구 `N`
- `market_digest/web/templates/card_page.html.j2` — 카드 마크업 전면 재작성
- `market_digest/web/templates/detail_page.html.j2` — article 마크업 전면 재작성, 액션 버튼 순서·스타일
- `market_digest/web/templates/search.html.j2` — 미미한 조정
- `market_digest/web/assets/style.css` — 전면 재작성
- `market_digest/web/assets/search.js` — 결과 카드 마크업 교체
- `market_digest/web/assets/base.js` — 뱃지 출력 `🔍 N` → `N`
- `market_digest/web/app.py` — `detail_page` 핸들러에 `region`, `direction` 계산 + template kwargs
- `market_digest/web/data.py` — `build_cards_index` 에 `direction` 포함
- `market_digest/models.py` — `CardIndexEntry` 에 `direction` 필드 추가
- `market_digest/web/direction.py` (신규) — `infer_direction(item) -> Literal["up","down","neutral"]` 순수 함수

### 신규
- `market_digest/web/direction.py` — 방향 추론 유틸
- `tests/web/test_direction.py` — 유닛 테스트

## 검증 기준

- 모든 기존 테스트 통과 + 신규 direction 테스트
- 카드 페이지/상세 페이지에 이모지 없음 (`assert` grep)
- `GET /cards.json` 응답의 각 entry 에 `direction` 키 존재 (up/down/neutral)
- 시각 확인: 브라우저에서 오늘 실제 데이터로 렌더, serif 적용, accent bar 색 올바름

## 구현 방식

한 PR (단일 브랜치, 단일 병합) 로. 템플릿·CSS 재작성은 상호 의존이 커서 쪼개기 어렵다. 테스트는 마크업 변경에 맞춰 동시 갱신.

## 리스크

- **Noto Serif KR 외부 요청**: Cloudflare Tunnel 뒤에서도 fonts.googleapis.com 은 공용 CDN, 차단 가능성 낮음. 차단 시 `font-display: swap` 이라 폴백이 즉시 적용됨.
- **CardIndexEntry 변경**: 스키마 확장이므로 기존 cards.json 파일은 재생성 필요 (`/cards.json` 은 요청마다 생성되니 자동 반영).
- **direction 추론 부정확**: arrow 없고 opinion 도 없는 아이템은 neutral 로 안전하게 표시. 실질적 블로커 없음.
