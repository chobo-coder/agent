# Task 07: Testing

## Goal
단위/통합/E2E 테스트 작성, CI 파이프라인 준비

---

## 현재 상태

- `tests/test_state_machine.py`: 10개 통과
- `tests/test_orchestrator.py`: 6개 통과 (파서 테스트)
- `tests/test_pipeline.py`: streamlit import 의존성으로 CI에서만 실행 가능

---

## 테스트 전략

### 레이어별 테스트 범위

| 레이어 | 테스트 유형 | Mock 대상 | 커버리지 목표 |
|--------|-----------|----------|-------------|
| state_machine | 단위 | 없음 | 100% |
| parser | 단위 | 없음 | 95% |
| pipeline handlers | 단위 | SDK, S3 wrapper | 90% |
| orchestrator | 통합 | LLM, handlers | 80% |
| UI | 수동 E2E | - | 시나리오 기반 |

---

## 구현 상세

### 7-1. conftest.py (공통 fixtures)

```python
# tests/conftest.py

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch


@pytest.fixture
def sample_df():
    """기본 테스트 DataFrame"""
    np.random.seed(42)
    n = 50
    return pd.DataFrame({
        "product_name": ["ProductA"] * n,
        "date": pd.date_range("2024-01-01", periods=n),
        "metric_a": np.random.randn(n),
        "metric_b": np.random.rand(n) * 100,
        "metric_c": np.random.randint(0, 10, n),
        "category": np.random.choice(["A", "B", "C"], n),
    })


@pytest.fixture
def sample_df_with_nulls(sample_df):
    """결측치가 포함된 DataFrame"""
    df = sample_df.copy()
    df.loc[0:4, "metric_a"] = np.nan
    df.loc[10:12, "metric_b"] = np.nan
    return df


@pytest.fixture
def mock_session(sample_df):
    """SessionManager mock"""
    session = MagicMock()
    session.get_dataframe.return_value = sample_df
    session.get_metadata.return_value = None
    session.current_state = MagicMock()
    return session


@pytest.fixture
def mock_llm_client():
    """LLMClient mock"""
    client = MagicMock()
    client.complete.return_value = '{"product": "ProductA"}'
    return client
```

### 7-2. 상태 머신 테스트 확장

`tests/test_state_machine.py`에 추가:

```python
class TestStateMachineExtended:
    """Task 02에서 추가된 기능 테스트"""

    def test_history_tracking(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
        assert len(sm.history) == 3
        assert sm.history == [
            WorkflowState.IDLE,
            WorkflowState.QUERYING_DATA,
            WorkflowState.SHOWING_QUERY_RESULTS,
        ]

    def test_rollback_single(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.rollback()
        assert sm.state == WorkflowState.IDLE
        assert len(sm.history) == 1

    def test_rollback_at_idle(self):
        sm = StateMachine()
        sm.rollback()  # IDLE에서 rollback은 무시
        assert sm.state == WorkflowState.IDLE

    def test_progress_at_start(self):
        sm = StateMachine()
        assert sm.progress_percent == 0.0

    def test_progress_at_middle(self):
        sm = StateMachine()
        # IDLE(0) → halfway 정도
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
        sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
        sm.transition_to(WorkflowState.LOADING_PARQUET)
        sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
        assert 0.3 < sm.progress_percent < 0.5

    def test_progress_at_end(self):
        sm = StateMachine()
        # 전체 경로 순회
        for state in list(WorkflowState)[1:]:  # IDLE 제외
            if sm.can_transition_to(state):
                sm.transition_to(state)
        assert sm.progress_percent == 1.0

    def test_serialization_roundtrip(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)

        data = sm.to_dict()
        sm2 = StateMachine.from_dict(data)

        assert sm2.state == sm.state
        assert sm2.history == sm.history

    def test_serialization_format(self):
        sm = StateMachine()
        data = sm.to_dict()
        assert data == {"state": "IDLE", "history": ["IDLE"]}
```

### 7-3. 파서 테스트 확장

`tests/test_orchestrator.py`에 추가:

```python
class TestResponseParserExtended:
    def setup_method(self):
        self.parser = ResponseParser()

    def test_json_in_markdown_code_block(self):
        response = '```json\n{"product": "TestProduct"}\n```'
        assert self.parser.extract_product(response) == "TestProduct"

    def test_json_in_plain_code_block(self):
        response = '```\n{"product": "TestProduct"}\n```'
        assert self.parser.extract_product(response) == "TestProduct"

    def test_nested_json(self):
        response = '{"items": ["a"], "params": {"strategy": "mean", "threshold": 1.5}}'
        result = self.parser._extract_json(response)
        assert result["params"]["strategy"] == "mean"
        assert result["params"]["threshold"] == 1.5

    def test_json_with_surrounding_text(self):
        response = """분석 결과입니다.

{"features": ["col_a", "col_b"], "threshold": 0.8}

위 설정으로 진행하겠습니다."""
        assert self.parser.extract_features(response) == ["col_a", "col_b"]
        assert self.parser.extract_threshold(response) == 0.8

    def test_korean_in_json(self):
        response = '{"product": "테스트제품", "reason": "사용자 요청"}'
        assert self.parser.extract_product(response) == "테스트제품"

    def test_boolean_parsing(self):
        from core.state_machine import WorkflowState
        response = '{"load_additional": false, "reason": "충분합니다"}'
        result = self.parser.parse_decision(WorkflowState.SHOWING_QUERY_RESULTS, response)
        assert result["load_additional"] is False

    def test_multiple_json_takes_first(self):
        response = '{"a": 1} some text {"b": 2}'
        result = self.parser._extract_json(response)
        assert "a" in result

    def test_empty_string(self):
        assert self.parser._extract_json("") == {}

    def test_preprocess_items_parsing(self):
        from core.state_machine import WorkflowState
        response = '{"items": ["missing_values", "scaling"], "params": {"missing_strategy": "mean"}}'
        result = self.parser.parse_decision(WorkflowState.SHOWING_DATA_OVERVIEW, response)
        assert "missing_values" in result["items"]
        assert result["params"]["missing_strategy"] == "mean"
```

### 7-4. 파이프라인 테스트 확장

`tests/test_pipeline.py`에 추가:

```python
class TestPreprocessingFull:
    """전처리 모든 옵션 테스트"""

    def test_missing_mean_fill(self, sample_df_with_nulls):
        handler = PreprocessingHandler()
        result = handler._handle_missing(sample_df_with_nulls, {"missing_strategy": "mean"})
        assert result["metric_a"].isnull().sum() == 0

    def test_missing_median_fill(self, sample_df_with_nulls):
        handler = PreprocessingHandler()
        result = handler._handle_missing(sample_df_with_nulls, {"missing_strategy": "median"})
        assert result["metric_b"].isnull().sum() == 0

    def test_missing_drop(self, sample_df_with_nulls):
        handler = PreprocessingHandler()
        result = handler._handle_missing(sample_df_with_nulls, {"missing_strategy": "drop"})
        assert result.isnull().sum().sum() == 0
        assert len(result) < len(sample_df_with_nulls)

    def test_outlier_iqr(self, sample_df):
        handler = PreprocessingHandler()
        # 극단값 추가
        df = sample_df.copy()
        df.loc[0, "metric_a"] = 1000.0
        result = handler._handle_outliers(df, {"outlier_method": "iqr"})
        assert len(result) < len(df)

    def test_scaling_output_range(self, sample_df):
        handler = PreprocessingHandler()
        numeric_df = sample_df.select_dtypes(include=[np.number])
        result = handler._handle_scaling(numeric_df, {"scaling_method": "minmax"})
        assert result.max().max() <= 1.0 + 1e-10
        assert result.min().min() >= 0.0 - 1e-10

    def test_encoding_removes_categoricals(self, sample_df):
        handler = PreprocessingHandler()
        result = handler._handle_encoding(sample_df, {})
        assert "category" not in result.columns
        assert any("category_" in col for col in result.columns)

    def test_feature_selection(self, sample_df):
        handler = PreprocessingHandler()
        result = handler._handle_feature_selection(
            sample_df, {"keep_columns": ["metric_a", "metric_b"]}
        )
        assert list(result.columns) == ["metric_a", "metric_b"]


class TestPredictionScores:
    """예측 점수 유효성 테스트"""

    def test_scores_in_0_1_range(self, sample_df):
        handler = PredictionHandler()
        scores = handler._predict(sample_df, ["metric_a", "metric_b"], 0.5)
        assert scores.min() >= 0.0
        assert scores.max() <= 1.0

    def test_empty_features_uses_all_numeric(self, sample_df):
        handler = PredictionHandler()
        scores = handler._predict(sample_df, [], 0.5)
        assert len(scores) == len(sample_df)

    def test_nonexistent_feature_graceful(self, sample_df):
        handler = PredictionHandler()
        scores = handler._predict(sample_df, ["nonexistent_col"], 0.5)
        # 숫자형이 아닌 컬럼만 남으면 zeros
        assert len(scores) == len(sample_df)


class TestFeatureAnalysisOutput:
    """피처 분석 출력 검증"""

    def test_correlation_matrix_square(self, mock_session):
        handler = FeatureAnalysisHandler()
        result = handler.execute(mock_session)
        corr = result.dataframes["correlation_matrix"]
        assert corr.shape[0] == corr.shape[1]

    def test_correlation_values_range(self, mock_session):
        handler = FeatureAnalysisHandler()
        result = handler.execute(mock_session)
        corr = result.dataframes["correlation_matrix"]
        assert corr.min().min() >= -1.0
        assert corr.max().max() <= 1.0

    def test_figure_generated(self, mock_session):
        handler = FeatureAnalysisHandler()
        result = handler.execute(mock_session)
        assert len(result.figures) == 1
```

### 7-5. Orchestrator 통합 테스트

```python
# tests/test_integration.py (신규)

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from core.orchestrator import Orchestrator, StepResult
from core.state_machine import WorkflowState, StateMachine


class TestOrchestratorIntegration:
    """Orchestrator 통합 테스트 (LLM + Handler mock)"""

    @pytest.fixture
    def orchestrator(self):
        session = MagicMock()
        session.state_machine = StateMachine()
        session.get_metadata.return_value = None
        session.get_dataframe.return_value = None

        with patch("core.orchestrator.LLMClient") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.complete.return_value = '{"product": "TestProduct"}'
            mock_llm_cls.return_value = mock_llm

            orch = Orchestrator(session)
            orch.llm = mock_llm
            return orch

    def test_start_workflow_transitions_to_querying(self, orchestrator):
        orchestrator.llm.complete.return_value = '{"product": "ProductA"}'
        # DataQueryHandler mock
        mock_handler = MagicMock()
        mock_handler.execute.return_value = StepResult(
            dataframes={"query_result": MagicMock()},
            summary="조회 완료",
        )
        orchestrator._handlers[WorkflowState.QUERYING_DATA] = mock_handler

        result = orchestrator.handle_input("ProductA 분석해줘")
        assert orchestrator.session.state_machine.state in [
            WorkflowState.QUERYING_DATA,
            WorkflowState.SHOWING_QUERY_RESULTS,
        ]

    def test_error_triggers_rollback(self, orchestrator):
        orchestrator.session.state_machine.transition_to(WorkflowState.QUERYING_DATA)
        orchestrator.session.state_machine.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)

        # LLM이 정상 응답하지만 handler가 에러
        orchestrator.llm.complete.return_value = '{"load_additional": true}'

        mock_handler = MagicMock()
        mock_handler.execute.side_effect = RuntimeError("DB connection failed")
        orchestrator._handlers[WorkflowState.LOADING_PARQUET] = mock_handler

        result = orchestrator.handle_input("추가 데이터 가져와")
        assert result.metadata.get("error") is True

    def test_llm_error_keeps_state(self, orchestrator):
        orchestrator.session.state_machine.transition_to(WorkflowState.QUERYING_DATA)
        orchestrator.session.state_machine.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)

        from llm.client import LLMError
        orchestrator.llm.complete.side_effect = LLMError("timeout")

        original_state = orchestrator.session.state_machine.state
        result = orchestrator.handle_input("추가 로딩")
        assert result.metadata.get("error") is True
        assert orchestrator.session.state_machine.state == original_state
```

### 7-6. pytest 설정

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    integration: marks tests that require full setup
    slow: marks tests as slow
```

### 7-7. CI 실행 커맨드

```bash
# 단위 테스트만 (빠른 피드백)
pytest tests/test_state_machine.py tests/test_orchestrator.py -v

# 파이프라인 포함 (streamlit 설치 필요)
pytest tests/ -v --ignore=tests/test_integration.py

# 전체 (통합 테스트 포함)
pytest tests/ -v

# 커버리지
pytest tests/ --cov=core --cov=llm --cov=pipeline --cov-report=term-missing
```

---

## E2E 수동 테스트 시나리오

### 시나리오 1: Happy Path (전체 워크플로우)

| # | 사용자 입력 | 기대 결과 |
|---|-----------|----------|
| 1 | "ProductA 분석해줘" | SQL 조회 → 결과 테이블 표시 |
| 2 | "추가 데이터도 로딩해줘" | S3 로딩 → 머지 결과 |
| 3 | "결측치 제거하고 스케일링" | 전처리 실행 → 결과 통계 |
| 4 | "metric_a, metric_b로 0.7" | 예측 결과 표시 |

### 시나리오 2: 스킵 경로

| # | 사용자 입력 | 기대 결과 |
|---|-----------|----------|
| 1 | "ProductB 분석" | SQL 조회 |
| 2 | "이 정도면 충분해" | S3 건너뛰고 오버뷰 표시 |
| 3 | "전부 다 전처리" | 모든 항목 적용 |
| 4 | "상위 3개 피처로 0.5" | top_3 해석 → 예측 |

### 시나리오 3: 에러 복구

| # | 상황 | 기대 결과 |
|---|------|----------|
| 1 | LLM API 타임아웃 | "다시 시도" 메시지, 상태 유지 |
| 2 | DB 연결 실패 | 이전 상태로 롤백, 안내 메시지 |
| 3 | 빈 데이터 반환 | "데이터가 없습니다" 메시지 |

---

## 파일 체크리스트

| 파일 | 액션 | 설명 |
|------|------|------|
| `tests/conftest.py` | 신규 생성 | 공통 fixtures |
| `tests/test_state_machine.py` | 수정 | 8개 테스트 추가 |
| `tests/test_orchestrator.py` | 수정 | 9개 테스트 추가 |
| `tests/test_pipeline.py` | 수정 | 13개 테스트 추가 |
| `tests/test_integration.py` | 신규 생성 | Orchestrator 통합 3개 |
| `pytest.ini` | 신규 생성 | pytest 설정 |

---

## 완료 기준

- [ ] `pytest tests/` 전체 통과 (약 50개 테스트)
- [ ] state_machine 커버리지 100%
- [ ] parser 커버리지 95%+
- [ ] pipeline handlers 커버리지 90%+
- [ ] Malformed 입력 (빈 문자열, None, 잘못된 JSON)에서 크래시 없음
- [ ] E2E 시나리오 3개 수동 통과
- [ ] CI에서 `pytest tests/ -v` 실행 가능한 환경 구성
