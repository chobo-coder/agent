# Workflow Expansion Plan

## 목적

현재 완성된 `conventional` 워크플로우를 기준으로, 남은 `map_trend`와 `equip_trend` 워크플로우를 단계적으로 추가한다.

이 문서는 구현 전 대화용 플랜이다. 실제 구현 중 결정이 바뀌면 이 문서를 먼저 수정하고, 상태 머신/파이프라인 인터페이스/schema 변경 후에는 `docs/roo_tasks` 변경 이력을 함께 갱신한다.

## 현재 구조 요약

- 실제 Streamlit 앱 흐름은 `app.py`의 상태별 핸들러가 주도한다.
- `core/state_machine.py`에는 `WorkflowType.CONVENTIONAL`, `WorkflowType.MAP_TREND`, `WorkflowType.EQUIP_TREND`가 정의되어 있다.
- `conventional` 워크플로우는 다음 흐름까지 완료된 상태다.
  - 워크플로우 선택
  - 필수 조회 조건 수집
  - mock 조회 결과 표시
  - EDA 선택
  - S3 추가 로딩 여부 선택
  - 전처리 도구 선택/미리보기/적용
  - threshold scanning
  - 피처 조건 선택
  - 예측 결과 표시
- `map_trend`, `equip_trend`는 현재 TODO skeleton 상태다.
- `schema.py`는 프로젝트 규칙에 따라 실제 컬럼명/테이블명 대신 placeholder를 유지한다.

## 확장 원칙

1. 실제 도메인 값은 넣지 않는다.
   - 컬럼명, 테이블명, S3 경로, 장비 ID, 센서명 등은 placeholder 또는 mock 값으로 유지한다.

2. 파이프라인은 `schema.py`를 통해 설정을 참조한다.
   - 데이터 관련 상수를 `app.py`나 pipeline 내부에 하드코딩하지 않는다.

3. wrapper와 pipeline은 mock 데이터로 동작 가능한 골격을 먼저 만든다.
   - 실제 DB SDK, S3 parquet, SQL 쿼리는 루코드 담당 영역으로 남긴다.

4. 현재 앱 구조를 존중한다.
   - 당장은 `app.py` 직접 라우팅 방식에 맞춰 워크플로우를 확장한다.
   - `core/orchestrator.py` 통합은 워크플로우 골격이 안정된 뒤 별도 리팩터링 후보로 둔다.

5. 사용자는 각 워크플로우에서 다음 행동을 명확히 선택할 수 있어야 한다.
   - 분기점은 FSM의 decision state로 드러나야 한다.
   - 채팅 메시지는 현재 상태와 다음 입력 예시를 알려줘야 한다.

## 제안 구현 순서

### 1단계: MAP 경향성 워크플로우 골격

우선순위: 높음

이유:
- 사용자가 특정 LOT과 공정을 기준으로 fail이 어디에 몰리는지 빠르게 확인하는 흐름이다.
- 조회 대상이 LOT → 공정 fail 정보 → run/wafer fail 몰림 → wafer map 순서로 자연스럽게 좁혀진다.
- 전공정 데이터를 선택적으로 merge하는 구조라서, 기본 분석과 심화 분석을 나눠 설계하기 좋다.

사용자 의도:

- 특정 LOT 정보를 먼저 조회한다.
- 해당 LOT의 선택 공정에서 fail 정보를 조회한다.
- 해당 LOT의 run/wafer 단위 fail count와 total count를 조회하고 fail 몰림 여부를 확인한다.
- 몰림이 의심되는 run/wafer 중 분석할 wafer를 선택한다.
- 선택된 run_id, wafer_id를 활용해 die 좌표 단위 wafer map 데이터를 조회한다.
- 선택된 wafer에서 fail 발생 빈도에 경향성이 있는지 확인한다.
- fail map이 특정 이미지 형상 또는 공간 패턴을 보이는지 표시한다.
- 옵션으로 전 공정 데이터를 merge하여 전공정 feature별 특이사항이 있었는지 확인한다.

초안 흐름:

```text
IDLE
→ SELECTING_WORKFLOW
→ COLLECTING_PARAMS
→ VALIDATING_PARAMS
→ MAP_QUERYING_LOT
→ MAP_QUERYING_PROCESS_FAILS
→ MAP_SHOWING_FAIL_CONCENTRATION
→ MAP_SELECTING_WAFERS
→ MAP_QUERYING_WAFER_MAP
→ MAP_ANALYZING_FAIL_PATTERN
→ MAP_SHOWING_RESULTS
→ MAP_AWAITING_PREV_PROCESS_MERGE
→ MAP_MERGING_PREV_PROCESS 또는 skip
→ MAP_ANALYZING_PREV_PROCESS_FEATURES 또는 skip
→ MAP_SHOWING_PREV_PROCESS_RESULTS 또는 COMPLETED
```

최종 MAP workflow 요약:

| 구분 | 결정 내용 |
|------|----------|
| 입력 파라미터 | `lot_cd`, `lot_no`, `oper`, `from_date`, `end_date` |
| 선택 파라미터 | target `cat` |
| `lot_cd` 의미 | 제품/LOT 그룹 코드 |
| `lot_no` 의미 | 실제 개별 LOT 번호 |
| `oper` 의미 | fail 정보를 조회할 현재 공정 |
| 1차 fail 집계 | `lot_no`, `run_id`, `wafer_id`, `count`, `total_count` |
| `count` 의미 | fail die 개수 |
| `total_count` 의미 | 전체 die 개수 |
| fail 몰림 기준 | wafer별 `count >= schema.MAP_FAIL_CONCENTRATION_THRESHOLD` |
| 기본 몰림 threshold | `10` |
| wafer 선택 | 추천 후보 번호 선택과 직접 `run_id`/`wafer_id` 입력 모두 지원 |
| 2차 map 상세 | `lot_no`, `run_id`, `wafer_id`, `die_x`, `die_y`, `bin_cd` 또는 `category` |
| fail 판정 | target `cat` 입력 시 `category` 기준, 없으면 기존 `schema.FAILBIN` 기준 |
| layout mask | `schema.MAP_LAYOUT_BY_LOT_CD`에서 `lot_cd` 기준으로 선택 |
| layout fallback | `schema.MAP_DEFAULT_LAYOUT` |
| layout 의미 | `1=die 존재 좌표`, `0=die 없음/wafer 바깥` |
| 좌표축 설정 | `MAP_LAYOUT_ROW_AXIS`, `MAP_LAYOUT_COL_AXIS` |
| 좌표 offset | 기본 `die_x = col_index - MAP_LAYOUT_X_OFFSET`, `die_y = row_index - MAP_LAYOUT_Y_OFFSET` |
| 개별 map 색상 | missing/미측정=회색, normal=연두색, fail=빨간색 |
| 여러 wafer 표시 | 개별 wafer map과 aggregate map 모두 표시 |
| aggregate map | MVP에서는 같은 좌표의 fail 누적 count를 색 농도로 표시 |
| MVP 형상 판정 | edge 집중, center 집중, random |
| 전공정 선택 | `schema.PREV_PROCESS_OPTIONS`에서 여러 개 선택 가능 |
| 전공정 merge key | `run_id`, `wafer_id`, `die_x`, `die_y` |
| 전공정 feature 분석 | feature map과 fail result map의 유사도 계산 |
| similarity metric | masked Pearson correlation, masked cosine similarity |
| normalization | schema 설정, 기본 `"zscore"` |
| total score | `(abs(pearson_score) + cosine_score) / 2` |
| feature ranking | schema 설정, 기본 Top 10 |

MVP 구현 상태:

상세 설계 상태를 모두 FSM에 넣기보다, 첫 구현에서는 아래 상태로 압축한다.

```text
IDLE
→ SELECTING_WORKFLOW
→ COLLECTING_PARAMS
→ VALIDATING_PARAMS
→ MAP_QUERYING_LOT
→ MAP_SHOWING_FAIL_CONCENTRATION
→ MAP_SELECTING_WAFERS
→ MAP_ANALYZING_WAFER_MAP
→ MAP_SHOWING_RESULTS
→ MAP_AWAITING_PREV_PROCESS_MERGE
→ MAP_ANALYZING_PREV_PROCESS 또는 COMPLETED
→ MAP_SHOWING_PREV_PROCESS_RESULTS 또는 COMPLETED
```

압축 기준:

- `MAP_QUERYING_LOT`에서 LOT 기본 조회와 1차 fail 집계 조회를 함께 수행한다.
- `MAP_SHOWING_FAIL_CONCENTRATION`에서 run/wafer별 fail 몰림 후보를 표시한다.
- `MAP_SELECTING_WAFERS`에서 추천 후보 번호 선택과 직접 `run_id`/`wafer_id` 입력을 처리한다.
- `MAP_ANALYZING_WAFER_MAP`에서 2차 wafer map 상세 조회, fail 판정, 개별/aggregate map 생성, edge/center/random 판정을 함께 수행한다.
- `MAP_AWAITING_PREV_PROCESS_MERGE`에서 전공정 merge 여부와 `schema.PREV_PROCESS_OPTIONS` 기반 선택을 처리한다.
- `MAP_ANALYZING_PREV_PROCESS`에서 선택 전공정 데이터 merge와 feature similarity 계산을 함께 수행한다.

필요 상태 후보:

- `MAP_QUERYING_LOT`
  - 입력된 LOT 조건으로 LOT 기본 정보를 조회한다.
- `MAP_QUERYING_PROCESS_FAILS`
  - 해당 LOT의 선택 공정에서 `lot_no`, `run_id`, `wafer_id`, `count`, `total_count` 형태의 fail 집계 정보를 조회한다.
  - 여기서 `count`는 해당 run/wafer의 fail die 개수, `total_count`는 전체 die 개수를 의미한다.
- `MAP_SHOWING_FAIL_CONCENTRATION`
  - run별, wafer별 fail 몰림 여부와 기본 요약을 보여주고 상세 분석할 wafer 범위를 묻는다.
- `MAP_SELECTING_PARAMS`
  - wafer 선택 방식, fail 판정 기준, 분석 기준을 선택한다.
- `MAP_SELECTING_WAFERS`
  - 전체 wafer, 특정 wafer, fail 상위 wafer, 특정 run의 wafer 등 분석 대상을 확정한다.
  - fail 몰림 후보 번호 선택과 직접 `run_id`/`wafer_id` 입력을 모두 지원한다.
- `MAP_QUERYING_WAFER_MAP`
  - 선택된 `run_id`, `wafer_id`를 활용해 `lot_no`, `run_id`, `wafer_id`, `die_x`, `die_y`, `bin_cd` 또는 `category` 형태의 map 상세 데이터를 조회한다.
- `MAP_ANALYZING_FAIL_PATTERN`
  - fail 발생 빈도 경향과 map 형상/공간 패턴을 분석한다.
- `MAP_SHOWING_RESULTS`
  - wafer별 fail rate, run별 편차, heatmap, pattern summary를 표시한다.
- `MAP_AWAITING_PREV_PROCESS_MERGE`
  - 전공정 데이터 merge 분석을 진행할지 묻는다.
- `MAP_MERGING_PREV_PROCESS`
  - 현재 LOT/wafer/map 결과와 전공정 feature 데이터를 merge한다.
- `MAP_ANALYZING_PREV_PROCESS_FEATURES`
  - 전공정 feature별 이상값, 분포 차이, fail 연관 후보를 분석한다.
- `MAP_SHOWING_PREV_PROCESS_RESULTS`
  - 전공정 feature 특이사항 요약과 후보 feature ranking을 표시한다.

초기 MVP 범위:

- schema placeholder 기반 MAP/전공정 설정 추가
- 특정 LOT 기준 mock LOT 기본 정보 생성
- 해당 공정의 mock fail 정보 생성
- `lot_no`, `run_id`, `wafer_id`, `count`, `total_count` 기반 run/wafer별 fail die 몰림 요약
- wafer별 mock 좌표 map 데이터 생성
- fail 빈도 요약
  - run별 fail rate
  - wafer별 fail rate
  - wafer 내 zone별 fail rate
- fail 몰림 후보 기준
  - wafer별 fail die `count >= 10`
  - fail rate는 보조 지표로 함께 표시
- map 형상 판단
  - edge 집중
  - center 집중
  - random 후보
- wafer map scatter plot 표시
  - 없는 데이터 또는 미측정 die: 회색
  - 정상 die: 연두색
  - fail die: 빨간색
  - wafer layout mask를 사용해 die가 있어야 하는 좌표와 wafer 바깥 좌표를 구분한다.
  - layout mask에서 `1`은 die 존재 좌표, `0`은 die가 없어도 되는 좌표를 의미한다.
  - 여러 wafer를 선택하면 wafer별 scatter plot과 aggregate map을 모두 표시한다.
- 전공정 merge 여부 분기
- 전공정 feature mock 데이터 merge
- 전공정 feature map과 fail bin 결과 map 간 유사도 계산
- fail map과 유사도가 높은 전공정 feature ranking 표시

보류:

- 실제 LOT/run/wafer 조회 SQL
- 실제 wafer map 테이블 연결
- 실제 전공정 feature 테이블 연결
- 실제 merge key 확정
- 고급 이미지 패턴 인식
- ring-like 패턴 판정
- line/scratch-like 패턴 판정
- 통계 검정/모델 기반 원인 feature 탐색
- 고급 image similarity 또는 pattern matching 알고리즘

schema.py에 추가할 placeholder 후보:

```python
MAP_REQUIRED_PARAMS = [
    {"key": "lot_cd", "label": "LOT 코드", "type": "text"},
    {"key": "lot_no", "label": "LOT 번호", "type": "text"},
    {"key": "oper", "label": "공정(OPER)", "type": "text"},
    {"key": "from_date", "label": "시작일", "type": "date", "format": "YYYYMMDD"},
    {"key": "end_date", "label": "종료일", "type": "date", "format": "YYYYMMDD"},
]
MAP_OPTIONAL_PARAMS = [
    {"key": "cat", "label": "Target category", "type": "text"},
]

MAP_LOT_TABLE = "schema_name.map_lot_table"
MAP_FAIL_SUMMARY_TABLE = "schema_name.map_fail_summary_table"
MAP_DIE_TABLE = "schema_name.map_die_table"
MAP_LOT_CD_COLUMN = "lot_cd"
MAP_LOT_NO_COLUMN = "lot_no"
MAP_OPER_COLUMN = "oper"
MAP_RUN_COLUMN = "run_id"
MAP_WAFER_COLUMN = "wafer_id"
MAP_FAIL_COUNT_COLUMN = "count"
MAP_TOTAL_COUNT_COLUMN = "total_count"
MAP_FAIL_CONCENTRATION_THRESHOLD = 10
MAP_X_COLUMN = "die_x"
MAP_Y_COLUMN = "die_y"
MAP_BIN_COLUMN = "bin_cd"
MAP_CATEGORY_COLUMN = "category"
MAP_FAIL_COLUMN = "fail_flag"
MAP_VALUE_COLUMN = "map_value"
MAP_LAYOUT_BY_LOT_CD = {
    "lot_cd_placeholder_1": [
        [0, 0, 1, 0, 0],
        [0, 1, 1, 1, 0],
        [1, 1, 1, 1, 1],
        [0, 1, 1, 1, 0],
        [0, 0, 1, 0, 0],
    ],
    "lot_cd_placeholder_2": [
        [0, 1, 1, 1, 0],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [0, 1, 1, 1, 0],
    ],
}
MAP_DEFAULT_LAYOUT = [
    [0, 0, 1, 0, 0],
    [0, 1, 1, 1, 0],
    [1, 1, 1, 1, 1],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 0, 0],
]
MAP_LAYOUT_ROW_AXIS = "die_y"
MAP_LAYOUT_COL_AXIS = "die_x"
MAP_LAYOUT_X_OFFSET = 11
MAP_LAYOUT_Y_OFFSET = 11
MAP_LAYOUT_OFFSET_MODE = "subtract"
MAP_FEATURE_SIMILARITY_NORMALIZATION = "zscore"
MAP_FEATURE_SIMILARITY_TOP_N = 10
MAP_SUMMARY_KEYS = ["lot_no", "run_id", "wafer_id"]
MAP_DIE_QUERY_KEYS = ["lot_no", "run_id", "wafer_id"]
MAP_MERGE_KEYS = ["lot_no", "wafer_id"]

PREV_PROCESS_MERGE_KEYS = ["run_id", "wafer_id", "die_x", "die_y"]
PREV_PROCESS_OPTIONS = [
    {
        "id": "prev_process_1",
        "label": "전공정 1",
        "table": "schema_name.prev_process_table_1",
        "columns": ["col_prev_1", "col_prev_2", "col_prev_3"],
        "merge_keys": PREV_PROCESS_MERGE_KEYS,
    },
    {
        "id": "prev_process_2",
        "label": "전공정 2",
        "table": "schema_name.prev_process_table_2",
        "columns": ["col_prev_4", "col_prev_5", "col_prev_6"],
        "merge_keys": PREV_PROCESS_MERGE_KEYS,
    },
]
```

검토 필요:

- MAP용 LOT 조회는 기존 `REQUIRED_PARAMS`와 별도로 `MAP_REQUIRED_PARAMS`를 사용한다.
- MAP 워크플로우에는 `lot_cd`, `lot_no`, `oper`, `from_date`, `end_date`를 입력 조건으로 사용한다.
- MAP 워크플로우의 선택 입력으로 target `cat`을 받을 수 있다.
- MAP 워크플로우에서 `oper`는 fail 정보를 조회할 현재 공정 기준으로 사용한다.
- `lot_cd`는 제품/LOT 그룹 코드, `lot_no`는 실제 개별 LOT 번호로 사용한다.
- 최초 fail 조회 결과는 `lot_no`, `run_id`, `wafer_id`, `count`, `total_count` 형태의 집계 데이터이며, `count`는 fail die 개수, `total_count`는 전체 die 개수다.
- fail 몰림 후보는 wafer별 fail die `count >= 10`을 기본 기준으로 판정한다.
- fail 몰림 기준값은 `schema.MAP_FAIL_CONCENTRATION_THRESHOLD`로 관리한다.
- wafer 선택은 추천 후보 번호 선택과 직접 `run_id`/`wafer_id` 입력을 모두 지원한다.
- 상세 wafer map 조회는 선택된 `run_id`, `wafer_id`를 사용하며, 결과는 `lot_no`, `run_id`, `wafer_id`, `die_x`, `die_y`, `bin_cd` 또는 `category`를 포함한다.
- fail 판정은 target `cat`이 입력되면 `category` 기준으로 계산하고, target `cat`이 없으면 기존 `schema.FAILBIN`의 oper별 fail bin 기준으로 계산한다.
- map 형상 판단은 좌표 기반으로 충분한지, 실제 map 이미지 파일도 다뤄야 하는지 확인한다.
- wafer map 시각화는 `die_x`, `die_y` scatter plot으로 먼저 구현한다.
- 없는 데이터 또는 미측정 die는 회색, 정상 die는 연두색, fail die는 빨간색으로 표시한다.
- wafer layout mask는 `1=die 존재 좌표`, `0=die 없음/wafer 바깥 좌표`로 해석한다.
- wafer layout mask는 `schema.MAP_LAYOUT_BY_LOT_CD`에서 `lot_cd` 기준으로 선택한다.
- `lot_cd`에 매칭되는 layout이 없으면 `schema.MAP_DEFAULT_LAYOUT`을 사용한다.
- layout matrix의 row/column이 각각 어떤 die 좌표축에 대응되는지는 `schema.MAP_LAYOUT_ROW_AXIS`, `schema.MAP_LAYOUT_COL_AXIS`로 관리한다.
- layout index와 실제 `die_x`, `die_y` 사이의 offset은 `schema.MAP_LAYOUT_X_OFFSET`, `schema.MAP_LAYOUT_Y_OFFSET`으로 관리한다.
- placeholder offset은 `+11` 기준으로 두되, 실제 값은 루코드가 schema에서 교체한다.
- 기본 변환식은 `die_x = col_index - MAP_LAYOUT_X_OFFSET`, `die_y = row_index - MAP_LAYOUT_Y_OFFSET`로 둔다.
- offset 방향은 `schema.MAP_LAYOUT_OFFSET_MODE = "subtract"`로 명시하고, 실제 좌표계 확인 후 schema에서 조정한다.
- layout mask에서 `1`인 좌표인데 상세 map 데이터에 결과가 없으면 회색으로 표시한다.
- layout mask에서 `1`인 좌표이며 상세 map 데이터에서 정상으로 판정되면 연두색, fail로 판정되면 빨간색으로 표시한다.
- 여러 wafer 선택 시 개별 wafer map과 aggregate map을 모두 표시한다.
- aggregate map은 MVP에서 같은 좌표의 fail 누적 count를 색 농도로 표시한다.
- aggregate map의 fail rate 표시는 후속 확장으로 둔다.
- 전공정 데이터 merge는 일반적으로 `run_id`, `wafer_id`, `die_x`, `die_y` 기준의 die 좌표 단위로 수행한다.
- `lot_no`는 전공정 데이터 조회 필터/컨텍스트로 사용하고, 기본 merge key에는 포함하지 않는다.
- 전공정 데이터는 여러 개 선택할 수 있다.
- 선택 가능한 전공정 데이터 목록은 `schema.PREV_PROCESS_OPTIONS`에서 관리한다.
- 각 전공정 option은 `id`, `label`, `table`, `columns`, `merge_keys`를 가진다.
- 전공정 feature 특이사항은 fail die와 normal die의 단순 평균 차이보다, wafer 좌표 배열 간 유사도를 우선한다.
- 정수 또는 실수 feature를 `die_x`, `die_y` 기준의 feature map 배열로 변환한다.
- fail bin 또는 target cat 기준으로 만든 결과 map 배열과 feature map 배열의 유사도를 계산한다.
- 유사도가 높은 feature를 전공정 특이사항 후보 ranking으로 표시한다.
- MVP 유사도 metric은 `masked Pearson correlation`과 `masked cosine similarity`를 사용한다.
- layout mask에서 die가 존재하고, fail map과 feature map 양쪽 모두 값이 있는 좌표만 유효 좌표로 사용한다.
- fail map은 `fail=1`, `normal=0` binary 배열로 만든다.
- feature map은 numeric 값을 사용하며, 비교 전에 z-score 또는 min-max 정규화를 적용한다.
- feature map 정규화 방식은 `schema.MAP_FEATURE_SIMILARITY_NORMALIZATION`으로 관리한다.
- MVP 기본 정규화 방식은 `"zscore"`로 둔다.
- feature ranking은 Pearson score, cosine score, total score를 함께 표시한다.
- MVP total score는 `total_score = (abs(pearson_score) + cosine_score) / 2`로 계산한다.
- feature similarity 결과 표시 개수는 `schema.MAP_FEATURE_SIMILARITY_TOP_N`으로 관리한다.
- MVP 기본값은 Top 10이다.

### 2단계: 장비 경향성 워크플로우 골격

우선순위: 중간

초안 흐름:

```text
IDLE
→ SELECTING_WORKFLOW
→ COLLECTING_PARAMS
→ VALIDATING_PARAMS
→ QUERYING_DATA
→ SHOWING_QUERY_RESULTS
→ AWAITING_LOAD_DECISION
→ LOADING_PARQUET 또는 skip
→ SHOWING_DATA_OVERVIEW
→ EQUIP_SELECTING_PARAMS
→ EQUIP_LOADING_DATA
→ EQUIP_TREND_ANALYZING
→ EQUIP_SHOWING_TREND
→ EQUIP_CORRELATION 또는 COMPLETED
```

필요 상태 후보:

- `EQUIP_SELECTING_PARAMS`
  - 장비, 챔버, 센서 목록, 분석 기간을 선택한다.
- `EQUIP_LOADING_DATA`
  - mock 센서 시계열 데이터를 생성하거나 로딩한다.
- `EQUIP_TREND_ANALYZING`
  - rolling mean/std, drift, shift, SPC rule 위반 후보를 계산한다.
- `EQUIP_SHOWING_TREND`
  - 센서별 경향성 요약을 보여주고 불량 상관 분석 여부를 묻는다.
- `EQUIP_CORRELATION`
  - 센서값과 y/fail rate의 mock 상관 요약을 표시한다.

초기 MVP 범위:

- mock time series 생성
- 센서별 평균/표준편차/최근 변화량 계산
- 간단한 drift flag
- 간단한 SPC rule 1 후보
- 결과 summary 반환

보류:

- 실제 장비 센서 테이블 연결
- 실제 센서명 확정
- change point detection
- lag correlation
- 다변량 영향도 분석

### 3단계: 공통 라우팅 정리

우선순위: 중간

목표:
- `app.py`의 상태별 분기를 워크플로우별 함수로 정리한다.
- `conventional`, `map_trend`, `equip_trend`가 공통 구간 이후 자연스럽게 분기되도록 만든다.
- `core/orchestrator.py`의 설계와 실제 앱 흐름 사이의 차이를 줄인다.

후보 구조:

```text
handle_user_input()
├─ _handle_common_states()
├─ _handle_conventional_states()
├─ _handle_map_trend_states()
└─ _handle_equip_trend_states()
```

### 4단계: 문서와 roo_tasks 갱신

상태 머신, 파이프라인 인터페이스, schema placeholder가 바뀌면 다음 문서를 갱신한다.

- `docs/workflow_diagram.md`
- `docs/roo_tasks/02_state_machine.md`
- `docs/roo_tasks/04_pipeline_steps.md`
- `docs/roo_tasks/05_chat_ui.md`
- `docs/roo_tasks/06_orchestrator.md`

## 결정이 필요한 질문

### Q1. MAP 워크플로우의 첫 MVP 초점

후보:

- A. wafer 공간 패턴 분석 중심
  - 한 LOT/wafer의 center/edge/random 패턴을 먼저 분석한다.
- B. LOT 간 map trend 비교 중심
  - 여러 LOT의 map 패턴 변화와 유사도를 먼저 비교한다.

현재 추천: A

### Q2. MAP 결과 표시 수준

후보:

- A. 텍스트 summary + DataFrame 위주
- B. heatmap 이미지까지 포함

현재 추천: B

### Q3. 장비 워크플로우의 첫 MVP 초점

후보:

- A. 센서별 drift/SPC 감지
- B. 장비 파라미터와 불량률 상관 분석

현재 추천: A

### Q4. 구현 구조

후보:

- A. 현재 `app.py` 직접 라우팅에 먼저 추가
- B. `core/orchestrator.py` 중심으로 먼저 리팩터링 후 추가

현재 추천: A

## 다음 액션

1. 이 문서의 질문 Q1~Q4를 사용자와 함께 확정한다.
2. 확정된 방향에 맞춰 MAP 워크플로우 상태와 mock pipeline 인터페이스를 먼저 설계한다.
3. 설계가 맞으면 구현 전 `docs/workflow_diagram.md` 초안을 갱신한다.
4. 이후 FSM, app handler, pipeline mock, 테스트 순서로 구현한다.
