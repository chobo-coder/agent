# 데이터 분석 에이전트 — 코드 설명서

## 프로젝트 개요

Streamlit 채팅 인터페이스 기반의 데이터 분석 에이전트. 사용자와 대화하며 **파라미터 수집 → 데이터 조회 → 전처리 → 피처 분석 → 예측** 워크플로우를 진행한다. FSM(유한 상태 머신)으로 흐름을 제어하고, LLM으로 자연어 파싱을 수행한다.

---

## 아키텍처 구조

```
agent/
├── app.py                  ← Streamlit 진입점 + 전체 워크플로우 로직
├── config.py               ← 환경 설정 (API 키, URL)
├── schema.py               ← 데이터 스키마 정의 (컬럼, 테이블, 도구)
├── core/
│   ├── state_machine.py    ← FSM (상태 + 전이 규칙)
│   ├── session.py          ← Streamlit 세션 래퍼
│   ├── orchestrator.py     ← 메인 제어 루프 (미래 확장용)
│   └── checkpoints.py      ← DataFrame 저장/복원
├── llm/
│   ├── client.py           ← OpenAI 호환 API 클라이언트
│   ├── prompts.py          ← 프롬프트 템플릿
│   └── parser.py           ← LLM 응답 JSON 파싱
├── pipeline/
│   ├── __init__.py         ← BaseHandler ABC
│   ├── data_query.py       ← SQL 조회
│   ├── data_loader.py      ← S3 parquet 로딩
│   ├── data_overview.py    ← 데이터 요약
│   ├── preprocessing.py    ← 전처리 실행
│   ├── feature_analysis.py ← 상관분석 + 피처 중요도
│   └── prediction.py       ← 예측 스코어링
├── ui/
│   ├── chat.py             ← 채팅 렌더링 + 사이드바
│   └── formatters.py       ← DataFrame/차트 포맷팅
└── wrappers/
    ├── sdk_wrapper.py      ← 사내 DB SDK 어댑터 (mock)
    └── s3_wrapper.py       ← S3 parquet 읽기 (mock)
```

---

## 레이어별 상세 설명

---

### 1. `app.py` — Streamlit 진입점

**역할:** 전체 채팅 UI 렌더링 + 사용자 입력을 상태에 따라 라우팅

**핵심 함수:**

| 함수 | 역할 |
|------|------|
| `main()` | Streamlit 페이지 설정, 세션 초기화, 채팅 입력 처리 |
| `handle_user_input(session, user_input)` | 현재 상태에 따라 적절한 핸들러로 분기 |
| `_handle_collecting(session, user_input)` | LLM으로 파라미터 추출 → 검증 → 누락 시 루프 |
| `_extract_params_with_llm(user_input, existing)` | LLM 호출로 파라미터 추출, 실패 시 regex fallback |
| `_parse_params_fallback(text)` | 규칙 기반 파라미터 추출 (날짜, 공정, 제품명 regex) |
| `_parse_tool_selection(text)` | 전처리 도구 선택 파싱 (번호/이름/키워드) |
| `_parse_feature_request(text)` | 피처명 + threshold 추출 |
| `_build_preprocess_menu()` | schema 기반 도구 선택 메뉴 생성 |
| `_build_data_overview(params)` | 데이터 오버뷰 테이블 생성 |

**동작 흐름:**
```
사용자 입력 → handle_user_input()
  ├── IDLE → COLLECTING_PARAMS로 전이 + 파라미터 파싱 시도
  ├── COLLECTING/VALIDATING → LLM 파라미터 추출 → 검증
  │     ├── 누락 → 안내 메시지 + 재입력 대기
  │     └── 완료 → QUERYING_DATA → 오버뷰 표시
  ├── SHOWING_QUERY_RESULTS → Yes/No 파싱 → S3 로딩 분기
  ├── SHOWING_DATA_OVERVIEW → 도구 선택 파싱 → 전처리 실행
  ├── SHOWING_FEATURES → 피처+threshold 파싱 → 예측 실행
  └── COMPLETED → reset → 새 워크플로우
```

---

### 2. `schema.py` — 중앙 데이터 설정

**역할:** 모든 데이터 관련 설정의 단일 소스. 파이프라인 코드가 이 파일을 import하여 사용.

**주요 설정:**

| 상수 | 용도 |
|------|------|
| `REQUIRED_PARAMS` | 사용자에게 수집할 필수 입력 항목 (제품명, 시작일, 종료일, 공정) |
| `PROCESS_OPTIONS` | 선택 가능한 공정 목록 (빈 리스트면 자유 입력) |
| `DB_TABLE`, `DB_COLUMNS` | SQL 쿼리 대상 테이블/컬럼 |
| `S3_PATH_PATTERN`, `S3_MERGE_KEYS` | S3 데이터 경로 패턴 + 머지 키 |
| `NUMERIC_COLUMNS` | 수치형 컬럼 (전처리/분석 대상) |
| `CATEGORICAL_COLUMNS` | 범주형 컬럼 (인코딩 대상) |
| `TARGET_COLUMN` | 예측 타겟 변수 |
| `PREPROCESSING_TOOLS` | 9개 사전 정의 전처리 도구 |
| `AVAILABLE_FEATURES` | 피처 분석에 사용 가능한 컬럼 |
| `DEFAULT_THRESHOLD` | 기본 임계값 (0.5) |

**설계 의도:** 실제 컬럼명/테이블명은 `col_1`, `schema_name.table_name` 같은 placeholder로 되어있음. 사용자가 회사에서 실제 값으로 교체하면 코드 수정 없이 동작.

---

### 3. `core/state_machine.py` — FSM (유한 상태 머신)

**역할:** 워크플로우의 17개 상태와 전이 규칙을 정의. 잘못된 전이를 방지.

**상태 흐름:**
```
IDLE
 → COLLECTING_PARAMS ↔ VALIDATING_PARAMS (누락 시 루프)
   → QUERYING_DATA
     → SHOWING_QUERY_RESULTS (사용자 판단 1)
       → AWAITING_LOAD_DECISION
         ├→ LOADING_PARQUET → SHOWING_DATA_OVERVIEW
         └→ SHOWING_DATA_OVERVIEW (사용자 판단 2)
           → AWAITING_PREPROCESS → PREPROCESSING
             → SHOWING_PREPROCESSED → ANALYZING_FEATURES
               → SHOWING_FEATURES (사용자 판단 3)
                 → AWAITING_COMBINATIONS → PREDICTING
                   → SHOWING_PREDICTIONS → COMPLETED → IDLE
```

**핵심 구성:**

```python
class WorkflowState(Enum):
    # 17개 상태 (IDLE ~ COMPLETED)

DECISION_STATES = {
    # 사용자 입력을 기다리는 5개 상태
    COLLECTING_PARAMS, VALIDATING_PARAMS,
    SHOWING_QUERY_RESULTS, SHOWING_DATA_OVERVIEW, SHOWING_FEATURES
}

TRANSITIONS = {
    # 각 상태에서 갈 수 있는 다음 상태 목록 (딕셔너리)
}

class StateMachine:
    transition_to(target)     # 유효한 전이만 허용
    can_transition_to(target) # 전이 가능 여부 체크
    is_decision_point         # 현재 상태가 분기점인지
    get_next_auto_state()     # 자동 전이 대상 (분기점 아닐 때)
    reset()                   # IDLE로 초기화
```

---

### 4. `core/session.py` — 세션 관리

**역할:** `st.session_state`를 타입 안전하게 래핑. 채팅 히스토리, DataFrame, 메타데이터 관리.

**인터페이스:**
```python
class SessionManager:
    state_machine: StateMachine      # FSM 인스턴스
    current_state: WorkflowState     # 현재 상태
    chat_history: list[dict]         # 채팅 메시지 목록

    add_message(role, content)       # 채팅 메시지 추가
    get_dataframe(key) -> DataFrame  # 중간 결과 조회
    set_dataframe(key, df)           # 중간 결과 저장
    get_metadata(key, default)       # 메타데이터 조회 (params, threshold 등)
    set_metadata(key, value)         # 메타데이터 저장
    reset()                          # 전체 초기화
```

**저장되는 데이터:**
- `workflow_context`: 파이프라인 중간 DataFrame들 (`query_result`, `merged_data`, `preprocessed`, `predictions`)
- `metadata`: 수집된 파라미터, 선택된 도구, 피처, threshold 등
- `chat_history`: `[{"role": "user"|"assistant", "content": "..."}]`

---

### 5. `core/orchestrator.py` — 제어 루프 (확장용)

**역할:** 상태머신 + LLM + 파이프라인을 연결하는 제어 루프. 현재 `app.py`에서 직접 워크플로우를 처리하므로, 향후 리팩토링 시 사용.

**핵심 클래스:**
```python
class StepResult:
    dataframes: dict[str, DataFrame]  # 파이프라인 결과 데이터
    figures: list[Figure]             # 차트/그래프
    summary: str                      # 텍스트 요약
    metadata: dict                    # 부가 정보

class Orchestrator:
    handle_input(user_input) → StepResult
    _start_workflow(user_input)   # IDLE에서 시작
    _handle_decision(user_input)  # 분기점 처리
    _auto_advance()              # 자동 전이
    _execute_current_step()      # 핸들러 실행
```

---

### 6. `llm/client.py` — LLM API 클라이언트

**역할:** OpenAI 호환 API 호출 + 재시도 로직

**동작:**
- 3회 재시도 (1초, 2초, 4초 exponential backoff)
- `APITimeoutError`, `APIConnectionError` → 재시도
- `RateLimitError` → 2배 딜레이 후 재시도
- 모두 실패 시 `LLMError` 발생

```python
class LLMClient:
    complete(prompt, system=None) -> str       # 단일 프롬프트
    complete_with_history(messages, system) -> str  # 멀티턴

class LLMError(Exception):
    # LLM API 호출 실패 시 발생
```

**설정:** `config.py`에서 `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` 참조.

---

### 7. `llm/prompts.py` — 프롬프트 템플릿

**역할:** 각 워크플로우 단계에서 LLM에 보낼 프롬프트 생성

**프롬프트 목록:**

| 메서드 | 용도 | 출력 JSON |
|--------|------|-----------|
| `build_param_extraction()` | 자연어 → 파라미터 추출 | `{product, date_from, date_to, process}` |
| `_build_load_decision_prompt()` | 추가 로딩 판단 | `{load_additional: bool, reason}` |
| `_build_preprocess_decision_prompt()` | 전처리 선택 | `{items: [...], params: {...}}` |
| `_build_combination_prompt()` | 피처+threshold | `{features: [...], threshold: float}` |
| `build_summary_prompt()` | 결과 요약 | 자연어 텍스트 |

**특징:**
- 모든 프롬프트에 few-shot 예시 포함
- `schema.py` 값을 참조하여 동적 프롬프트 생성
- "반드시 JSON만 출력" 규칙 명시

---

### 8. `llm/parser.py` — 응답 파서

**역할:** LLM 텍스트 응답에서 JSON 추출

**파싱 전략 (순서대로 시도):**
1. 전체 텍스트를 `json.loads()`로 직접 파싱
2. `{...}` regex로 flat JSON 추출

**인터페이스:**
```python
class ResponseParser:
    extract_product(response) -> str
    parse_decision(state, response) -> dict
    extract_features(response) -> list[str]
    extract_threshold(response) -> float
    _extract_json(text) -> dict  # 내부 핵심 메서드
```

---

### 9. `pipeline/` — 파이프라인 핸들러들

모든 핸들러는 `BaseHandler` ABC를 상속하고, `execute(session) -> StepResult`를 구현.

#### `pipeline/__init__.py` — BaseHandler
```python
class BaseHandler(ABC):
    @abstractmethod
    def execute(self, session: SessionManager) -> StepResult: ...
```

#### `pipeline/preprocessing.py` — 전처리

| 핸들러 메서드 | 동작 |
|---------------|------|
| `_handle_missing(df, params)` | drop/mean/median 결측치 처리 |
| `_handle_outliers(df, params)` | IQR 기반 이상치 제거 |
| `_handle_encoding(df, params)` | 범주형 → 원핫 인코딩 |
| `_handle_scaling(df, params)` | StandardScaler 적용 |
| `_handle_feature_selection(df, params)` | 지정 컬럼만 선택 |

**도구 실행 방식:** `session.metadata["preprocess_items"]`에 handler 이름 리스트가 저장되면, `_apply()`가 순서대로 실행.

#### `pipeline/feature_analysis.py` — 피처 분석

- 수치형 컬럼 간 상관계수 행렬 계산 (`df.corr()`)
- seaborn heatmap 생성
- 상위 10개 상관관계 쌍 텍스트 출력

#### `pipeline/prediction.py` — 예측

- 선택된 피처 컬럼을 0~1로 정규화
- 정규화된 값의 평균을 예측 점수로 사용 (단순 스코어링)
- threshold 기준으로 이상/미만 분류
- 향후 실제 모델(joblib/pickle)로 교체 예정

---

### 10. `ui/chat.py` — 채팅 UI

**역할:** Streamlit 채팅 메시지 렌더링 + 사이드바 워크플로우 표시

**구성요소:**

| 함수 | 역할 |
|------|------|
| `render_chat_history(session)` | 저장된 채팅 메시지를 `st.chat_message`로 렌더링 |
| `render_sidebar(session)` | 진행률 바 + 단계별 상태 + 현재 컨텍스트 표시 |
| `render_step_result(result)` | StepResult를 채팅 내 마크다운/테이블/차트로 표시 |

**사이드바 표시 내용:**
- 진행률 퍼센트 바
- 17개 상태 목록 (완료=취소선, 현재=볼드, 미래=○)
- 현재 조회 조건 (제품, 기간, 공정)
- 선택된 전처리/피처/임계값
- "처음부터 다시" 리셋 버튼

---

### 11. `config.py` — 환경 설정

`.env` 파일에서 값을 로드. 모든 설정은 `os.getenv`로 오버라이드 가능.

```python
LLM_API_BASE_URL = "https://api.openai.com/v1"  # LLM 엔드포인트
LLM_API_KEY = ""           # API 키 (.env에 설정)
LLM_MODEL = "gpt-4o"      # 사용 모델
LLM_TEMPERATURE = 0.2     # 낮은 온도 → 결정적 출력
LLM_MAX_TOKENS = 2048
S3_BUCKET = ""             # S3 버킷명
S3_REGION = "ap-northeast-2"
SDK_API_URL = ""           # 사내 SDK URL
SDK_API_KEY = ""           # 사내 SDK 키
CHECKPOINT_DIR = ".checkpoints"
```

---

## LLM 사용 지점 (4곳)

| 지점 | 상태 | LLM 역할 | 실패 시 |
|------|------|----------|---------|
| 파라미터 추출 | COLLECTING_PARAMS | 자연어 → `{product, dates, process}` | regex fallback |
| 추가 로딩 판단 | SHOWING_QUERY_RESULTS | 의도 분류 → `{load: bool}` | 키워드 매칭 |
| 전처리 선택 | SHOWING_DATA_OVERVIEW | 도구 파싱 → `{items, params}` | 번호/키워드 매칭 |
| 피처 조합 | SHOWING_FEATURES | 피처+임계값 → `{features, threshold}` | regex 추출 |

**핵심:** LLM API 키가 없어도 앱이 동작함. 모든 LLM 호출에 규칙 기반 fallback이 있음.

---

## 데이터 흐름

```
사용자 입력
    │
    ▼
[파라미터 수집] → session.metadata["query_params"]
    │
    ▼
[SQL 조회] → session.workflow_context["query_result"] (DataFrame)
    │
    ▼
[S3 로딩 + 머지] → session.workflow_context["merged_data"] (DataFrame)
    │
    ▼
[전처리] → session.workflow_context["preprocessed"] (DataFrame)
    │
    ▼
[피처 분석] → session.workflow_context["correlation_matrix"] + heatmap
    │
    ▼
[예측] → session.workflow_context["predictions"] (DataFrame + 점수)
```

---

## 실행 방법

```bash
# 의존성 설치
pip install -r requirements.txt

# .env 파일 설정 (선택)
cp .env.example .env
# LLM_API_KEY=sk-... 설정

# 앱 실행
streamlit run app.py
```

LLM API 키 없이도 실행 가능 (규칙 기반 fallback으로 동작).

---

## 루코드 구현 대상 (미구현)

| 영역 | 파일 | 내용 |
|------|------|------|
| 실제 DB 연동 | `wrappers/sdk_wrapper.py` | 사내 SDK로 SQL 실행 |
| 실제 S3 연동 | `wrappers/s3_wrapper.py` | boto3로 parquet 읽기 |
| 실제 스키마 | `schema.py` | placeholder → 실제 컬럼/테이블명 |
| 모델 연동 | `pipeline/prediction.py` | 단순 스코어링 → 학습된 모델 |
| 피처 중요도 | `pipeline/feature_analysis.py` | RandomForest 중요도 추가 |
| 체크포인트 | `core/checkpoints.py` | parquet 저장/복원 |
