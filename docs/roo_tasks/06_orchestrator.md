# Task 06: Orchestrator

## Goal
상태머신 + LLM + 파이프라인 + UI를 연결하는 메인 제어 루프

## Files
- `core/orchestrator.py`
- `core/session.py`
- `core/checkpoints.py`
- `app.py`

## Steps
1. `SessionManager` — `st.session_state` 래핑, DataFrame/metadata 관리
2. `CheckpointManager` — parquet 저장/로드/삭제
3. `Orchestrator.__init__` — 모든 핸들러 등록
4. `handle_input(user_input)`:
   - IDLE → 제품 추출 → QUERYING_DATA
   - Decision point → LLM 분류 → 다음 상태 결정
   - Non-decision → 자동 전이
5. `_execute_current_step()` — 핸들러 실행 + 체크포인트 + 요약
6. `app.py` — Streamlit 진입점에서 Orchestrator 연결

## Acceptance Criteria
- [ ] 전체 워크플로우 시나리오 수행 가능
- [ ] 체크포인트 파일 생성 확인
- [ ] 에러 시 상태 롤백 또는 에러 메시지 표시
- [ ] `streamlit run app.py`로 실행 가능
