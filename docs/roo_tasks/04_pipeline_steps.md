# Task 04: Pipeline Steps

## Goal
6개 파이프라인 핸들러의 실제 비즈니스 로직 구현 + wrapper 연동

---

## 현재 상태

- `pipeline/__init__.py`: `BaseHandler` ABC 정의
- 6개 핸들러 스캐폴딩 완료 (기본 로직 포함)
- `wrappers/sdk_wrapper.py`: `NotImplementedError` stub
- `wrappers/s3_wrapper.py`: `NotImplementedError` stub

---

## 구현 상세

### 4-1. SDK Wrapper 실제 연동

`wrappers/sdk_wrapper.py`:

```python
class SDKWrapper:
    def __init__(self):
        self._api_url = config.SDK_API_URL
        self._api_key = config.SDK_API_KEY
        # TODO: 사내 SDK 클라이언트 초기화
        # from internal_sdk import Client
        # self._client = Client(url=self._api_url, key=self._api_key)

    def execute_query(self, query: str) -> pd.DataFrame:
        """
        실제 구현 시:
        1. SDK 클라이언트로 쿼리 실행
        2. 결과를 pd.DataFrame으로 변환
        3. 연결 에러/타임아웃 핸들링

        예상 인터페이스:
            result = self._client.query(query)
            return result.to_dataframe()
        """
        # 개발/테스트용 mock 데이터 반환 (실 연동 전까지)
        import numpy as np
        n = 100
        return pd.DataFrame({
            "product_name": ["ProductA"] * n,
            "date": pd.date_range("2024-01-01", periods=n),
            "metric_a": np.random.randn(n),
            "metric_b": np.random.rand(n) * 100,
            "category": np.random.choice(["A", "B", "C"], n),
        })

    def test_connection(self) -> bool:
        """SDK 연결 테스트"""
        try:
            # self._client.ping()
            return True
        except Exception:
            return False
```

**교체 시 주의사항:**
- 사내 SDK 패키지를 `requirements.txt`에 추가
- `config.py`에 추가 설정값이 필요하면 반영
- 쿼리 타임아웃 기본 30초로 설정

### 4-2. S3 Wrapper 실제 연동

`wrappers/s3_wrapper.py`:

```python
class S3Wrapper:
    def read_parquet(self, prefix: str) -> pd.DataFrame:
        """
        S3에서 prefix 하위 모든 parquet 파일을 읽어 concat.

        실제 구현:
            files = self.list_files(prefix)
            dfs = []
            for key in files:
                s3_path = f"s3://{self._bucket}/{key}"
                dfs.append(pd.read_parquet(s3_path))
            return pd.concat(dfs, ignore_index=True)
        """
        files = self.list_files(prefix)
        if not files:
            raise DataNotFoundError(f"No parquet files under: {prefix}")

        dfs = []
        for key in files:
            s3_uri = f"s3://{self._bucket}/{key}"
            df = pd.read_parquet(
                s3_uri,
                storage_options={
                    "key": os.getenv("AWS_ACCESS_KEY_ID"),
                    "secret": os.getenv("AWS_SECRET_ACCESS_KEY"),
                    "region_name": config.S3_REGION,
                },
            )
            dfs.append(df)
        return pd.concat(dfs, ignore_index=True)


class DataNotFoundError(Exception):
    pass
```

**주의사항:**
- AWS 자격증명은 환경변수 또는 IAM Role 사용
- 대용량 파일 시 `pyarrow.dataset`으로 lazy loading 고려
- prefix 패턴: `data/{product_name}/YYYY/MM/` 확인 필요

### 4-3. DataQueryHandler — SQL 쿼리 고도화

`pipeline/data_query.py`:

```python
def _build_query(self, product: str) -> str:
    """
    실제 쿼리 작성 시 확인사항:
    - 테이블명: analytics.product_data? 실제 스키마 확인
    - 날짜 범위 제한 (최근 N일)
    - 필요한 컬럼만 SELECT (성능)
    - SQL injection 방지: 파라미터 바인딩 사용
    """
    # TODO: 실제 테이블/스키마에 맞게 수정
    return f"""
    SELECT
        product_name,
        created_at,
        metric_a,
        metric_b,
        metric_c,
        category,
        segment
    FROM analytics.product_metrics
    WHERE product_name = %(product)s
      AND created_at >= CURRENT_DATE - INTERVAL '90 days'
    ORDER BY created_at DESC
    LIMIT 10000
    """
```

**변경 필요:**
- `%(product)s` 파라미터 바인딩 방식은 사내 SDK에 맞게 조정
- 실제 테이블명, 컬럼명 반영
- 날짜 범위는 설정으로 분리 (`config.QUERY_LOOKBACK_DAYS`)

### 4-4. DataLoaderHandler — 머지 로직 개선

`pipeline/data_loader.py`:

```python
def _merge(self, existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """
    실제 머지 시 고려사항:
    - join key 확인 (date? product_name + date?)
    - 중복 행 처리 전략
    - 컬럼 충돌 시 suffix 처리
    - 타입 불일치 해결
    """
    if existing is None:
        return new

    # 공통 키로 left join
    common_keys = list(set(existing.columns) & set(new.columns) & {"date", "product_name"})

    if common_keys:
        merged = existing.merge(new, on=common_keys, how="left", suffixes=("", "_s3"))
    else:
        merged = pd.concat([existing, new], ignore_index=True)

    return merged.drop_duplicates().reset_index(drop=True)
```

### 4-5. PreprocessingHandler — 파라미터 확장

현재 구현은 기본 동작. 추가 구현:

```python
def _handle_outliers(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """method 파라미터에 따라 IQR 또는 Z-score 사용"""
    method = params.get("outlier_method", "iqr")
    threshold = params.get("outlier_threshold", 1.5)

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if method == "iqr":
        for col in numeric_cols:
            q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
            iqr = q3 - q1
            mask = (df[col] >= q1 - threshold * iqr) & (df[col] <= q3 + threshold * iqr)
            df = df[mask]
    elif method == "zscore":
        from scipy import stats
        z_scores = np.abs(stats.zscore(df[numeric_cols], nan_policy="omit"))
        df = df[(z_scores < threshold).all(axis=1)]
    return df

def _handle_scaling(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """method에 따라 Standard/MinMax/Robust 선택"""
    method = params.get("scaling_method", "standard")
    numeric_cols = df.select_dtypes(include=[np.number]).columns

    if method == "standard":
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
    elif method == "minmax":
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
    elif method == "robust":
        from sklearn.preprocessing import RobustScaler
        scaler = RobustScaler()
    else:
        return df

    df[numeric_cols] = scaler.fit_transform(df[numeric_cols])
    return df
```

### 4-6. FeatureAnalysisHandler — 피처 중요도 추가

```python
from sklearn.ensemble import RandomForestClassifier

def _compute_importance(self, df: pd.DataFrame, target_col: str | None = None) -> pd.DataFrame:
    """RandomForest 기반 피처 중요도"""
    numeric_df = df.select_dtypes(include=[np.number])
    if target_col and target_col in numeric_df.columns:
        X = numeric_df.drop(columns=[target_col])
        y = (numeric_df[target_col] > numeric_df[target_col].median()).astype(int)
    else:
        # target 미지정 시 마지막 컬럼 사용
        X = numeric_df.iloc[:, :-1]
        y = (numeric_df.iloc[:, -1] > numeric_df.iloc[:, -1].median()).astype(int)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)

    importance_df = pd.DataFrame({
        "feature": X.columns,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)

    return importance_df
```

### 4-7. PredictionHandler — 모델 교체 준비

현재는 정규화 평균 스코어링. 실제 모델 연동 시:

```python
def _predict(self, df: pd.DataFrame, features: list[str], threshold: float) -> np.ndarray:
    """
    교체 전략:
    1단계 (현재): 정규화 평균 스코어링
    2단계: 사전 학습된 모델 로딩 (pickle/joblib)
    3단계: 실시간 API 호출

    2단계 구현 시:
        import joblib
        model = joblib.load("models/trained_model.pkl")
        return model.predict_proba(feature_df)[:, 1]
    """
    if not features:
        features = df.select_dtypes(include=[np.number]).columns.tolist()

    feature_df = df[features].select_dtypes(include=[np.number])
    if feature_df.empty:
        return np.zeros(len(df))

    # 현재: 단순 스코어링
    normalized = (feature_df - feature_df.min()) / (feature_df.max() - feature_df.min() + 1e-8)
    return normalized.mean(axis=1).values
```

---

## 테스트 추가

`tests/test_pipeline.py`에 추가:

```python
class TestDataQuery:
    def test_build_query_contains_product(self):
        handler = DataQueryHandler()
        query = handler._build_query("TestProduct")
        assert "TestProduct" in query or "%(product)s" in query

    def test_execute_returns_dataframe(self, mock_session):
        """SDK mock으로 execute 테스트"""
        with patch.object(SDKWrapper, "execute_query", return_value=sample_df):
            handler = DataQueryHandler()
            result = handler.execute(mock_session)
            assert "query_result" in result.dataframes


class TestDataLoader:
    def test_merge_with_none_existing(self, sample_df):
        handler = DataLoaderHandler()
        result = handler._merge(None, sample_df)
        assert len(result) == len(sample_df)

    def test_merge_deduplication(self, sample_df):
        handler = DataLoaderHandler()
        result = handler._merge(sample_df, sample_df)
        assert len(result) == len(sample_df)  # 중복 제거


class TestPreprocessingExtended:
    def test_outliers_zscore(self, sample_df):
        handler = PreprocessingHandler()
        result = handler._handle_outliers(sample_df, {"outlier_method": "zscore", "outlier_threshold": 3.0})
        assert len(result) <= len(sample_df)

    def test_scaling_minmax(self, sample_df):
        handler = PreprocessingHandler()
        result = handler._handle_scaling(sample_df.select_dtypes(include=[np.number]), {"scaling_method": "minmax"})
        assert result.max().max() <= 1.0
        assert result.min().min() >= 0.0
```

---

## 파일 체크리스트

| 파일 | 액션 | 변경 내용 |
|------|------|----------|
| `wrappers/sdk_wrapper.py` | 수정 | 실제 SDK 연동 (또는 mock 데이터 유지) |
| `wrappers/s3_wrapper.py` | 수정 | boto3 parquet 읽기 구현 |
| `pipeline/data_query.py` | 수정 | 실제 SQL 쿼리, 파라미터 바인딩 |
| `pipeline/data_loader.py` | 수정 | 키 기반 머지 로직 |
| `pipeline/preprocessing.py` | 수정 | zscore, minmax, robust 추가 |
| `pipeline/feature_analysis.py` | 수정 | RF 피처 중요도 추가 |
| `pipeline/prediction.py` | 수정 | 모델 교체 인터페이스 준비 |
| `tests/test_pipeline.py` | 수정 | 각 핸들러 테스트 추가 |

---

## 완료 기준

- [ ] SDK wrapper로 실제 DB 쿼리 실행 (또는 mock으로 정상 동작)
- [ ] S3 wrapper로 parquet 파일 읽기 성공
- [ ] 머지 시 중복 제거 + 키 기반 조인 동작
- [ ] 전처리 5가지 옵션 모두 파라미터 반영
- [ ] 피처 중요도 DataFrame 생성 확인
- [ ] 예측 점수가 0~1 범위
- [ ] `pytest tests/test_pipeline.py` 전체 통과

---

## 변경 이력

### 2026-05-07: schema.py 중앙 설정 + 도구 기반 전처리 방식 전환

**변경 사항:**
- `schema.py`에 `REQUIRED_PARAMS`, `PROCESS_OPTIONS`, `PREPROCESSING_TOOLS` 추가
- `pipeline/data_query.py`가 `schema.DB_TABLE`, `schema.DB_COLUMNS`, `schema.DB_PRODUCT_COLUMN`, `schema.DB_DATE_COLUMN` 참조하도록 변경
- `pipeline/data_loader.py`가 `schema.S3_PATH_PATTERN`, `schema.S3_MERGE_KEYS` 참조하도록 변경
- 전처리가 자유 텍스트 파싱 → 미리 설정된 도구(PREPROCESSING_TOOLS) 선택 방식으로 변경

**새로 추가된 인터페이스:**
```python
# schema.py — 전처리 도구 정의
PREPROCESSING_TOOLS = [
    {
        "id": "drop_missing",           # 내부 식별자
        "name": "결측치 제거",           # UI 표시명
        "description": "결측치가 포함된 행을 삭제",
        "handler": "missing_values",    # PreprocessingHandler 내 메서드 매핑
        "params": {"missing_strategy": "drop"},  # 고정 파라미터
    },
    # ... 총 9개 도구 (결측치 3, 이상치 2, 인코딩 1, 스케일링 3)
]

# app.py — 도구 선택 파싱
def _parse_tool_selection(user_input: str) -> list[dict]:
    """사용자 입력에서 선택된 도구 목록 반환.

    매칭 방식:
    1. 번호 ("1, 3, 5" → 해당 번호의 도구)
    2. ID ("drop_missing" → 해당 ID의 도구)
    3. 키워드 ("이상치", "스케일링" → 관련 도구, 우선순위 기반)

    Returns:
        list[dict] — 선택된 PREPROCESSING_TOOLS 항목들
    """
```

**기존 코드 수정:**
- `pipeline/data_query.py:_build_query` — 하드코딩된 테이블/컬럼명 대신 `schema.*` 상수 참조
- `pipeline/data_loader.py:_merge` — `schema.S3_MERGE_KEYS`를 join key로 사용
- `pipeline/preprocessing.py:execute` — `session.metadata["selected_tools"]`에서 도구 목록을 받아 각 도구의 `handler`와 `params`로 실행

**루코드 구현 시 주의사항:**
- `schema.py`의 TODO 항목들은 사용자가 실제 값으로 교체할 영역 (코드 로직은 건드리지 않음)
- 전처리 핸들러는 `tool["handler"]` 값으로 내부 메서드를 디스패치: `"missing_values"` → `_handle_missing_values(df, tool["params"])`
- 도구 선택 시 키워드 우선순위: 구체적 키워드(평균/중앙값) > 일반 키워드(결측/이상치)
- `PREPROCESSING_TOOLS`에 새 도구 추가 시 `pipeline/preprocessing.py`에 대응 핸들러 메서드도 추가 필요

### 2026-05-07: 조회 파라미터 변경 + 전처리 도구 4개 추가 + MAP/장비 파이프라인 스캐폴딩

**변경 사항:**
- `schema.py` 조회 파라미터 변경: `product/date_from/date_to/process` → `lot_cd/from_date/end_date/cat(선택)`
- `schema.py`에 `OPTIONAL_PARAMS`, `FAILBIN`, Y값 결정 로직 설명 추가
- `schema.py`에 MAP/장비 설정 TODO 추가 (`MAP_TABLE`, `EQUIP_TABLE` 등)
- `schema.PREPROCESSING_TOOLS`에 4개 도구 추가 (총 13개):
  - `drop_low_variance`: 저분산 컬럼 제거
  - `drop_high_na`: NA 다수 컬럼 제거
  - `drop_insignificant_ttest`: t-test 비유의 컬럼 제거
  - `drop_correlated_pairs`: 고상관 페어 컬럼 제거
- `pipeline/preprocessing.py`에 4개 핸들러 메서드 추가
- `pipeline/map_trend.py` 신규 생성 (TODO 스캐폴딩)
- `pipeline/equip_trend.py` 신규 생성 (TODO 스캐폴딩)

**새로 추가된 인터페이스:**
```python
# schema.py — 조회 파라미터
REQUIRED_PARAMS = [
    {"key": "lot_cd", "label": "LOT 코드", "type": "text"},
    {"key": "from_date", "label": "시작일", "type": "date", "format": "YYYY-MM-DD"},
    {"key": "end_date", "label": "종료일", "type": "date", "format": "YYYY-MM-DD"},
]
OPTIONAL_PARAMS = [
    {"key": "cat", "label": "분석 카테고리 (선택)", "type": "text"},
]

# schema.py — Y값 결정
FAILBIN = {
    "OPER_01": [3, 5, 7],  # oper → fail bin 번호 리스트
    "OPER_02": [2, 4],
}

# pipeline/preprocessing.py — 추가 메서드
def _handle_low_variance(self, df, params) -> DataFrame: ...
def _handle_high_na_columns(self, df, params) -> DataFrame: ...
def _handle_ttest_filter(self, df, params) -> DataFrame: ...
def _handle_correlated_pairs(self, df, params) -> DataFrame: ...

# pipeline/map_trend.py — TODO 핸들러 5개
# MapParamHandler, MapDataLoader, MapAnalyzer, MapResultHandler, MapCompareHandler

# pipeline/equip_trend.py — TODO 핸들러 5개
# EquipParamHandler, EquipDataLoader, EquipTrendAnalyzer, EquipTrendResult, EquipCorrelation
```

**기존 코드 수정:**
- `schema.py` — `DB_PRODUCT_COLUMN` 삭제, `DB_LOT_COLUMN`/`DB_CAT_COLUMN` 추가
- `pipeline/preprocessing.py:_apply` — 4개 새 handler 분기 추가

**루코드 구현 시 주의사항:**
- `cat`은 선택 파라미터. 지정 시 Y=1(cat 일치)/0, 미지정 시 `FAILBIN`으로 Y 결정
- `_handle_ttest_filter`는 `schema.TARGET_COLUMN`을 참조하여 타겟 기준으로 t-test 수행
- `_handle_correlated_pairs`는 평균 상관이 더 높은 쪽 컬럼을 제거
- MAP/장비 파이프라인은 TODO 주석만 있고 미구현. 구현 시 `pipeline/__init__.py`의 `BaseHandler`를 상속
- MAP 분석에 필요한 schema 설정: `MAP_TABLE`, `MAP_WAFER_ID_COLUMN`, `MAP_X_COLUMN`, `MAP_Y_COLUMN`
- 장비 분석에 필요한 schema 설정: `EQUIP_TABLE`, `EQUIP_SENSOR_COLUMNS`, `EQUIP_SPC_RULES`

### 2026-05-08: EDA (탐색적 데이터 분석) 파이프라인 추가

**변경 사항:**
- `pipeline/eda.py` 신규 생성 — EDA 분석 함수 3개 + 결과 클래스 + 요약 빌더
- `app.py` — EDA 버튼 렌더링 + `_handle_eda()` 핸들러 추가
- `app.py` — `SHOWING_QUERY_RESULTS` 메시지에 EDA 안내 문구 추가

**EDA 실행 시점:**
- `SHOWING_QUERY_RESULTS` 상태에서 사용자가 "📊 EDA 수행" 버튼을 클릭
- 상태 전이 없이 현재 상태 내에서 실행 (S3 로딩 질문은 유지)
- EDA 결과가 채팅에 추가된 후 `eda_done` 메타데이터로 중복 실행 방지
- 롤백 시 `eda_done`도 초기화됨 (스냅샷에 포함)

**새로 추가된 인터페이스:**
```python
# pipeline/eda.py

@dataclass
class EDAResult:
    missing: pd.DataFrame        # columns: [column, count, ratio]
    low_variance: pd.DataFrame   # columns: [column, variance]
    high_correlation: pd.DataFrame  # columns: [col_a, col_b, correlation]
    summary: str                 # 마크다운 요약 텍스트

def run_eda(
    df: pd.DataFrame,
    variance_threshold: float = 0.01,
    corr_threshold: float = 0.9,
) -> EDAResult:
    """EDA 메인 함수. 3개 분석 실행 후 EDAResult 반환."""

def analyze_missing(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼별 결측치 현황 (column, count, ratio). TODO: 루코드 구현"""

def analyze_low_variance(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """저분산 피처 목록 (column, variance). TODO: 루코드 구현"""

def analyze_high_correlation(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """고상관 피처 쌍 (col_a, col_b, correlation). TODO: 루코드 구현"""

# app.py
def _handle_eda(session: SessionManager) -> None:
    """EDA 실행 → 결과 DataFrame 세션 저장 → 채팅에 요약 추가"""
```

**루코드 구현 대상 (TODO):**

| 함수 | 파일 | 현재 상태 | 구현 내용 |
|------|------|----------|----------|
| `analyze_missing()` | `pipeline/eda.py` | mock 데이터 반환 | `df.isnull().sum()` 기반 결측 수/비율 계산 |
| `analyze_low_variance()` | `pipeline/eda.py` | mock 데이터 반환 | `schema.NUMERIC_COLUMNS` 대상 `df.var()` 계산, threshold 미만 필터 |
| `analyze_high_correlation()` | `pipeline/eda.py` | mock 데이터 반환 | `df[NUMERIC_COLUMNS].corr()` 상삼각에서 threshold 이상 쌍 추출 |

**구현 시 참조할 코드:**
```python
# analyze_missing 구현 예시
def analyze_missing(df: pd.DataFrame) -> pd.DataFrame:
    counts = df.isnull().sum()
    ratios = counts / len(df)
    result = pd.DataFrame({
        "column": counts.index,
        "count": counts.values,
        "ratio": ratios.values,
    })
    return result.sort_values("ratio", ascending=False).reset_index(drop=True)

# analyze_low_variance 구현 예시
def analyze_low_variance(df: pd.DataFrame, threshold: float = 0.01) -> pd.DataFrame:
    numeric = df[schema.NUMERIC_COLUMNS].select_dtypes(include="number")
    variances = numeric.var()
    low = variances[variances < threshold]
    return pd.DataFrame({"column": low.index, "variance": low.values}).sort_values("variance")

# analyze_high_correlation 구현 예시
def analyze_high_correlation(df: pd.DataFrame, threshold: float = 0.9) -> pd.DataFrame:
    numeric = df[schema.NUMERIC_COLUMNS].select_dtypes(include="number")
    corr = numeric.corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    pairs = upper.stack().reset_index()
    pairs.columns = ["col_a", "col_b", "correlation"]
    return pairs[pairs["correlation"] >= threshold].sort_values("correlation", ascending=False)
```

**루코드 구현 시 주의사항:**
- 반환 DataFrame의 컬럼명은 반드시 `[column, count, ratio]`, `[column, variance]`, `[col_a, col_b, correlation]` 유지 — `_build_summary()`와 `app.py`가 이 컬럼명에 의존
- `run_eda()`의 인터페이스(파라미터, 반환값)는 변경하지 말 것 — `app.py`의 `_handle_eda()`가 의존
- EDA 결과 DataFrame은 `session.set_dataframe("eda_missing" / "eda_low_variance" / "eda_high_correlation")`로 저장됨
- `schema.NUMERIC_COLUMNS`를 참조하여 수치형 컬럼만 분석 대상으로 할 것

### 2026-05-08: 전처리 미리보기 루프 + 지연 적용 방식 전환

**변경 사항:**
- `pipeline/preprocess_preview.py` 신규 생성 — 전처리 미리보기 계산 + 지연 적용
- `app.py` — `SHOWING_DATA_OVERVIEW` 핸들러를 루프 방식으로 변경, `_apply_preprocess_plan()` + `_parse_complete()` 추가

**변경된 전처리 흐름:**
```
SHOWING_DATA_OVERVIEW (전처리 메뉴 표시)
  → 사용자 "1" 입력 → 결측치 제거 미리보기 (행 -10, 컬럼 변화 없음) → 계획에 누적 → 루프
  → 사용자 "7" 입력 → 스케일링 미리보기 (변환 예정 컬럼 표시) → 계획에 누적 → 루프
  → 사용자 "10" 입력 → 저분산 제거 미리보기 (컬럼 -1) → 계획에 누적 → 루프
  → 사용자 "완료" 입력 → apply_plan()으로 한 번에 적용 → SHOWING_FEATURES로 전이
```

**새로 추가된 인터페이스:**
```python
# pipeline/preprocess_preview.py

@dataclass
class PreprocessAction:
    tool_id: str                        # "drop_missing" 등
    tool_name: str                      # "결측치 제거" 등
    handler: str                        # "missing_values" 등
    params: dict
    drop_indices: list[int] = []        # 제거될 행 인덱스
    drop_columns: list[str] = []        # 제거될 컬럼명
    transform_columns: list[str] = []   # 변환될 컬럼 (스케일링, 인코딩)
    description: str = ""               # 미리보기 설명 텍스트

@dataclass
class PreprocessPlan:
    actions: list[PreprocessAction] = []
    original_shape: tuple[int, int] = (0, 0)

    def add(self, action: PreprocessAction) -> None: ...
    @property
    def all_drop_indices(self) -> set[int]: ...   # 누적 제거 행
    @property
    def all_drop_columns(self) -> set[str]: ...   # 누적 제거 컬럼
    @property
    def remaining_shape(self) -> tuple[int, int]: ...  # 예상 결과 shape
    def build_summary(self) -> str: ...            # 마크다운 요약

def preview_tool(df, tool, plan) -> PreprocessAction:
    """도구의 미리보기 계산 (데이터 변경 없음). 이전 누적 계획 반영."""

def apply_plan(df, plan) -> pd.DataFrame:
    """누적된 계획을 실제 데이터에 적용 (drop_indices + drop_columns 제거)."""

# app.py
def _parse_complete(text: str) -> bool:
    """'완료', '끝', 'done' 등 감지"""

def _apply_preprocess_plan(session) -> str:
    """plan을 실제 적용 → 상태 전이 → 결과 메시지 반환"""
```

**루코드 구현 대상 (TODO):**

| 함수 | 현재 상태 | 구현 내용 |
|------|----------|----------|
| `_preview_missing()` | mock: 10% 행 제거 | `df.dropna()` 시 제거될 인덱스 계산, `fillna` 시 변환 컬럼 계산 |
| `_preview_outliers()` | mock: 5% 행 제거 | IQR/zscore 기준 이상치 인덱스 계산 |
| `_preview_encoding()` | mock: 컬럼명만 반환 | `pd.get_dummies` 시 생성될 컬럼 수 예측 |
| `_preview_scaling()` | mock: 컬럼명만 반환 | 변환 대상 컬럼 목록 (행/컬럼 변화 없음) |
| `_preview_low_variance()` | mock: 첫 컬럼 제거 | `df.var() < threshold` 인 컬럼 계산 |
| `_preview_high_na()` | mock: 빈 목록 | `df.isna().mean() >= threshold` 인 컬럼 계산 |
| `_preview_ttest()` | mock: 마지막 컬럼 제거 | 타겟 대비 p-value >= alpha 컬럼 계산 |
| `_preview_correlated()` | mock: 두 번째 컬럼 제거 | 상관행렬에서 threshold 이상 쌍의 제거 대상 컬럼 계산 |
| `apply_plan()` | drop만 적용 | drop 후 스케일링/인코딩 등 변환도 적용 |

**구현 시 참조할 코드:**
```python
# _preview_missing (strategy="drop") 구현 예시
def _preview_missing(df, tool_id, tool_name, params):
    strategy = params.get("missing_strategy", "drop")
    if strategy == "drop":
        mask = df.isna().any(axis=1)
        drop_indices = df.index[mask].tolist()
        return PreprocessAction(
            tool_id=tool_id, tool_name=tool_name,
            handler="missing_values", params=params,
            drop_indices=drop_indices,
            description=f"결측치 포함 행 {len(drop_indices)}개 제거 예정",
        )
    else:
        cols_with_na = df.columns[df.isna().any()].tolist()
        return PreprocessAction(
            tool_id=tool_id, tool_name=tool_name,
            handler="missing_values", params=params,
            transform_columns=cols_with_na,
            description=f"{len(cols_with_na)}개 컬럼 결측치를 {strategy}으로 대체",
        )

# _preview_low_variance 구현 예시
def _preview_low_variance(df, tool_id, tool_name, params):
    threshold = params.get("variance_threshold", 0.01)
    numeric = df.select_dtypes(include=[np.number])
    drop_cols = numeric.columns[numeric.var() < threshold].tolist()
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="low_variance", params=params,
        drop_columns=drop_cols,
        description=f"저분산 컬럼 {len(drop_cols)}개 제거 예정",
    )

# apply_plan 확장 예시 (변환 포함)
def apply_plan(df, plan):
    result = df.copy()
    # 1) 행 제거
    result = result.drop(index=[i for i in plan.all_drop_indices if i in result.index])
    # 2) 컬럼 제거
    result = result.drop(columns=[c for c in plan.all_drop_columns if c in result.columns])
    # 3) 변환 적용 (스케일링, 인코딩 등)
    for action in plan.actions:
        if action.handler == "scaling":
            result = _apply_scaling(result, action.params)
        elif action.handler == "encoding":
            result = _apply_encoding(result, action.params)
        elif action.handler == "missing_values" and action.params.get("missing_strategy") != "drop":
            result = _apply_fillna(result, action.params)
    return result.reset_index(drop=True)
```

**루코드 구현 시 주의사항:**
- `preview_tool()`은 이전 누적 계획(`plan`)을 반영한 **가상 DataFrame**에서 계산 — `_get_virtual_df(df, plan)` 사용
- `PreprocessPlan`은 `session.metadata["preprocess_plan"]`에 저장됨 → 롤백 시 스냅샷과 함께 복원
- `apply_plan()`은 현재 drop만 적용 — 변환(스케일링, 인코딩, fillna)도 적용하도록 확장 필요
- `build_summary()`의 마크다운 형식 유지 — 채팅에 직접 표시됨
- 사용자가 "완료" 없이 롤백하면 `preprocess_plan`이 스냅샷 시점(None)으로 복원되어 전처리가 초기화됨

### 2026-05-08: Threshold Scanning + 예측 지표 + Scatter Plot 추가

**변경 사항:**
- `schema.py` — `SCANNING_THRESHOLDS`, `SCANNING_CONDITIONS` 상수 추가
- `pipeline/threshold_scanning.py` 신규 생성:
  - `run_threshold_scanning()` — 피처/임계값/조건 조합별 성능 지표 계산
  - `compute_prediction_metrics()` — 선택된 조건 조합으로 screen_rate/drop_rate/roi/f1_score 재계산
  - `plot_feature_scatter()` — matplotlib scatter plot (1D/2D/3D, y=1 빨간색, 임계값 라인)
- `app.py` — `_render_feature_selector()` → `_render_scanning_table()`로 교체 (토글 버튼 → `st.dataframe` 복수 행 선택)
- `app.py` — `_apply_preprocess_plan()`에서 전처리 완료 후 자동으로 `run_threshold_scanning()` 실행
- `app.py` — `_parse_feature_request()` → `_parse_feature_selections()`로 교체. 복수 피처별 독립 조건/임계값 지원. 반환: `list[dict]`
- `app.py` — SHOWING_FEATURES 핸들러: 예측 지표 재계산 + scatter plot 생성·저장
- `app.py`/`test_app.py` — COMPLETED 상태에서 scatter plot 이미지 렌더링
- `llm/prompts.py` — `_build_combination_prompt()` selections 배열 형식으로 변경

**새로 추가된 인터페이스:**
```python
# schema.py
SCANNING_THRESHOLDS = [round(i * 0.1, 1) for i in range(1, 10)]  # [0.1 ~ 0.9]
SCANNING_CONDITIONS = [">=", "<="]

# pipeline/threshold_scanning.py
def run_threshold_scanning(
    df: pd.DataFrame,
    features: list[str],
    target_col: str,
    thresholds: list[float] | None = None,
    conditions: list[str] | None = None,
) -> pd.DataFrame:
    """각 피처/임계값/조건 조합별 성능 지표 계산.
    Returns: DataFrame [feature, threshold, condition, roi, screen_rate, drop_rate, f1_score]
    """

def compute_prediction_metrics(
    df: pd.DataFrame,
    target_col: str,
    selections: list[dict],  # [{"feature": str, "condition": str, "threshold": float}]
) -> dict:
    """선택된 조건 조합으로 예측 지표 재계산.
    Returns: {"total", "screened", "screen_rate", "drop_rate", "roi", "f1_score"}
    """

def plot_feature_scatter(
    df: pd.DataFrame,
    target_col: str,
    selections: list[dict],
) -> bytes | None:
    """matplotlib scatter plot (PNG bytes). 1~3 피처만 지원, 4+ → None.
    이 함수는 Claude가 구현 완료 — 루코드 수정 불필요.
    """

# app.py
def _parse_feature_selections(text: str) -> list[dict]:
    """사용자 입력에서 피처별 조건/임계값 조합 목록 추출.
    Returns: [{"feature": str, "threshold": float|None, "condition": str|None}, ...]
    """
```

**데이터 흐름:**
```
_apply_preprocess_plan() 완료
  → run_threshold_scanning(result_df, AVAILABLE_FEATURES, TARGET_COLUMN)
  → session.set_dataframe("scanning_result", scanning_df)
  → SHOWING_FEATURES 상태 진입
  → _render_scanning_table() — st.dataframe(multi-row 선택)
  → 행 선택 → "col_3 >= 0.7, col_4 <= 0.3 조건으로 예측해줘" 자동 채움
  → handle_user_input()
  → _parse_feature_selections() → [{"feature","threshold","condition"}, ...]
  → compute_prediction_metrics() → screen_rate, drop_rate, roi, f1_score
  → plot_feature_scatter() → PNG bytes (1D/2D/3D scatter)
  → COMPLETED 상태 → scatter plot 이미지 렌더링
```

**루코드 구현 대상 (TODO):**

| 함수 | 파일 | 현재 상태 | 구현 내용 |
|------|------|----------|----------|
| `run_threshold_scanning()` | `pipeline/threshold_scanning.py` | mock: `numpy.random`으로 랜덤 값 반환 | 실제 성능 지표 계산 (tp/fp/fn 기반) |
| `compute_prediction_metrics()` | `pipeline/threshold_scanning.py` | mock: `numpy.random`으로 랜덤 값 반환 | 복수 조건 AND 조합으로 실제 지표 계산 |

**구현 시 참조할 코드:**
```python
# run_threshold_scanning 실제 구현 예시
def run_threshold_scanning(df, features, target_col, thresholds=None, conditions=None):
    if thresholds is None:
        thresholds = schema.SCANNING_THRESHOLDS
    if conditions is None:
        conditions = schema.SCANNING_CONDITIONS

    rows = []
    for feat in features:
        for thresh in thresholds:
            for cond in conditions:
                if cond == ">=":
                    mask = df[feat] >= thresh
                else:
                    mask = df[feat] <= thresh

                y = df[target_col]
                predicted = mask.astype(int)

                tp = ((predicted == 1) & (y == 1)).sum()
                fp = ((predicted == 1) & (y == 0)).sum()
                fn = ((predicted == 0) & (y == 1)).sum()

                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                screen_rate = predicted.sum() / len(df)
                drop_rate = fp / predicted.sum() if predicted.sum() > 0 else 0
                roi = recall / screen_rate if screen_rate > 0 else 0

                rows.append({
                    "feature": feat, "threshold": thresh, "condition": cond,
                    "roi": round(roi, 3), "screen_rate": round(screen_rate, 3),
                    "drop_rate": round(drop_rate, 3), "f1_score": round(f1, 3),
                })

    return pd.DataFrame(rows).sort_values("f1_score", ascending=False).reset_index(drop=True)

# compute_prediction_metrics 실제 구현 예시
def compute_prediction_metrics(df, target_col, selections):
    # 복수 조건을 AND로 결합
    combined_mask = pd.Series(True, index=df.index)
    for sel in selections:
        if sel["condition"] == ">=":
            combined_mask &= df[sel["feature"]] >= sel["threshold"]
        else:
            combined_mask &= df[sel["feature"]] <= sel["threshold"]

    y = df[target_col]
    predicted = combined_mask.astype(int)
    tp = ((predicted == 1) & (y == 1)).sum()
    fp = ((predicted == 1) & (y == 0)).sum()
    fn = ((predicted == 0) & (y == 1)).sum()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    screened = predicted.sum()
    screen_rate = screened / len(df) if len(df) > 0 else 0
    drop_rate = fp / screened if screened > 0 else 0
    roi = recall / screen_rate if screen_rate > 0 else 0

    return {
        "total": len(df), "screened": int(screened),
        "screen_rate": round(screen_rate, 4), "drop_rate": round(drop_rate, 4),
        "roi": round(roi, 3), "f1_score": round(f1, 3),
    }
```

**루코드 구현 시 주의사항:**
- `run_threshold_scanning()`: 반환 컬럼 `[feature, threshold, condition, roi, screen_rate, drop_rate, f1_score]` 유지 — `_render_scanning_table()`이 의존
- `compute_prediction_metrics()`: 반환 딕셔너리 키 `[total, screened, screen_rate, drop_rate, roi, f1_score]` 유지 — `handle_user_input()`이 의존
- `plot_feature_scatter()`는 Claude가 구현 완료 (matplotlib). 루코드는 수정 불필요
- `selections` 파라미터: `[{"feature": str, "condition": ">="/"<=", "threshold": float}]` 형식
- 복수 조건은 AND로 결합하여 지표 계산
- `df[target_col]`은 0/1 이진값 (Y값). `schema.TARGET_COLUMN`("y")을 사용

### 2026-05-08: MAP 경향성 분석 파이프라인 구현

**변경 사항:**
- `pipeline/map_trend.py` — TODO 스캐폴딩에서 전체 mock 구현으로 교체 (13개 함수)
- `schema.py` — MAP 워크플로우 전용 상수 추가
- `app.py` — MAP 핸들러 추가 (`_handle_map_query`, `_handle_map_prev_process_decision`)
- `app.py` — 파라미터 추출에 `lot_no` 지원 추가
- `ui/chat.py` — MAP 상태 라벨 + 동적 사이드바 스테이지
- `test_app.py` — MAP 테스트 시나리오 + 동적 사이드바

**schema.py 추가 상수:**
```python
MAP_REQUIRED_PARAMS = [
    {"key": "lot_cd", "label": "LOT 코드", "type": "text"},
    {"key": "lot_no", "label": "LOT 번호", "type": "text"},
    {"key": "oper", "label": "공정(OPER)", "type": "text"},
    {"key": "from_date", "label": "시작일", "type": "date", "format": "YYYYMMDD"},
    {"key": "end_date", "label": "종료일", "type": "date", "format": "YYYYMMDD"},
]
MAP_FAIL_CONCENTRATION_THRESHOLD = 10
MAP_DEFAULT_LAYOUT = [[0,0,1,0,0],[0,1,1,1,0],[1,1,1,1,1],[0,1,1,1,0],[0,0,1,0,0]]
MAP_LAYOUT_X_OFFSET = 11
MAP_LAYOUT_Y_OFFSET = 11
MAP_LAYOUT_OFFSET_MODE = "subtract"
MAP_LAYOUT_BY_LOT_CD: dict[str, list[list[int]]] = {}  # LOT별 레이아웃 오버라이드
PREV_PROCESS_MERGE_KEYS = ["run_id", "wafer_id", "die_x", "die_y"]
PREV_PROCESS_OPTIONS = [...]  # 전공정 옵션 (table, columns, merge_keys)
MAP_FEATURE_SIMILARITY_NORMALIZATION = "zscore"
MAP_FEATURE_SIMILARITY_TOP_N = 10
```

**pipeline/map_trend.py 함수 목록:**

| 함수 | 현재 상태 | 구현 내용 |
|------|----------|----------|
| `query_lot_fail_summary(params)` | mock: 3 run × 5 wafer 랜덤 | 실제 DB 조회 → run/wafer별 fail count 집계 |
| `get_concentration_candidates(df)` | 구현 완료 | threshold 이상 fail count인 wafer 필터 |
| `build_fail_summary_message(df, candidates)` | 구현 완료 | 마크다운 테이블 빌더 |
| `parse_wafer_selection(text, candidates, df)` | 구현 완료 | "전체", 번호, run/wafer ID 파싱 |
| `query_wafer_map_detail(params, wafers)` | mock: 랜덤 die 좌표 | 실제 DB 조회 → die별 pass/fail 데이터 |
| `classify_pattern(df)` | 구현 완료 | edge/center/random 패턴 판정 |
| `build_aggregate_fail_map(df)` | 구현 완료 | wafer별 fail을 die 좌표별로 합산 |
| `plot_wafer_map(df, wafer_id, run_id, layout)` | 구현 완료 | matplotlib wafer map (green/red/gray) |
| `plot_aggregate_map(agg_df)` | 구현 완료 | 집계 fail map heatmap |
| `build_map_results_message(df, wafers, pattern)` | 구현 완료 | 분석 결과 마크다운 |
| `parse_prev_process_selection(text)` | 구현 완료 | 전공정 옵션 선택 파싱 |
| `merge_prev_process_data(map_df, options)` | mock: 랜덤 컬럼 | 실제 DB 조회 + die 좌표 기준 merge |
| `compute_feature_similarity(df, features)` | 구현 완료 | masked Pearson + cosine → total score |
| `build_prev_process_results_message(sim_df)` | 구현 완료 | feature ranking 마크다운 |

**루코드 구현 대상 (TODO):**

| 함수 | 구현 내용 |
|------|----------|
| `query_lot_fail_summary()` | `schema.MAP_DB_TABLE` 조회, `schema.MAP_FAIL_COLUMN` 기준 fail count 집계 |
| `query_wafer_map_detail()` | die 좌표별 pass/fail 실제 데이터 조회, `schema.MAP_LAYOUT_X_OFFSET`/`Y_OFFSET` 적용 |
| `merge_prev_process_data()` | `schema.PREV_PROCESS_OPTIONS[i]["table"]` 조회, `PREV_PROCESS_MERGE_KEYS` 기준 merge |

**구현 시 참조할 코드:**
```python
# query_lot_fail_summary 실제 구현 예시
def query_lot_fail_summary(params: dict) -> pd.DataFrame:
    wrapper = SDKWrapper()
    query = f"""
    SELECT run_id, wafer_id,
           COUNT(*) as total_die,
           SUM(CASE WHEN {schema.MAP_FAIL_COLUMN} IN ({schema.MAP_FAIL_VALUES}) THEN 1 ELSE 0 END) as fail_count
    FROM {schema.MAP_DB_TABLE}
    WHERE lot_cd = '{params["lot_cd"]}'
      AND lot_no = '{params["lot_no"]}'
      AND oper = '{params["oper"]}'
      AND date BETWEEN '{params["from_date"]}' AND '{params["end_date"]}'
    GROUP BY run_id, wafer_id
    """
    return wrapper.execute_query(query)

# query_wafer_map_detail 실제 구현 예시
def query_wafer_map_detail(params: dict, wafers: list[dict]) -> pd.DataFrame:
    wafer_filter = " OR ".join([
        f"(run_id='{w['run_id']}' AND wafer_id='{w['wafer_id']}')"
        for w in wafers
    ])
    query = f"""
    SELECT run_id, wafer_id,
           die_x - {schema.MAP_LAYOUT_X_OFFSET} as die_x,
           die_y - {schema.MAP_LAYOUT_Y_OFFSET} as die_y,
           {schema.MAP_FAIL_COLUMN} as fail
    FROM {schema.MAP_DB_TABLE}
    WHERE ({wafer_filter})
    """
    return wrapper.execute_query(query)
```

**루코드 구현 시 주의사항:**
- `schema.py`의 MAP 상수는 placeholder. 실제 테이블명/컬럼명/fail 판정 기준으로 교체
- `MAP_DEFAULT_LAYOUT`은 5x5 mock. 실제 레이아웃(die 유효 위치 마스크)으로 교체
- `MAP_LAYOUT_X_OFFSET`/`Y_OFFSET`은 DB die 좌표 → 0-indexed 변환용
- `PREV_PROCESS_OPTIONS`의 `table`/`columns`/`merge_keys`를 실제 값으로 교체
- `classify_pattern()`의 edge/center 기준값(0.65/0.35)은 도메인에 맞게 조정 가능
- `compute_feature_similarity()`의 정규화 방식(`zscore`)은 `schema.MAP_FEATURE_SIMILARITY_NORMALIZATION`으로 설정
- wafer map plot 색상: missing=lightgray, normal=limegreen, fail=red — 변경 시 `plot_wafer_map()` 수정
- conventional 워크플로우 코드는 일절 변경 없음

### 2026-05-08: 수율 경향성 분석 파이프라인 + schema 설정 추가

**변경 사항:**
- `pipeline/yield_trend.py` 신규 생성 — 수율 경향성 분석 파이프라인 (12개 함수)
- `schema.py` — 수율 워크플로우 전용 상수 추가
- `app.py` — 수율 핸들러 추가 (`_handle_yield_loading`, `_handle_yield_request`)

**schema.py 추가 상수:**
```python
YIELD_REQUIRED_PARAMS = [
    {"key": "lot_cd", "label": "LOT 코드", "type": "text"},
]
YIELD_OPTIONAL_PARAMS = [
    {"key": "week", "label": "조회 주차 (예: 2025-W20)", "type": "text"},
    {"key": "oper", "label": "공정(OPER)", "type": "text"},
    {"key": "from_date", "label": "시작일 (week 내 필터)", "type": "date", "format": "YYYYMMDD"},
    {"key": "end_date", "label": "종료일 (week 내 필터)", "type": "date", "format": "YYYYMMDD"},
]
YIELD_TABLE = "schema_name.yield_table"  # TODO: 실제 테이블명
YIELD_LOT_COLUMN = "lot_cd"
YIELD_OPER_COLUMN = "oper"
YIELD_DATE_COLUMN = "test_date"
YIELD_CAT_COLUMN = "cat"
YIELD_IN_COLUMN = "in_count"    # 투입 수
YIELD_OUT_COLUMN = "out_count"  # 양품 수
YIELD_PARQUET_DIR = "data/yield"  # parquet 캐싱 경로
```

**pipeline/yield_trend.py 함수 목록:**

| 함수 | 현재 상태 | 구현 내용 |
|------|----------|----------|
| `resolve_weeks(params)` | 구현 완료 | week 결정: 명시 week / 날짜→week / 기본 전주 |
| `get_parquet_path(lot_cd, week)` | 구현 완료 | `{YIELD_PARQUET_DIR}/{lot_cd}/week_{YYYYWNN}.parquet` |
| `load_or_query(params, weeks)` | 구현 완료 | parquet 존재 시 로드, 없으면 DB 조회 + 저장 |
| `query_yield_data(params, week)` | mock: 랜덤 in/out 생성 | 실제 DB 조회 → lot_cd+week 기준 수율 데이터 |
| `save_parquet(df, lot_cd, week)` | 구현 완료 | DataFrame → parquet 저장 |
| `filter_by_date(df, from_date, end_date)` | 구현 완료 | 날짜 범위 필터링 |
| `preprocess_yield(df)` | 구현 완료 | 공정별 수율 + 공정-cat별 불량률 계산 |
| `build_overview_message(oper_summary, cat_detail)` | 구현 완료 | 마크다운 요약 테이블 |
| `parse_detail_request(text)` | 구현 완료 | "전체"/"공정"/"cat"/"종료" 파싱 |
| `build_detail_view(oper_summary, cat_detail, request)` | 구현 완료 | 필터링된 trend 테이블 |

**Week 기반 조회 + Parquet 캐싱:**
- 데이터는 week 단위로 조회 (YYYY-WNN 형식)
- 미지정 시 전주를 기본값으로 사용
- 조회 결과를 `{YIELD_PARQUET_DIR}/{lot_cd}/week_{YYYYWNN}.parquet`에 캐싱
- 동일 lot_cd+week 재조회 시 parquet 로드 (DB 조회 skip)
- from_date/end_date 지정 시 해당 날짜가 속한 week들을 로드 후 필터

**Mock 데이터 구조:**
```
lot_cd | oper | test_date | cat  | in_count | out_count
LOT001 | OP1  | 20250505  | cat1 | 1000     | 980
LOT001 | OP1  | 20250505  | cat2 | 1000     | 995
...
```

**루코드 구현 대상 (TODO):**

| 함수 | 구현 내용 |
|------|----------|
| `query_yield_data()` | `schema.YIELD_TABLE` 조회, week 기간 기준 SQL, 공정 미지정 시 전체 공정 |
| `save_parquet()` | 저장 경로를 S3/NFS로 변경 시 wrapper 수정 |

**구현 시 참조할 코드:**
```python
# query_yield_data 실제 구현 예시
def query_yield_data(params: dict, week: str) -> pd.DataFrame:
    wrapper = SDKWrapper()
    start, end = _week_to_date_range(week)
    oper_filter = f"AND {schema.YIELD_OPER_COLUMN} = '{params['oper']}'" if params.get("oper") else ""
    query = f"""
    SELECT {schema.YIELD_LOT_COLUMN}, {schema.YIELD_OPER_COLUMN},
           {schema.YIELD_DATE_COLUMN}, {schema.YIELD_CAT_COLUMN},
           {schema.YIELD_IN_COLUMN}, {schema.YIELD_OUT_COLUMN}
    FROM {schema.YIELD_TABLE}
    WHERE {schema.YIELD_LOT_COLUMN} = '{params["lot_cd"]}'
      AND {schema.YIELD_DATE_COLUMN} BETWEEN '{start}' AND '{end}'
      {oper_filter}
    """
    return wrapper.execute_query(query)
```

**루코드 구현 시 주의사항:**
- `schema.py`의 YIELD 상수는 placeholder. 실제 테이블명/컬럼명으로 교체
- `YIELD_PARQUET_DIR`은 로컬 경로. S3/NFS 사용 시 경로 및 저장 로직 변경
- `preprocess_yield()`의 수율 계산 로직(`out/in`)은 도메인에 맞게 조정 가능
- `OPER_OPTIONS`가 빈 리스트면 mock에서 `["OP1", "OP2", "OP3"]` 폴백 사용
- conventional, MAP 워크플로우 코드는 일절 변경 없음
