# 수율 경향성(Yield Trend) 워크플로우 구현 계획서

## 1. 워크플로우 개요

| 항목 | 내용 |
|------|------|
| 이름 | `yield_trend` |
| 목적 | 제품(lot_cd)의 공정별 수율 및 cat별 불량률 trend 확인 |
| 입력 | lot_cd(필수), week(선택 — 미지정 시 전주), oper(선택 — 미지정 시 전체 공정), from_date/end_date(선택 — week 내 날짜 필터용) |
| 데이터 | LOT별 cat별 in/out (수율은 계산), week 단위로 조회/캐싱 |
| 표시 | 공정별 수율 + 공정-cat 불량률 (전체 공정 합산은 안 함) |
| 특징 | week 단위 parquet 캐싱 → 자동전처리 → overview → 사용자 요청 루프 |

## 2. Week 기반 조회 + Parquet 캐싱

### 조회 단위

- 데이터는 **week 단위**로 조회한다.
- week 포맷: `YYYY-WNN` (예: `2025-W20`)
- 사용자가 기간을 언급하지 않으면 **전주(previous week)** 를 기본값으로 사용한다.

### Parquet 캐싱 전략

```
조회 요청 (lot_cd + week)
│
├─ parquet 파일 존재? → 파일 로드 (DB 조회 skip)
│   경로: {YIELD_PARQUET_DIR}/{lot_cd}/week_{YYYYWNN}.parquet
│
└─ 없음 → DB 조회 → parquet 저장 → 데이터 사용
```

- 저장 경로 패턴: `data/yield/{lot_cd}/week_2025W20.parquet`
- 경로는 `schema.YIELD_PARQUET_DIR`로 관리

### 날짜 필터링

- 사용자가 `from_date`, `end_date`를 지정한 경우:
  1. 해당 날짜가 속한 week(들)를 계산
  2. 각 week의 parquet를 로드 (없으면 DB 조회 + 저장)
  3. 로드한 데이터에서 `from_date ~ end_date` 범위로 필터링
- 여러 week에 걸치는 경우 각 week parquet를 개별 로드 후 concat

### 예시

| 사용자 입력 | week 결정 | 동작 |
|------------|----------|------|
| "LOT001 트렌드 확인해줘" | 전주 (2025-W19) | W19 parquet 확인 → 없으면 조회+저장 |
| "LOT001 20주차 트렌드" | 2025-W20 | W20 parquet 확인 → 없으면 조회+저장 |
| "LOT001 5월 1일~5월 10일" | W18, W19 (해당 날짜 포함 week) | 각 week parquet 로드 → 날짜 필터 |

## 3. FSM 상태 설계

```
IDLE
→ SELECTING_WORKFLOW          # yield_trend 선택
→ COLLECTING_PARAMS           # lot_cd, [week], [oper], [from_date], [end_date]
→ VALIDATING_PARAMS
→ YIELD_LOADING_DATA          # parquet 확인 → 없으면 DB 조회 + 저장
→ YIELD_PREPROCESSING         # 자동: 피벗, 수율/불량률 계산, 날짜 필터
→ YIELD_SHOWING_OVERVIEW      # 공정별 수율 + cat별 불량률 표시 (decision)
→ YIELD_AWAITING_REQUEST      # 사용자 요청 대기 (decision, 루프)
→ YIELD_SHOWING_DETAIL        # 요청 결과 표시
→ YIELD_AWAITING_REQUEST      # 루프백
→ COMPLETED
```

Decision states: `YIELD_SHOWING_OVERVIEW`, `YIELD_AWAITING_REQUEST`

주요 변경: `YIELD_QUERYING_DATA` → `YIELD_LOADING_DATA` (parquet 로드 or DB 조회를 통합)

## 4. 전이 규칙

```python
_YIELD_TREND_TRANSITIONS = {
    WorkflowState.COLLECTING_PARAMS: [
        WorkflowState.VALIDATING_PARAMS,
        WorkflowState.YIELD_LOADING_DATA,
    ],
    WorkflowState.VALIDATING_PARAMS: [
        WorkflowState.COLLECTING_PARAMS,
        WorkflowState.YIELD_LOADING_DATA,
    ],
    WorkflowState.YIELD_LOADING_DATA: [WorkflowState.YIELD_PREPROCESSING],
    WorkflowState.YIELD_PREPROCESSING: [WorkflowState.YIELD_SHOWING_OVERVIEW],
    WorkflowState.YIELD_SHOWING_OVERVIEW: [WorkflowState.YIELD_AWAITING_REQUEST],
    WorkflowState.YIELD_AWAITING_REQUEST: [
        WorkflowState.YIELD_SHOWING_DETAIL,
        WorkflowState.COMPLETED,
    ],
    WorkflowState.YIELD_SHOWING_DETAIL: [WorkflowState.YIELD_AWAITING_REQUEST],
}
```

## 5. schema.py 추가 항목

```python
# =============================================================================
# 수율 경향성 분석 설정
# =============================================================================

YIELD_REQUIRED_PARAMS = [
    {"key": "lot_cd", "label": "LOT 코드", "type": "text"},
]
YIELD_OPTIONAL_PARAMS = [
    {"key": "week", "label": "조회 주차 (예: 2025-W20)", "type": "text"},
    {"key": "oper", "label": "공정(OPER)", "type": "text"},
    {"key": "from_date", "label": "시작일 (week 내 필터)", "type": "date", "format": "YYYYMMDD"},
    {"key": "end_date", "label": "종료일 (week 내 필터)", "type": "date", "format": "YYYYMMDD"},
]

# DB 테이블
YIELD_TABLE = "schema_name.yield_table"  # TODO: 실제 테이블명

# 컬럼명
YIELD_LOT_COLUMN = "lot_cd"        # TODO: 실제 컬럼명
YIELD_OPER_COLUMN = "oper"         # TODO: 실제 컬럼명
YIELD_DATE_COLUMN = "test_date"    # TODO: 실제 컬럼명
YIELD_CAT_COLUMN = "cat"           # TODO: 실제 컬럼명
YIELD_IN_COLUMN = "in_count"       # TODO: 투입 수 컬럼명
YIELD_OUT_COLUMN = "out_count"     # TODO: 양품 수 컬럼명

# Parquet 캐싱
YIELD_PARQUET_DIR = "data/yield"   # TODO: 실제 저장 경로
# 파일명 패턴: {YIELD_PARQUET_DIR}/{lot_cd}/week_{YYYYWNN}.parquet
```

공정 미지정 시 전체 조회 대상은 `schema.OPER_OPTIONS` 참조.

## 6. pipeline/yield_trend.py 설계

| 함수 | 역할 | 입력 | 출력 |
|------|------|------|------|
| `resolve_weeks(params)` | week 결정: 명시 week 사용 or 날짜→week 변환 or 기본 전주 | params | `list[str]` (week 목록) |
| `get_parquet_path(lot_cd, week)` | parquet 파일 경로 생성 | lot_cd, week | `Path` |
| `load_or_query(params, weeks)` | parquet 있으면 로드, 없으면 DB 조회 + parquet 저장 | params, weeks | `DataFrame` |
| `query_yield_data(params, week)` | 단일 week DB 조회 (mock) | params, week | `DataFrame` |
| `save_parquet(df, lot_cd, week)` | DataFrame을 parquet으로 저장 | df, lot_cd, week | `Path` |
| `filter_by_date(df, from_date, end_date)` | 날짜 범위 필터링 (선택) | df, dates | `DataFrame` |
| `preprocess_yield(df)` | 수율/불량률 계산 + 집계 | raw DataFrame | `{"oper_summary": df, "cat_detail": df}` |
| `build_overview_message(summary)` | 공정별 수율 + cat불량률 메시지 | preprocess 결과 | `str` |
| `parse_detail_request(text)` | 사용자 요청 파싱 | user input | `{"show_all": bool, "oper": str?, "cat": str?}` |
| `build_detail_view(cat_detail_df, request)` | 필터링 + trend 표 생성 | detail df + request | `str` |
| `plot_oper_yield_trend(df, oper)` | 공정 수율 시계열 차트 | oper_summary df | `bytes(PNG)` |
| `plot_cat_defect_trend(df, oper, cat)` | 공정-cat 불량률 차트 | cat_detail df | `bytes(PNG)` |

## 7. Mock 데이터 구조

### Raw (query_yield_data 반환, week 단위)

```
lot_cd  | oper | test_date | cat  | in_count | out_count
--------|------|-----------|------|----------|----------
LOT_001 | OP1  | 20250505  | cat1 | 1000     | 980
LOT_001 | OP1  | 20250505  | cat2 | 1000     | 995
LOT_001 | OP2  | 20250505  | cat1 | 1000     | 970
LOT_001 | OP1  | 20250506  | cat1 | 1000     | 985
...     (해당 week의 월~일 데이터)
```

### Parquet 저장 형태

```
data/yield/
└── LOT_001/
    ├── week_2025W19.parquet
    ├── week_2025W20.parquet
    └── ...
```

### preprocess 후 — oper_summary

```
oper | test_date | total_in | total_out | yield_rate
-----|-----------|----------|-----------|----------
OP1  | 20250505  | 1000     | 975       | 97.5%
OP2  | 20250505  | 1000     | 970       | 97.0%
...
```

### preprocess 후 — cat_detail

```
oper | test_date | cat  | in_count | fail_count | defect_rate
-----|-----------|------|----------|------------|------------
OP1  | 20250505  | cat1 | 1000     | 20         | 2.0%
OP1  | 20250505  | cat2 | 1000     | 5          | 0.5%
OP2  | 20250505  | cat1 | 1000     | 30         | 3.0%
...
```

## 8. app.py 핸들러 흐름

```
YIELD_LOADING_DATA:
  1. resolve_weeks(params) → 대상 week 목록 결정
  2. load_or_query(params, weeks):
     - 각 week별 parquet 존재 확인
     - 있으면 로드, 없으면 DB 조회 + parquet 저장
     - 여러 week이면 concat
  3. session에 raw DataFrame 저장
  → auto → YIELD_PREPROCESSING

YIELD_PREPROCESSING:
  1. from_date/end_date 있으면 → filter_by_date(df)
  2. oper 없으면 schema.OPER_OPTIONS 전체로 확장
  3. preprocess_yield(df) → oper_summary, cat_detail 저장
  → auto → YIELD_SHOWING_OVERVIEW

YIELD_SHOWING_OVERVIEW:
  공정별 수율 테이블 + cat별 불량률 테이블 표시
  "전체 수율 trend를 보시려면 '전체 보여줘',
   특정 공정/cat을 보시려면 '공정X catY 보여줘'라고 입력하세요."
  → decision wait

YIELD_AWAITING_REQUEST:
  parse_detail_request(user_input)
  - 종료 → COMPLETED
  - show_all=True → 모든 공정 수율 trend 표
  - oper+cat 지정 → 해당 필터 적용
  → YIELD_SHOWING_DETAIL

YIELD_SHOWING_DETAIL:
  build_detail_view + plot (해당되면)
  → auto → YIELD_AWAITING_REQUEST (루프)
```

## 9. 사용자 요청 파싱 예시

### 파라미터 수집 단계

| 입력 | 파싱 결과 |
|------|----------|
| "LOT001 트렌드 확인해줘" | `{lot_cd: "LOT001", week: 전주}` |
| "LOT001 20주차 트렌드" | `{lot_cd: "LOT001", week: "2025-W20"}` |
| "LOT001 5월 1일~5월 10일" | `{lot_cd: "LOT001", weeks: [W18,W19], from_date: "20250501", end_date: "20250510"}` |
| "LOT001 OP1 지난주" | `{lot_cd: "LOT001", week: 전주, oper: "OP1"}` |

### 탐색 루프 단계

| 입력 | 파싱 결과 |
|------|----------|
| "전체 보여줘" / "all" | `{"show_all": True}` |
| "OP1의 cat2 보여줘" | `{"oper": "OP1", "cat": "cat2"}` |
| "OP1 수율 보여줘" | `{"oper": "OP1", "cat": None}` |
| "cat1 보여줘" | `{"oper": None, "cat": "cat1"}` |
| "종료" / "끝" | → COMPLETED |

## 10. 구현 순서

| # | 파일 | 작업 |
|---|------|------|
| 1 | `schema.py` | yield 관련 placeholder + parquet 경로 추가 |
| 2 | `core/state_machine.py` | WorkflowType, 5개 state, 전이 규칙, decision states 추가 |
| 3 | `pipeline/yield_trend.py` | mock pipeline + parquet 캐싱 로직 구현 (신규) |
| 4 | `llm/prompts.py` | yield 파라미터 추출 프롬프트 추가 (week 파싱 포함) |
| 5 | `app.py` | yield 상태별 핸들러 연결 |
| 6 | docs/roo_tasks | 변경 이력 갱신 |

## 11. 보류 사항 (루코드 담당)

- `YIELD_TABLE` 실제 테이블명/컬럼명 교체
- `YIELD_PARQUET_DIR` 실제 저장 경로 교체
- 실제 SQL 쿼리 작성 (week 기반 조회)
- 수율 계산 비즈니스 로직 (in/out → yield 변환 규칙)
- DB SDK wrapper 연동
- parquet 저장 경로를 S3 또는 NFS로 변경 시 wrapper 수정
