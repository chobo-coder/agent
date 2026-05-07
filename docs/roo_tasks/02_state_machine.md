# Task 02: State Machine

## Goal
워크플로우 상태 머신 구현 및 테스트

## Files
- `core/state_machine.py`
- `tests/test_state_machine.py`

## Steps
1. `WorkflowState` enum 정의 (15개 상태)
2. `TRANSITIONS` 딕셔너리로 유효한 전이 규칙 정의
3. `StateMachine` 클래스 구현:
   - `state` property
   - `transition_to(target)` — 유효성 검사 후 전이
   - `can_transition_to(target)` — 전이 가능 여부
   - `is_decision_point` — LLM 판단 필요 여부
   - `get_next_auto_state()` — 자동 전이 대상
   - `reset()` — IDLE로 복귀
4. 테스트: happy path, skip path, invalid transition, decision point 판별

## Acceptance Criteria
- [ ] 모든 유효 경로 전이 성공
- [ ] 잘못된 전이 시 `InvalidTransitionError` 발생
- [ ] Decision point 3곳 정확히 식별
- [ ] `pytest tests/test_state_machine.py` 통과
