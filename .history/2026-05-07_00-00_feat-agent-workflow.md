# feat-agent-workflow

- **날짜**: 2026-05-07
- **브랜치**: main
- **커밋**: b17178c initial

## 한 줄 요약

Streamlit 채팅 기반 데이터 분석 에이전트의 전체 워크플로우(파라미터 수집 → 검증 → 조회 → 전처리 → 피처분석 → 예측)를 FSM + LLM 기반으로 구현하고, 루코드 개발용 태스크 문서를 완성했다.

## 변경된 파일

| 파일 | 유형 | 설명 |
|------|------|------|
| app.py | 수정 | Streamlit 진입점 — 전체 채팅 워크플로우 로직 (상태별 핸들러, LLM 파라미터 추출, 도구 선택 전처리) |
| schema.py | 추가 | 중앙 데이터 설정 — REQUIRED_PARAMS, DB/S3 컬럼, PREPROCESSING_TOOLS 정의 |
| core/state_machine.py | 수정 | FSM에 COLLECTING_PARAMS, VALIDATING_PARAMS 상태 추가 (15→17개) |
| llm/client.py | 수정 | OpenAI 호환 클라이언트 — retry/backoff, LLMError 예외 |
| llm/prompts.py | 수정 | 프롬프트 빌더 — build_param_extraction, few-shot 예시, SYSTEM_PROMPT |
| pipeline/data_query.py | 수정 | schema.DB_* 상수 참조로 변경 |
| pipeline/data_loader.py | 수정 | schema.S3_* 상수 참조로 변경 |
| ui/chat.py | 수정 | 사이드바 진행률, 상태 한국어 라벨, 쿼리 파라미터 표시 |
| docs/workflow_diagram.md | 추가 | 전체 워크플로우 ASCII 다이어그램 |
| docs/roo_tasks/prompts.md | 추가 | 루코드용 태스크별 복붙 프롬프트 |
| docs/roo_tasks/01~07_*.md | 수정 | 태스크 상세화 + 변경 이력 섹션 추가 |
| .todo | 추가 | 사용자 수동 작업 TODO (환경설정, SDK/S3 연동, schema 교체) |

## 주요 변경 내용

### 배경

기존 Python 스크립트를 Streamlit 채팅 UI 기반 에이전틱 앱으로 전환하되, 실제 비즈니스 로직(DB/S3 연동)은 루코드가 후속 구현하도록 구조만 완성하는 것이 목표였다.

### 구현 내용

**상태 머신 레이어 (core/)**
- 17개 상태의 FSM으로 워크플로우 제어
- COLLECTING_PARAMS ↔ VALIDATING_PARAMS 루프로 필수 파라미터 수집
- DECISION_STATES에서 사용자 입력 대기

**LLM 레이어 (llm/)**
- OpenAI 호환 API 클라이언트 (retry 3회, exponential backoff)
- 파라미터 추출 프롬프트 (few-shot 예시 포함)
- API 키 없이도 동작하는 regex fallback

**파이프라인 레이어 (pipeline/)**
- schema.py 기반 설정 분리 (컬럼명, 테이블명은 익명 placeholder)
- PREPROCESSING_TOOLS: 9개 사전 정의 도구 (번호/이름/키워드로 선택)
- 도구 선택 파싱 우선순위: 구체적 키워드 > 일반 키워드

**UI 레이어 (ui/)**
- 사이드바 진행률 바 + 상태 라벨
- 데이터 오버뷰 → 전처리 메뉴 → 피처 분석 결과 순차 표시

**문서 레이어 (docs/)**
- roo_tasks 7개 태스크 MD 상세화 + 변경 이력 섹션
- prompts.md: 루코드에 복붙할 프롬프트 모음
- workflow_diagram.md: 전체 흐름 ASCII 다이어그램

## 영향 범위

- 전체 앱 워크플로우 (IDLE → COMPLETED)
- 루코드 개발 태스크 문서 (roo_tasks/)
- schema.py를 참조하는 모든 파이프라인 핸들러

## 다음 작업

- [ ] 사내 SDK 연동 (wrappers/sdk_wrapper.py 실제 구현)
- [ ] S3 parquet 연동 (wrappers/s3_wrapper.py 실제 구현)
- [ ] schema.py의 TODO 항목을 실제 테이블/컬럼명으로 교체
- [ ] .env 파일에 LLM_API_KEY, SDK_API_URL 등 설정
- [ ] 루코드로 태스크 01~07 순차 구현
