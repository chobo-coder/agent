# Task 07: Testing

## Goal
단위 테스트 + 통합 테스트 작성 및 CI 준비

## Files
- `tests/test_state_machine.py`
- `tests/test_pipeline.py`
- `tests/test_orchestrator.py`

## Steps
1. **상태 머신 테스트**
   - Happy path (전체 워크플로우)
   - Skip path (S3 로딩 건너뛰기)
   - Invalid transition 예외
   - Decision point 식별
   - Reset 동작

2. **파이프라인 테스트**
   - 각 핸들러 mock 테스트
   - 전처리 옵션별 단위 테스트
   - 상관분석 출력 검증
   - 예측 점수 범위 검증

3. **파서 테스트**
   - 정상 JSON 파싱
   - 텍스트 내 JSON 추출
   - Malformed 입력 graceful 처리

4. **통합 테스트** (수동)
   - `streamlit run app.py`로 전체 시나리오 수행
   - 각 분기점에서 다양한 입력 테스트

## Acceptance Criteria
- [ ] `pytest tests/` 전체 통과
- [ ] 코드 커버리지 80% 이상 (핵심 로직)
- [ ] Malformed 입력에도 크래시 없음
