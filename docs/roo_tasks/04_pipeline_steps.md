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
