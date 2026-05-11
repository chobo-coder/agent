# 로깅 구현 계획서

## 개요

프로젝트 전반에 구조화된 로깅을 추가하여 디버깅과 운영 모니터링을 지원한다.
Python 표준 `logging` 모듈을 사용하며, 모듈별 로거를 생성한다.

## 로거 구조

```python
# config.py 또는 logging_config.py에서 초기화
import logging

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
LOG_LEVEL = logging.DEBUG  # 개발 중. 운영 시 INFO로 변경

logging.basicConfig(format=LOG_FORMAT, level=LOG_LEVEL)
```

### 모듈별 로거

| 로거 이름 | 사용 위치 | 목적 |
|-----------|----------|------|
| `agent.pipeline` | `pipeline/*.py` | 파이프라인 실행 추적 |
| `agent.sql` | `pipeline/data_query.py`, `wrappers/sdk_wrapper.py` | SQL 쿼리 추적 |
| `agent.llm` | `llm/client.py`, `llm/parser.py` | LLM 프롬프트/응답 추적 |
| `agent.fsm` | `core/state_machine.py` | 상태 전이 추적 |
| `agent.data` | `pipeline/*.py`, `wrappers/*.py` | 데이터 품질 검증 |
| `agent.wrapper` | `wrappers/sdk_wrapper.py`, `wrappers/s3_wrapper.py` | 외부 시스템 호출 추적 |
| `agent.session` | `core/session.py` | 세션 상태 변경 추적 |
| `agent.app` | `app.py` | 사용자 입력/UI 흐름 추적 |

각 모듈 파일 상단에서:
```python
import logging
logger = logging.getLogger("agent.pipeline")  # 모듈에 맞게 변경
```

---

## 1. 파이프라인 로깅 (`agent.pipeline`)

### 대상 파일
- `pipeline/data_query.py`
- `pipeline/data_loader.py`
- `pipeline/preprocessing.py`
- `pipeline/eda.py`
- `pipeline/feature_analysis.py`
- `pipeline/prediction.py`
- `pipeline/map_trend.py`
- `pipeline/threshold_scanning.py`
- `pipeline/preprocess_preview.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 함수 진입 | DEBUG | 함수명, 입력 파라미터 (큰 DataFrame은 shape만) |
| 함수 완료 | INFO | 함수명, 실행 시간, 출력 shape/타입 |
| 에러 발생 | ERROR | 함수명, 에러 메시지, traceback |

### 구현 패턴

```python
import time
import logging

logger = logging.getLogger("agent.pipeline")

def query_conventional(params: dict) -> pd.DataFrame:
    logger.debug(f"query_conventional 시작 | params={params}")
    start = time.time()
    try:
        df = _실제_쿼리_로직(params)
        elapsed = time.time() - start
        logger.info(f"query_conventional 완료 | {elapsed:.2f}s | shape={df.shape}")
        return df
    except Exception as e:
        logger.error(f"query_conventional 실패 | {e}", exc_info=True)
        raise
```

### (선택) 데코레이터 패턴

반복을 줄이려면 공통 데코레이터를 사용할 수 있다:

```python
# utils/logging_utils.py
import time
import logging
from functools import wraps

def log_pipeline(func):
    """파이프라인 함수에 진입/완료/에러 로깅을 자동 추가"""
    logger = logging.getLogger("agent.pipeline")

    @wraps(func)
    def wrapper(*args, **kwargs):
        # DataFrame은 shape만, 나머지는 그대로 로깅
        safe_kwargs = {
            k: f"DataFrame{v.shape}" if hasattr(v, 'shape') else v
            for k, v in kwargs.items()
        }
        logger.debug(f"{func.__name__} 시작 | {safe_kwargs}")
        start = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            result_info = f"shape={result.shape}" if hasattr(result, 'shape') else type(result).__name__
            logger.info(f"{func.__name__} 완료 | {elapsed:.2f}s | {result_info}")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} 실패 | {e}", exc_info=True)
            raise
    return wrapper

# 사용 예시
@log_pipeline
def query_conventional(params: dict) -> pd.DataFrame:
    ...
```

---

## 2. SQL 로깅 (`agent.sql`)

### 대상 파일
- `pipeline/data_query.py`
- `wrappers/sdk_wrapper.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 쿼리 실행 전 | DEBUG | SQL 전문, 바인드 파라미터 |
| 쿼리 완료 | INFO | 실행 시간, 반환 row 수 |
| 쿼리 실패 | ERROR | SQL 전문, 에러 메시지 |

### 구현 패턴

```python
logger = logging.getLogger("agent.sql")

def execute_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    logger.debug(f"SQL 실행\n{sql}\nparams={params}")
    start = time.time()
    try:
        df = _sdk_실행(sql, params)
        elapsed = time.time() - start
        logger.info(f"SQL 완료 | {elapsed:.2f}s | rows={len(df)}")
        return df
    except Exception as e:
        logger.error(f"SQL 실패 | {e}\nSQL: {sql}", exc_info=True)
        raise
```

### 주의사항
- 민감한 파라미터(비밀번호, 토큰 등)는 마스킹 처리
- 쿼리가 길 경우 처음 500자만 로깅하는 옵션 고려

---

## 3. LLM 프롬프트/응답 로깅 (`agent.llm`)

### 대상 파일
- `llm/client.py`
- `llm/parser.py`
- `llm/prompts.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 프롬프트 생성 | DEBUG | 프롬프트 전문 (system + user) |
| API 호출 완료 | INFO | 응답 시간, 토큰 사용량 (input/output) |
| 응답 원문 | DEBUG | LLM 응답 전문 |
| 파싱 결과 | INFO | 파싱된 구조체 (dict/list) |
| 파싱 실패 | WARNING | 응답 원문 + 파싱 에러 (fallback 시도 전) |

### 구현 패턴

```python
logger = logging.getLogger("agent.llm")

def call_llm(system_prompt: str, user_prompt: str) -> str:
    logger.debug(f"LLM 요청\n[SYSTEM] {system_prompt[:200]}...\n[USER] {user_prompt}")
    start = time.time()
    try:
        response = _api_호출(system_prompt, user_prompt)
        elapsed = time.time() - start
        usage = response.usage  # token 사용량
        logger.info(f"LLM 완료 | {elapsed:.2f}s | tokens: in={usage.prompt_tokens} out={usage.completion_tokens}")
        logger.debug(f"LLM 응답 원문: {response.content}")
        return response.content
    except Exception as e:
        logger.error(f"LLM 호출 실패 | {e}", exc_info=True)
        raise

def parse_response(raw: str, expected_format: str) -> dict:
    logger.debug(f"파싱 시작 | format={expected_format}")
    try:
        result = _파싱_로직(raw)
        logger.info(f"파싱 성공 | keys={list(result.keys())}")
        return result
    except Exception as e:
        logger.warning(f"파싱 실패 | {e}\n원문: {raw[:300]}")
        raise
```

---

## 4. FSM 상태 전이 로깅 (`agent.fsm`)

### 대상 파일
- `core/state_machine.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 전이 성공 | INFO | `{workflow_type}: {from_state} → {to_state} (trigger: {event})` |
| 전이 거부 | WARNING | `유효하지 않은 전이: {current_state} → {attempted_state}` |
| 워크플로우 시작 | INFO | `워크플로우 시작: {workflow_type}` |
| 워크플로우 종료 | INFO | `워크플로우 완료: {workflow_type} | 총 {n}단계` |

### 구현 패턴

```python
logger = logging.getLogger("agent.fsm")

def transition(self, to_state: WorkflowState, trigger: str = ""):
    from_state = self.state
    if self._is_valid_transition(to_state):
        self._state = to_state
        logger.info(f"{self.workflow_type.value}: {from_state.value} → {to_state.value} | trigger={trigger}")
    else:
        logger.warning(f"전이 거부: {from_state.value} → {to_state.value} | workflow={self.workflow_type.value}")
        raise InvalidTransitionError(...)
```

---

## 5. 데이터 품질 로깅 (`agent.data`)

### 대상 파일
- `pipeline/*.py` (데이터 로딩/전처리 후)
- `wrappers/*.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 데이터 로딩 후 | INFO | shape, 컬럼 목록 |
| null 비율 높음 | WARNING | `컬럼 '{col}'의 null 비율: {pct}%` (threshold: 50%) |
| 컬럼 불일치 | WARNING | `예상 컬럼 누락: {missing_cols}` (schema.py 대비) |
| 전처리 전후 | INFO | `전처리: {before_rows} → {after_rows} rows ({dropped} 제거)` |

### 구현 패턴

```python
logger = logging.getLogger("agent.data")

def validate_dataframe(df: pd.DataFrame, expected_columns: list[str] | None = None):
    logger.info(f"DataFrame shape={df.shape} | columns={list(df.columns)}")

    # null 비율 검사
    null_pcts = df.isnull().mean() * 100
    high_null = null_pcts[null_pcts > 50]
    for col, pct in high_null.items():
        logger.warning(f"컬럼 '{col}' null 비율: {pct:.1f}%")

    # 컬럼 불일치 검사
    if expected_columns:
        missing = set(expected_columns) - set(df.columns)
        if missing:
            logger.warning(f"예상 컬럼 누락: {missing}")
```

---

## 6. Wrapper 호출 로깅 (`agent.wrapper`)

### 대상 파일
- `wrappers/sdk_wrapper.py`
- `wrappers/s3_wrapper.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 호출 시작 | DEBUG | 엔드포인트/경로, 파라미터 |
| 호출 완료 | INFO | 응답 시간, 데이터 크기 |
| 호출 실패 | ERROR | 에러 메시지, 재시도 횟수 |
| 재시도 | WARNING | `재시도 {n}/{max} | {error}` |

### 구현 패턴

```python
logger = logging.getLogger("agent.wrapper")

def load_parquet(s3_path: str) -> pd.DataFrame:
    logger.debug(f"S3 로딩 시작 | path={s3_path}")
    start = time.time()
    try:
        df = _s3_read(s3_path)
        elapsed = time.time() - start
        logger.info(f"S3 로딩 완료 | {elapsed:.2f}s | shape={df.shape} | path={s3_path}")
        return df
    except Exception as e:
        logger.error(f"S3 로딩 실패 | path={s3_path} | {e}", exc_info=True)
        raise
```

---

## 7. 사용자 입력 흐름 로깅 (`agent.app`)

### 대상 파일
- `app.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 사용자 입력 | DEBUG | 입력 원문 (개인정보 주의) |
| 파라미터 추출 | INFO | LLM이 추출한 파라미터 dict |
| 파라미터 검증 | INFO | 성공/실패 + 누락 필드 |
| 워크플로우 선택 | INFO | 선택된 워크플로우 타입 |

---

## 8. 세션/캐시 로깅 (`agent.session`)

### 대상 파일
- `core/session.py`

### 로깅 항목

| 시점 | 레벨 | 내용 |
|------|------|------|
| 세션 키 설정 | DEBUG | `session[{key}] = {value_summary}` |
| 캐시 hit | DEBUG | `캐시 hit: {cache_key}` |
| 캐시 miss | INFO | `캐시 miss: {cache_key} → 새로 로딩` |

---

## 9. 에러/예외 통합 로깅

### 규칙

1. **모든 `except` 블록에서 `exc_info=True` 사용** — traceback 포함
2. **사용자 메시지와 로그 메시지 분리** — `st.error()`에는 친절한 메시지, 로그에는 기술 상세
3. **예외 재발생(re-raise) 시에도 로깅** — 상위에서 잡더라도 발생 지점에서 기록

```python
try:
    result = pipeline.run(params)
except Exception as e:
    logger.error(f"파이프라인 실행 실패 | {e}", exc_info=True)
    st.error("데이터 처리 중 오류가 발생했습니다. 관리자에게 문의하세요.")
    # 필요 시 raise
```

---

## 로그 레벨 가이드

| 레벨 | 용도 |
|------|------|
| DEBUG | 개발 중 상세 추적 (프롬프트 전문, SQL 전문, 파라미터 상세) |
| INFO | 정상 흐름의 주요 이벤트 (함수 완료, 상태 전이, 쿼리 완료) |
| WARNING | 비정상이지만 계속 진행 가능 (파싱 실패→fallback, null 비율 높음) |
| ERROR | 작업 실패 (쿼리 에러, API 호출 실패, 예외 발생) |

---

## 구현 순서 (Roo 작업 순서)

| 순서 | 작업 | 파일 |
|------|------|------|
| 1 | 로깅 설정 초기화 | `config.py` (basicConfig 추가) |
| 2 | (선택) 데코레이터 유틸 | `utils/logging_utils.py` (신규) |
| 3 | SQL 로깅 | `wrappers/sdk_wrapper.py`, `pipeline/data_query.py` |
| 4 | Wrapper 로깅 | `wrappers/s3_wrapper.py` |
| 5 | 파이프라인 로깅 | `pipeline/*.py` (각 함수에 적용) |
| 6 | LLM 로깅 | `llm/client.py`, `llm/parser.py` |
| 7 | FSM 로깅 | `core/state_machine.py` |
| 8 | 데이터 품질 로깅 | `pipeline/*.py` (로딩/전처리 후) |
| 9 | 세션/캐시 로깅 | `core/session.py` |
| 10 | 사용자 입력 로깅 | `app.py` |
| 11 | 에러 통합 정리 | 전체 `except` 블록 점검 |

## 주의사항

- **민감 정보 마스킹** — API 키, 비밀번호, 개인정보는 로그에 남기지 않음
- **DataFrame 내용은 로깅하지 않음** — shape, columns만 기록. 실제 데이터 행은 DEBUG에서도 출력하지 않음
- **로그 파일 출력** — 운영 환경에서는 `FileHandler` 추가하여 `logs/agent.log`에 기록
- **Streamlit 호환** — `st.logger`가 아닌 표준 `logging` 사용. Streamlit 재실행 시에도 로그가 유지됨
