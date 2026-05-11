# CLAUDE.md — 프로젝트 규칙

## 역할 분담: Claude vs 루코드(Roo Code)

### Claude가 담당하는 영역
- 아키텍처 설계 및 모듈 구조
- FSM 상태 전이 로직
- LLM 프롬프트/파서 설계
- UI 워크플로우 흐름 제어
- 문서화 (roo_tasks, workflow_diagram)

### 루코드가 담당하는 영역 (Claude는 직접 구현하지 않음)
- `schema.py`의 실제 데이터 값 (컬럼명, 테이블명, S3 경로 등)
- `wrappers/sdk_wrapper.py` — 사내 DB SDK 실제 연동
- `wrappers/s3_wrapper.py` — S3 parquet 실제 연동
- `pipeline/data_query.py` — 실제 SQL 쿼리 작성
- 도메인 특화 비즈니스 로직 (전처리 세부 규칙, 예측 모델 등)

### 핵심 규칙

1. **데이터 스키마는 placeholder로 유지** — `schema.py`에 `col_1`, `col_2`, `schema_name.table_name` 같은 익명 값을 사용. 실제 컬럼명/테이블명은 루코드가 교체.

2. **파이프라인 코드는 schema.py를 import하여 참조** — 하드코딩 금지. 모든 데이터 관련 상수는 `schema.py`에서 가져옴.

3. **wrapper는 mock 데이터 반환** — SDK/S3 wrapper는 개발/테스트용 mock 데이터를 반환하는 상태로 유지. 실제 연동은 루코드가 구현.

4. **변경 시 sync-roo 실행** — 상태 머신, 파이프라인 인터페이스, schema 변경 시 `/sync-roo`로 roo_tasks 문서에 변경 이력 추가.

## schema.py 사용 규칙

| 상수 | 용도 | 참조 위치 |
|------|------|----------|
| `REQUIRED_PARAMS` | 사용자 입력 파라미터 정의 | app.py (파라미터 수집) |
| `DB_TABLE`, `DB_COLUMNS` | SQL 쿼리 대상 | pipeline/data_query.py |
| `S3_PATH_PATTERN`, `S3_MERGE_KEYS` | S3 데이터 로딩/머지 | pipeline/data_loader.py |
| `NUMERIC_COLUMNS`, `CATEGORICAL_COLUMNS` | 전처리 대상 분류 | pipeline/preprocessing.py |
| `PREPROCESSING_TOOLS` | 사전 정의 전처리 도구 | app.py (도구 선택 메뉴) |
| `AVAILABLE_FEATURES`, `TARGET_COLUMN` | 피처 분석/예측 | pipeline/feature_analysis.py, prediction.py |

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
- 루코드 담당 영역은 placeholder/mock 경계를 유지하고 실제 도메인 값이나 실제 연동을 구현하지 않는다.

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
