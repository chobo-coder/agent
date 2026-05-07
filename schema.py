"""
데이터 스키마 정의 — 실제 컬럼명/테이블명을 여기에 작성.
루코드가 코딩할 때 이 파일을 참조하여 파이프라인 코드에 반영합니다.

[작성 방법]
1. 아래 placeholder를 실제 값으로 교체
2. 컬럼을 추가/삭제하려면 리스트 수정
3. app.py, pipeline/ 코드는 이 파일을 import하여 사용
"""

# =============================================================================
# 사용자 입력 파라미터 (워크플로우 시작 시 수집)
# =============================================================================

# 필수 입력 항목 정의
# key: 내부 식별자, label: 사용자에게 보여줄 이름, type: 입력 유형
REQUIRED_PARAMS = [
    {"key": "lot_cd", "label": "LOT 코드", "type": "text"},
    {"key": "from_date", "label": "시작일", "type": "date", "format": "YYYY-MM-DD"},
    {"key": "end_date", "label": "종료일", "type": "date", "format": "YYYY-MM-DD"},
]

# 선택 입력 (cat 지정 시 해당 cat 유무로 Y값 결정)
OPTIONAL_PARAMS = [
    {"key": "cat", "label": "분석 카테고리 (선택)", "type": "text"},
]

# 카테고리 목록 (선택지가 정해져 있을 경우)
# 빈 리스트면 자유 입력, 값이 있으면 이 중에서만 선택
CAT_OPTIONS = [
    # TODO: 실제 카테고리명으로 교체
    "CAT_A",
    "CAT_B",
    "CAT_C",
]

# =============================================================================
# DB 테이블 정보
# =============================================================================

DB_TABLE = "schema_name.table_name"  # TODO: 실제 테이블명
DB_DATE_COLUMN = "created_at"  # TODO: 날짜 컬럼명
DB_LOT_COLUMN = "lot_cd"  # TODO: LOT 코드 컬럼명
DB_CAT_COLUMN = "cat"  # TODO: 카테고리 컬럼명
DB_LOOKBACK_DAYS = 90  # 조회할 최근 일수

# DB에서 조회할 컬럼 목록
DB_COLUMNS = [
    "col_1",  # TODO: 실제 컬럼명으로 교체
    "col_2",
    "col_3",
    "col_4",
    "col_5",
    "col_6",
]

# =============================================================================
# S3 parquet 정보
# =============================================================================

S3_PATH_PATTERN = "data/{product}/"  # TODO: 실제 경로 패턴
S3_MERGE_KEYS = ["col_1", "col_2"]  # TODO: DB와 S3 데이터를 머지할 키 컬럼

# S3 parquet의 컬럼 목록
S3_COLUMNS = [
    "col_1",  # TODO: 실제 컬럼명으로 교체
    "col_2",
    "col_s3_a",
    "col_s3_b",
]

# =============================================================================
# 컬럼 유형 분류
# =============================================================================

# 수치형 컬럼 (전처리/분석 대상)
NUMERIC_COLUMNS = [
    "col_3",  # TODO: 실제 수치형 컬럼
    "col_4",
    "col_5",
    "col_s3_a",
    "col_s3_b",
]

# 범주형 컬럼 (인코딩 대상)
CATEGORICAL_COLUMNS = [
    "col_6",  # TODO: 실제 범주형 컬럼
]

# 타겟 변수 (피처 중요도 계산 시 종속변수)
TARGET_COLUMN = "y"  # 자동 생성됨 (cat 또는 FAILBIN 기반)

# =============================================================================
# Y값 결정 로직
# =============================================================================
# cat 컬럼명 (DB 내)
DB_CAT_COLUMN = "cat"

# 1) cat 파라미터가 지정된 경우:
#    → y = 1 if row[DB_CAT_COLUMN] == 지정된 cat값 else 0
#
# 2) cat 파라미터가 없는 경우:
#    → FAILBIN 설정 사용. oper별 bin 값 리스트에 해당하면 y=1
#
# FAILBIN: oper(공정)를 key로, fail로 판정할 bin 번호 리스트를 value로 지정
FAILBIN = {
    # TODO: 실제 oper명과 fail bin 번호로 교체
    "OPER_01": [3, 5, 7],
    "OPER_02": [2, 4],
    "OPER_03": [1, 6, 8],
}

# =============================================================================
# 전처리 도구 (사용자가 선택 가능한 도구 목록)
# =============================================================================

# 각 도구는 고정된 파라미터를 가지며, 사용자는 번호/이름으로 선택
PREPROCESSING_TOOLS = [
    {
        "id": "drop_missing",
        "name": "결측치 제거",
        "description": "결측치가 포함된 행을 삭제",
        "handler": "missing_values",
        "params": {"missing_strategy": "drop"},
    },
    {
        "id": "fill_mean",
        "name": "결측치 평균 대체",
        "description": "수치형 컬럼의 결측치를 평균값으로 채움",
        "handler": "missing_values",
        "params": {"missing_strategy": "mean"},
    },
    {
        "id": "fill_median",
        "name": "결측치 중앙값 대체",
        "description": "수치형 컬럼의 결측치를 중앙값으로 채움",
        "handler": "missing_values",
        "params": {"missing_strategy": "median"},
    },
    {
        "id": "remove_outliers_iqr",
        "name": "이상치 제거 (IQR)",
        "description": "IQR 1.5배 기준으로 이상치 행 제거",
        "handler": "outliers",
        "params": {"outlier_method": "iqr", "outlier_threshold": 1.5},
    },
    {
        "id": "remove_outliers_zscore",
        "name": "이상치 제거 (Z-score)",
        "description": "Z-score 3.0 기준으로 이상치 행 제거",
        "handler": "outliers",
        "params": {"outlier_method": "zscore", "outlier_threshold": 3.0},
    },
    {
        "id": "onehot_encoding",
        "name": "원핫 인코딩",
        "description": "범주형 컬럼을 원핫 인코딩으로 변환",
        "handler": "encoding",
        "params": {"encoding_method": "onehot"},
    },
    {
        "id": "standard_scaling",
        "name": "표준 스케일링",
        "description": "수치형 컬럼을 평균 0, 표준편차 1로 변환",
        "handler": "scaling",
        "params": {"scaling_method": "standard"},
    },
    {
        "id": "minmax_scaling",
        "name": "MinMax 스케일링",
        "description": "수치형 컬럼을 0~1 범위로 변환",
        "handler": "scaling",
        "params": {"scaling_method": "minmax"},
    },
    {
        "id": "robust_scaling",
        "name": "로버스트 스케일링",
        "description": "이상치에 강건한 스케일링 (중앙값/IQR 기반)",
        "handler": "scaling",
        "params": {"scaling_method": "robust"},
    },
    {
        "id": "drop_low_variance",
        "name": "저분산 컬럼 제거",
        "description": "분산이 임계값 미만인 컬럼을 제거",
        "handler": "low_variance",
        "params": {"variance_threshold": 0.01},
    },
    {
        "id": "drop_high_na",
        "name": "NA 다수 컬럼 제거",
        "description": "결측치 비율이 임계값 이상인 컬럼을 제거",
        "handler": "high_na_columns",
        "params": {"na_threshold": 0.5},
    },
    {
        "id": "drop_insignificant_ttest",
        "name": "t-test 비유의 컬럼 제거",
        "description": "타겟 대비 t-test p-value가 유의수준 이상인 컬럼 제거",
        "handler": "ttest_filter",
        "params": {"alpha": 0.05},
    },
    {
        "id": "drop_correlated_pairs",
        "name": "고상관 페어 컬럼 제거",
        "description": "상관계수가 임계값 이상인 컬럼 쌍 중 하나를 제거",
        "handler": "correlated_pairs",
        "params": {"corr_threshold": 0.9},
    },
]

# =============================================================================
# 피처 분석 설정
# =============================================================================

# 예측에 사용 가능한 피처 목록 (사용자가 선택할 수 있는 범위)
AVAILABLE_FEATURES = [
    "col_3",
    "col_4",
    "col_s3_a",
    "col_s3_b",
]

# 기본 threshold
DEFAULT_THRESHOLD = 0.5

# =============================================================================
# MAP 경향성 분석 설정
# =============================================================================

# TODO: MAP 분석에 필요한 설정 추가
# MAP_TABLE = "schema_name.wafer_map_table"  # wafer map 데이터 테이블
# MAP_WAFER_ID_COLUMN = "wafer_id"           # wafer 식별 컬럼
# MAP_X_COLUMN = "die_x"                     # die X 좌표 컬럼
# MAP_Y_COLUMN = "die_y"                     # die Y 좌표 컬럼
# MAP_VALUE_COLUMN = "bin_cd"                # 분석 대상 값 (bin code, 수율 등)
# MAP_ANALYSIS_TYPES = [
#     "spatial_clustering",    # 공간 클러스터링 (edge, center, random)
#     "zone_analysis",         # zone별 불량률 비교
#     "pattern_matching",      # 알려진 패턴 매칭 (scratch, ring 등)
# ]

# =============================================================================
# 장비 경향성 분석 설정
# =============================================================================

# TODO: 장비 경향성 분석에 필요한 설정 추가
# EQUIP_TABLE = "schema_name.equip_sensor_table"  # 장비 센서 데이터 테이블
# EQUIP_ID_COLUMN = "equip_id"                    # 장비 식별 컬럼
# EQUIP_CHAMBER_COLUMN = "chamber_id"             # 챔버 식별 컬럼
# EQUIP_TIMESTAMP_COLUMN = "collected_at"         # 센서 수집 시각 컬럼
# EQUIP_SENSOR_COLUMNS = [
#     "temperature",    # 온도
#     "pressure",       # 압력
#     "flow_rate",      # 유량
#     "power",          # 파워
# ]
# EQUIP_SPC_RULES = {
#     "rule_1": 1,      # 1 point > 3 sigma
#     "rule_2": 9,      # 9 points same side of center
#     "rule_3": 6,      # 6 points continuously increasing/decreasing
# }
# EQUIP_TREND_WINDOW_DAYS = 30  # 경향성 분석 기간 (일)
