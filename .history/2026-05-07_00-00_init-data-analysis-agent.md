# init-data-analysis-agent

- **날짜**: 2026-05-07
- **브랜치**: (git 미초기화)
- **커밋**: N/A - 초기 스캐폴딩

## 한 줄 요약

Streamlit 채팅 기반 데이터 분석 에이전트의 전체 프로젝트 스캐폴딩 완료 (FSM + LLM + Pipeline + UI + Docs)

## 변경된 파일

| 파일 | 유형 | 설명 |
|------|------|------|
| app.py | 추가 | Streamlit 진입점 |
| config.py | 추가 | 환경변수 기반 설정 |
| requirements.txt | 추가 | Python 의존성 목록 |
| core/state_machine.py | 추가 | 15개 상태 FSM + 전이 규칙 |
| core/session.py | 추가 | st.session_state 래퍼 |
| core/orchestrator.py | 추가 | 메인 제어 루프 + StepResult |
| core/checkpoints.py | 추가 | DataFrame 체크포인트 저장/로드 |
| llm/client.py | 추가 | OpenAI 호환 API 클라이언트 |
| llm/prompts.py | 추가 | 단계별 프롬프트 템플릿 |
| llm/parser.py | 추가 | LLM 응답 JSON 파서 |
| pipeline/__init__.py | 추가 | BaseHandler ABC |
| pipeline/data_query.py | 추가 | SQL 조회 핸들러 |
| pipeline/data_loader.py | 추가 | S3 parquet 로딩+머지 |
| pipeline/data_overview.py | 추가 | 데이터 요약 통계 |
| pipeline/preprocessing.py | 추가 | 5가지 전처리 옵션 |
| pipeline/feature_analysis.py | 추가 | 상관분석 + heatmap |
| pipeline/prediction.py | 추가 | 피처 조합 예측 |
| ui/chat.py | 추가 | 채팅 렌더링 + 사이드바 |
| ui/components.py | 추가 | Streamlit 위젯 |
| ui/formatters.py | 추가 | DataFrame/Figure 포맷터 |
| wrappers/sdk_wrapper.py | 추가 | 사내 DB SDK 어댑터 (stub) |
| wrappers/s3_wrapper.py | 추가 | S3 parquet 리더 (stub) |
| tests/test_state_machine.py | 추가 | FSM 단위 테스트 10개 |
| tests/test_pipeline.py | 추가 | 파이프라인 mock 테스트 |
| tests/test_orchestrator.py | 추가 | LLM 파서 테스트 6개 |
| docs/architecture.md | 추가 | 아키텍처 설계 문서 |
| docs/roo_tasks/01~07 | 추가 | 루코드 개발용 태스크 7개 |

## 주요 변경 내용

### 배경
기존 Python 스크립트 기반 데이터 분석을 Streamlit 채팅 에이전트로 전환하기 위해, 루코드(Roo Code)로 개발할 수 있도록 구조 설계 + 코드 스캐폴딩을 생성함.

### 구현 내용

**Core 레이어**
- `StateMachine`: 15개 상태, 전이 테이블, 3개 LLM 분기점 식별
- `SessionManager`: DataFrame/metadata를 session_state로 관리
- `Orchestrator`: 상태별 핸들러 라우팅, LLM 연동, 체크포인트 저장
- `CheckpointManager`: parquet 기반 중간 결과 저장/복구

**LLM 레이어**
- `LLMClient`: OpenAI 호환 API (base_url 변경 가능)
- `PromptBuilder`: 제품 추출, 분기 결정, 결과 요약 프롬프트
- `ResponseParser`: JSON 추출 (정규식 fallback 포함)

**Pipeline 레이어**
- 6개 핸들러 모두 `BaseHandler.execute(session) → StepResult` 인터페이스 준수
- 전처리: missing/outlier/encoding/scaling/feature_selection
- 예측: 정규화 평균 스코어링 + threshold 적용

**UI 레이어**
- 채팅 히스토리 렌더링 + StepResult 혼합 표시
- 사이드바 워크플로우 진행률

## 영향 범위

- 전체 신규 프로젝트 (기존 코드 없음)
- 사내 SDK / S3 wrapper는 stub으로 남아있음 → 실제 연동 필요

## 다음 작업

- [ ] 사내 SDK wrapper 실제 구현 연동
- [ ] S3 wrapper 실제 구현 연동
- [ ] Streamlit 전체 의존성 설치 후 통합 테스트
- [ ] .env 파일 생성 및 API 키 설정
- [ ] git init + 초기 커밋
