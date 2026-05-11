# AGENTS.md — 프로젝트 규칙

## 역할 분담: Codex vs 루코드(Roo Code)

### Codex가 담당하는 영역
- 아키텍처 설계 및 모듈 구조
- FSM 상태 전이 로직
- LLM 프롬프트/파서 설계
- UI 워크플로우 흐름 제어
- 문서화 (roo_tasks, workflow_diagram)

### 루코드가 담당하는 영역 (Codex는 직접 구현하지 않음)
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

## 코딩 컨벤션

- Python 3.12+
- 타입 힌트 사용 (`str | None`, `list[dict]`)
- 한국어 주석/docstring
- Streamlit session_state 직접 접근 대신 `core/session.py` SessionManager 사용
