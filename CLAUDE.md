# CLAUDE.md — 프로젝트 규칙

## 개발 환경 제약

```
Claude (집) ──git push──→ Roo (회사)   ✅ 단방향 전달
Roo (회사)  ──────────→ Claude         ❌ 역방향 불가
```

- Claude는 Roo가 수정한 내용을 알 수 없다.
- 따라서 Claude의 코드는 **Roo의 변경에 영향받지 않는 영역**에 집중한다.
- 양쪽이 같은 파일(`app.py`)을 수정할 수 있지만, **수정 영역을 분리**하여 충돌을 최소화한다.

## 파일 소유권

### Claude 영역 (Claude가 주로 수정)

| 파일 | 수정 범위 |
|------|----------|
| `app.py` | UI 렌더링, FSM 전이 흐름, `st.status` 진행 상태, 사용자 입력 처리 |
| `core/state_machine.py` | 상태 정의, 전이 규칙 |
| `core/session.py` | SessionManager |
| `llm/prompts.py` | 프롬프트 템플릿 |
| `llm/parser.py` | LLM 응답 파서 |
| `ui/chat.py` | 채팅 UI, 사이드바 |
| `ui/components.py`, `ui/formatters.py` | UI 컴포넌트 |
| `test_*.py`, `tests/*.py` | 모든 테스트 코드 |
| `docs/` | 문서 전체 |

### Roo 영역 (Roo가 주로 수정)

| 파일 | 수정 범위 |
|------|----------|
| `schema.py` | 실제 컬럼명, 테이블명, S3 경로, 파라미터 정의 |
| `pipeline/*.py` | 파이프라인 실제 구현 (쿼리, 전처리, 분석 로직) |
| `wrappers/sdk_wrapper.py` | 사내 DB SDK 실제 연동 |
| `wrappers/s3_wrapper.py` | S3 parquet 실제 연동 |
| `app.py` | 파이프라인 호출부, 실제 데이터 처리 로직 |

### app.py 공유 규칙

`app.py`는 양쪽 모두 수정하므로 다음 규칙으로 충돌을 줄인다:

1. **Claude는 UI/흐름만 수정** — `st.status`, `st.write`, `st.dataframe`, FSM 전이 호출, 사용자 입력 분기
2. **Roo는 데이터 처리만 수정** — pipeline 함수 호출, 실제 파라미터 매핑, 결과 후처리
3. **Claude는 pipeline 호출 시 mock 호환 패턴 유지** — `pipeline.xxx(params)` 형태로 호출하고, mock에서도 동작하도록 작성
4. **함수 시그니처 변경 시 `pipeline/_interfaces.py`에 명시** — Claude가 정의한 시그니처를 Roo가 참고하여 구현

### 핵심 규칙

1. **Claude는 Roo 영역 파일을 직접 수정하지 않는다** — `schema.py`, `pipeline/*.py`, `wrappers/*.py`는 mock/placeholder만 작성하고 실제 구현은 Roo에게 맡긴다.

2. **파이프라인 인터페이스를 안정적으로 유지** — Claude가 `app.py`에서 호출하는 pipeline 함수의 시그니처(이름, 파라미터, 반환 타입)는 `pipeline/_interfaces.py`에 정의. Roo는 이 시그니처를 따라 구현.

3. **변경 시 sync-roo 실행** — 상태 머신, 파이프라인 인터페이스, UI 변경 시 `/sync-roo`로 roo_tasks 문서에 변경 이력 추가. Roo가 Claude의 변경을 이해할 수 있는 유일한 채널.

4. **테스트는 mock 기반으로 작성** — Claude가 작성하는 테스트는 실제 DB/S3 없이 mock 데이터로 동작해야 한다. Roo가 pipeline을 교체해도 테스트 구조는 유지.

## schema.py 사용 규칙 (Roo 소유, Claude는 참조만)

| 상수 | 용도 | 참조 위치 |
|------|------|----------|
| `REQUIRED_PARAMS` | 사용자 입력 파라미터 정의 | app.py (파라미터 수집) |
| `DB_TABLE`, `DB_COLUMNS` | SQL 쿼리 대상 | pipeline/data_query.py |
| `S3_PATH_PATTERN`, `S3_MERGE_KEYS` | S3 데이터 로딩/머지 | pipeline/data_loader.py |
| `NUMERIC_COLUMNS`, `CATEGORICAL_COLUMNS` | 전처리 대상 분류 | pipeline/preprocessing.py |
| `PREPROCESSING_TOOLS` | 사전 정의 전처리 도구 | app.py (도구 선택 메뉴) |
| `AVAILABLE_FEATURES`, `TARGET_COLUMN` | 피처 분석/예측 | pipeline/feature_analysis.py, prediction.py |

Claude는 `schema.py`에 placeholder 값만 작성한다. Roo가 실제 값으로 교체하며, Claude는 교체된 값을 알 수 없으므로 **값에 의존하는 로직을 작성하지 않는다**.

## Karpathy 기반 작업 원칙

Andrej Karpathy가 지적한 LLM 코딩 에이전트의 흔한 실패 패턴을 줄이기 위해 다음 원칙을 따른다.

### 1. 구현 전에 생각하기

- 요구사항이 모호하면 조용히 가정하지 말고, 가능한 해석과 전제를 먼저 밝힌다.
- 여러 구현 방향이 있으면 장단점과 선택 기준을 간단히 제시한다.
- 더 단순한 접근이 충분하면 과한 설계보다 단순한 접근을 우선한다.
- 이해하지 못한 코드나 도메인 규칙은 추측해서 바꾸지 말고 질문하거나 보류한다.

### 2. 단순함 우선

- 요청받지 않은 기능, 옵션, 설정, 확장성을 추가하지 않는다.
- 한 번만 쓰이는 코드를 위해 새 추상화를 만들지 않는다.
- 불가능하거나 아직 요구되지 않은 상황을 위해 과한 방어 코드를 넣지 않는다.
- 구현이 불필요하게 길어졌다면 같은 목표를 더 짧고 명확하게 달성하는 방식으로 줄인다.

### 3. 외과적 변경

- 사용자 요청과 직접 관련된 파일과 줄만 수정한다.
- 인접 코드, 주석, 포맷을 임의로 개선하거나 리팩터링하지 않는다.
- 기존 스타일과 구조를 우선 따른다.
- 내 변경으로 생긴 미사용 import, 변수, 함수는 정리하되, 기존 dead code는 요청 없이 삭제하지 않는다.
- Roo 영역 파일(`schema.py`, `pipeline/*.py`, `wrappers/*.py`)은 mock/placeholder만 작성하고 실제 값이나 연동을 구현하지 않는다.
- `app.py` 수정 시 UI/흐름 영역만 변경하고, pipeline 호출 패턴은 기존 시그니처를 유지한다.

### 4. 목표와 검증 기준으로 실행

- 작업을 시작할 때 성공 조건과 확인 방법을 분명히 한다.
- 버그 수정은 가능하면 재현 조건이나 테스트를 먼저 정의한 뒤 고친다.
- 리팩터링은 변경 전후 동작이 유지되는지 확인할 수 있는 검증을 함께 둔다.
- 다단계 작업은 각 단계마다 "무엇을 바꾸고 어떻게 확인할지"를 짧게 계획한다.

## 코딩 컨벤션

- Python 3.12+
- 타입 힌트 사용 (`str | None`, `list[dict]`)
- 한국어 주석/docstring
- Streamlit session_state 직접 접근 대신 `core/session.py` SessionManager 사용
