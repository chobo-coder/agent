# Roo Code 프로젝트 규칙

## 프로젝트 개요

Streamlit 채팅 기반 데이터 분석 에이전트. FSM(유한 상태 머신)으로 워크플로우를 제어하고, LLM으로 자연어를 파싱한다. 3종의 워크플로우(기존 분석 / MAP 경향성 / 장비 경향성)를 지원한다.

## 코딩 전 반드시 읽을 파일

| 순서 | 파일 | 이유 |
|------|------|------|
| 1 | `schema.py` | 모든 데이터 설정의 단일 소스. 컬럼명, 테이블명, 도구 정의가 여기 있음 |
| 2 | `core/state_machine.py` | 워크플로우 상태 + 전이 규칙. 새 기능 추가 시 여기서 흐름 확인 |
| 3 | `docs/roo_tasks/` | 태스크별 상세 스펙 + 변경 이력. 이전에 무엇이 바뀌었는지 확인 |
| 4 | `CLAUDE.md` | Claude와 Roo의 역할 분담 규칙 |

## 핵심 규칙

### 1. schema.py가 유일한 데이터 설정 소스

- 컬럼명, 테이블명, 경로 패턴을 코드에 하드코딩하지 않는다
- 반드시 `import schema` 후 `schema.DB_TABLE`, `schema.DB_COLUMNS` 등으로 참조
- 새 설정이 필요하면 `schema.py`에 추가하고 코드에서 import

```python
# 올바른 예
import schema
query = f"SELECT {', '.join(schema.DB_COLUMNS)} FROM {schema.DB_TABLE}"

# 잘못된 예
query = "SELECT col_1, col_2 FROM my_table"
```

### 2. 파이프라인 핸들러 구조

모든 핸들러는 `pipeline/__init__.py`의 `BaseHandler`를 상속한다:

```python
from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult

class MyHandler(BaseHandler):
    def execute(self, session: SessionManager) -> StepResult:
        # session에서 데이터 가져오기
        df = session.get_dataframe("key")
        params = session.get_metadata("key")

        # 처리 로직
        result_df = ...

        # StepResult로 반환
        return StepResult(
            dataframes={"result_key": result_df},
            figures=[fig],          # matplotlib Figure (선택)
            summary="요약 텍스트",
            metadata={"key": "val"},
        )
```

### 3. 세션 데이터 접근

`st.session_state`를 직접 접근하지 않는다. 반드시 `SessionManager`를 통해:

```python
session.get_dataframe("query_result")    # DataFrame 조회
session.set_dataframe("key", df)         # DataFrame 저장
session.get_metadata("query_params")     # 메타데이터 조회
session.set_metadata("key", value)       # 메타데이터 저장
```

### 4. 상태 전이 규칙

- 새 상태 추가 시: `WorkflowState` enum에 추가 → `TRANSITIONS`(또는 워크플로우별 전이 dict)에 등록
- 사용자 입력 대기 상태는 `DECISION_STATES`에도 추가
- 워크플로우별 전이는 `_COMMON_TRANSITIONS`(공통)과 `_XXX_TRANSITIONS`(전용)으로 분리

### 5. 전처리 도구 추가 방법

1. `schema.PREPROCESSING_TOOLS`에 도구 정의 추가:
   ```python
   {"id": "my_tool", "name": "도구명", "description": "설명", "handler": "handler_key", "params": {...}}
   ```
2. `pipeline/preprocessing.py`의 `_apply()`에 분기 추가:
   ```python
   elif item == "handler_key":
       return self._handle_my_tool(df, params)
   ```
3. 핸들러 메서드 구현

### 6. Y값 결정 로직

| 조건 | Y값 결정 방식 |
|------|--------------|
| `cat` 파라미터 지정됨 | `y = 1` if `row[schema.DB_CAT_COLUMN] == cat값` else `0` |
| `cat` 미지정 | `schema.FAILBIN` 참조. oper별 bin 번호 리스트에 해당하면 `y=1` |

## 워크플로우 구조

### 공통 구간 (모든 워크플로우)

```
IDLE → SELECTING_WORKFLOW → COLLECTING_PARAMS ↔ VALIDATING_PARAMS → QUERYING_DATA → SHOWING_QUERY_RESULTS → (S3 로딩 분기) → SHOWING_DATA_OVERVIEW
```

### 분기 이후

| 워크플로우 | 오버뷰 이후 흐름 | 상태 |
|-----------|-----------------|------|
| conventional | 전처리 → 피처분석 → 예측 | 구현 완료 |
| map_trend | MAP 파라미터 → MAP 로딩 → 공간분석 → 결과 → (비교) | TODO |
| equip_trend | 장비 파라미터 → 센서 로딩 → 트렌드분석 → 결과 → (상관분석) | TODO |

### MAP/장비 워크플로우 구현 시 체크리스트

1. `core/state_machine.py`에서 해당 상태 enum 주석 해제
2. 해당 `_XXX_TRANSITIONS` dict 주석 해제
3. `_build_transitions()`에 elif 분기 추가
4. `DECISION_STATES`에 분기점 상태 추가
5. `pipeline/map_trend.py` 또는 `pipeline/equip_trend.py`에서 핸들러 구현
6. `core/orchestrator.py`의 `_workflow_handlers`에 핸들러 등록
7. `core/orchestrator.py`의 `_resolve_next_state`에 분기 로직 추가
8. `app.py`에 해당 상태의 사용자 입력 핸들링 함수 추가
9. `schema.py`에서 관련 설정 주석 해제 및 실제 값 입력

## 파일 구조 요약

```
agent/
├── app.py                  # Streamlit UI + 상태별 라우팅
├── schema.py               # 데이터 설정 (컬럼, 테이블, 도구, FAILBIN)
├── config.py               # 환경 설정 (API 키, URL)
├── core/
│   ├── state_machine.py    # FSM (WorkflowType, WorkflowState, StateMachine)
│   ├── session.py          # Streamlit 세션 래퍼
│   ├── orchestrator.py     # 멀티 워크플로우 제어 루프
│   └── checkpoints.py      # DataFrame 저장/복원
├── llm/
│   ├── client.py           # LLM API 클라이언트 (retry 포함)
│   ├── prompts.py          # 프롬프트 템플릿
│   └── parser.py           # JSON 파서
├── pipeline/
│   ├── __init__.py         # BaseHandler ABC
│   ├── data_query.py       # SQL 조회 (schema.DB_* 참조)
│   ├── data_loader.py      # S3 parquet 로딩 (schema.S3_* 참조)
│   ├── preprocessing.py    # 전처리 (13개 도구)
│   ├── feature_analysis.py # 상관분석 + 피처 중요도
│   ├── prediction.py       # 예측 스코어링
│   ├── map_trend.py        # TODO: MAP 경향성 핸들러
│   └── equip_trend.py      # TODO: 장비 경향성 핸들러
├── wrappers/
│   ├── sdk_wrapper.py      # 사내 DB SDK (mock → 실제 연동 필요)
│   └── s3_wrapper.py       # S3 parquet (mock → 실제 연동 필요)
└── ui/
    ├── chat.py             # 채팅 렌더링 + 사이드바
    └── formatters.py       # DataFrame/차트 포맷팅
```

## 코딩 컨벤션

- Python 3.12+
- 타입 힌트 사용 (`str | None`, `list[dict]`)
- docstring과 주석은 한국어
- 변수/함수명은 snake_case 영문
- 새 파일 생성 시 모듈 docstring에 역할 설명 포함
- `schema.py`의 TODO 주석이 붙은 값은 사용자가 교체할 영역 — 로직 변경 없이 값만 바꾸면 동작해야 함
