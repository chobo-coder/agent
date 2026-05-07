# Task 03: LLM Integration

## Goal
OpenAI 호환 LLM 클라이언트, 프롬프트 빌더, 응답 파서 구현

## Files
- `llm/client.py`
- `llm/prompts.py`
- `llm/parser.py`
- `tests/test_orchestrator.py` (parser tests)

## Steps
1. `LLMClient` 구현:
   - `complete(prompt, system?)` — 단일 요청
   - `complete_with_history(messages, system?)` — 멀티턴
2. `PromptBuilder` 구현:
   - `build_product_extraction(input)` — 제품명 추출
   - `build_decision_prompt(state, input)` — 분기점별 프롬프트
   - `build_summary_prompt(raw)` — 결과 요약
3. `ResponseParser` 구현:
   - `extract_product(response)` — 제품명 파싱
   - `parse_decision(state, response)` — 분기 결정 파싱
   - `extract_features(response)` — 피처 목록
   - `extract_threshold(response)` — 임계값
   - `_extract_json(text)` — JSON 추출 유틸리티
4. 파서 테스트: 정상 JSON, 텍스트 내 JSON, malformed 입력

## Acceptance Criteria
- [ ] API 호출 시 정상 응답 수신 (실제 키 필요)
- [ ] 다양한 형태의 LLM 응답에서 JSON 추출 성공
- [ ] `pytest tests/test_orchestrator.py` 통과
