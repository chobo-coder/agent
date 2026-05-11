"""워크플로우 E2E 테스트 — Streamlit AppTest 기반.

사용법:
    .venv/bin/python -m pytest test_workflow_e2e.py -v -s

각 테스트의 PROMPTS 리스트를 수정하여 다양한 프롬프트를 테스트할 수 있다.
"""

import pytest
from streamlit.testing.v1 import AppTest

from core.state_machine import WorkflowState


# =============================================================================
# 헬퍼
# =============================================================================

def create_app() -> AppTest:
    """앱 인스턴스 생성 + 초기 실행"""
    at = AppTest.from_file("app.py", default_timeout=30)
    at.run()
    assert not at.exception, f"앱 초기화 실패: {at.exception}"
    return at


def send_message(at: AppTest, text: str, via: str = "chat") -> AppTest:
    """메시지 전송 후 실행.

    Args:
        via: "chat" = chat_input, "feat" = 피처 선택 text_input,
             "candidate" = MAP 후보 선택 text_input
    """
    if via == "chat":
        at.chat_input[0].set_value(text).run()
    elif via == "feat":
        # SHOWING_FEATURES 상태의 text_input + 버튼
        at.text_input(key="_feat_text_input").set_value(text).run()
        at.button(key="_feat_send").click().run()
    elif via == "candidate":
        # MAP_SHOWING_FAIL_CONCENTRATION 상태의 text_input + 버튼
        at.text_input(key="_candidate_text_input").set_value(text).run()
        at.button(key="_candidate_send").click().run()
    assert not at.exception, f"'{text}' 입력 후 에러: {at.exception}"
    return at


def get_last_assistant_message(at: AppTest) -> str:
    """마지막 assistant 메시지 텍스트 반환"""
    assistant_msgs = [
        cm for cm in at.chat_message
        if cm.name == "assistant"
    ]
    if not assistant_msgs:
        return ""
    # 마지막 assistant 메시지의 markdown children
    last = assistant_msgs[-1]
    texts = []
    for child in last.children.values():
        if hasattr(child, "value"):
            texts.append(child.value)
    return "\n".join(texts)


def get_current_state(at: AppTest) -> str:
    """현재 FSM 상태 반환"""
    # session_state에서 state_machine 접근
    try:
        sm = at.session_state["state_machine"]
        return sm.state.value
    except (KeyError, AttributeError):
        return "unknown"


def print_step(step_num: int, prompt: str, response: str, state: str):
    """테스트 단계 출력"""
    print(f"\n{'='*60}")
    print(f"  Step {step_num}: 입력 = \"{prompt}\"")
    print(f"  상태: {state}")
    print(f"{'='*60}")
    # 응답은 처음 300자만
    preview = response[:300] + ("..." if len(response) > 300 else "")
    print(f"  응답:\n{preview}")


# =============================================================================
# Conventional 워크플로우 테스트
# =============================================================================

class TestConventionalWorkflow:
    """기존 분석(Conventional) 워크플로우 E2E 테스트.

    PROMPTS를 수정하여 다양한 시나리오를 테스트할 수 있다.
    """

    # ── 여기를 수정하세요 ──
    # via: "chat" = chat_input (기본), "feat" = 피처 text_input, "candidate" = MAP 후보 text_input
    PROMPTS = [
        # step 1: 워크플로우 선택
        {"input": "1", "expect_contains": "Conventional"},

        # step 2: 파라미터 입력 (LOT, 기간, 공정)
        {"input": "LOT A001 공정 OPER_001 기간 20250101 ~ 20250131", "expect_contains": "조회"},

        # step 3: S3 추가 로딩 여부
        {"input": "아니오", "expect_contains": "전처리 도구"},

        # step 4: 전처리 도구 선택
        {"input": "1, 4", "expect_contains": "전처리 계획"},

        # step 5: 전처리 완료
        {"input": "완료", "expect_contains": "피처 분석"},

        # step 6: 피처 선택 + 예측 (SHOWING_FEATURES 상태에서는 text_input 사용)
        {"input": "col_3 >= 0.7 조건으로 예측해줘", "via": "feat", "expect_contains": "예측"},
    ]

    def test_full_flow(self):
        """Conventional 전체 흐름 테스트"""
        at = create_app()

        for i, step in enumerate(self.PROMPTS, 1):
            prompt = step["input"]
            via = step.get("via", "chat")
            at = send_message(at, prompt, via=via)
            response = get_last_assistant_message(at)
            state = get_current_state(at)

            print_step(i, prompt, response, state)

            if step.get("expect_contains"):
                assert step["expect_contains"] in response, (
                    f"Step {i}: 응답에 '{step['expect_contains']}' 없음\n"
                    f"실제 응답: {response[:200]}"
                )

    def test_workflow_selection(self):
        """워크플로우 선택만 테스트"""
        at = create_app()
        at = send_message(at, self.PROMPTS[0]["input"])
        response = get_last_assistant_message(at)
        assert "Conventional" in response

    def test_param_collection(self):
        """파라미터 수집 테스트 — 누락 시 재요청 확인"""
        at = create_app()
        at = send_message(at, "1")  # conventional 선택

        # 불완전한 파라미터
        at = send_message(at, "LOT A001")
        response = get_last_assistant_message(at)
        assert "누락" in response, f"누락 안내가 없음: {response[:200]}"


# =============================================================================
# MAP 경향성 워크플로우 테스트
# =============================================================================

class TestMAPWorkflow:
    """MAP 경향성 분석 워크플로우 E2E 테스트."""

    # ── 여기를 수정하세요 ──
    PROMPTS = [
        # step 1: MAP 선택
        {"input": "2", "expect_contains": "MAP"},

        # step 2: 파라미터 입력 (MAP은 lot_no 필수)
        {"input": "LOT M001 LOT_001 공정 OPER_001 기간 20250101 ~ 20250131", "expect_contains": "Fail"},

        # step 3: wafer 선택 (MAP_SHOWING_FAIL_CONCENTRATION에서는 text_input 사용)
        {"input": "1, 2", "via": "candidate", "expect_contains": "wafer"},

        # step 4: 전공정 merge 여부
        {"input": "스킵", "expect_contains": "완료"},
    ]

    def test_full_flow(self):
        """MAP 전체 흐름 테스트"""
        at = create_app()

        for i, step in enumerate(self.PROMPTS, 1):
            prompt = step["input"]
            via = step.get("via", "chat")
            at = send_message(at, prompt, via=via)
            response = get_last_assistant_message(at)
            state = get_current_state(at)

            print_step(i, prompt, response, state)

            if step.get("expect_contains"):
                assert step["expect_contains"] in response, (
                    f"Step {i}: 응답에 '{step['expect_contains']}' 없음\n"
                    f"실제 응답: {response[:200]}"
                )


# =============================================================================
# 수율 경향성 워크플로우 테스트
# =============================================================================

class TestYieldWorkflow:
    """수율 경향성 분석 워크플로우 E2E 테스트."""

    # ── 여기를 수정하세요 ──
    PROMPTS = [
        # step 1: 수율 선택
        {"input": "3", "expect_contains": "수율"},

        # step 2: 파라미터 입력
        {"input": "LOT Y001 공정 OPER_001 W20 기간 20250101 ~ 20250131", "expect_contains": "조회"},

        # step 3: 상세 요청
        {"input": "전체 보여줘", "expect_contains": None},

        # step 4: 종료
        {"input": "종료", "expect_contains": "완료"},
    ]

    def test_full_flow(self):
        """수율 전체 흐름 테스트"""
        at = create_app()

        for i, step in enumerate(self.PROMPTS, 1):
            prompt = step["input"]
            via = step.get("via", "chat")
            at = send_message(at, prompt, via=via)
            response = get_last_assistant_message(at)
            state = get_current_state(at)

            print_step(i, prompt, response, state)

            if step.get("expect_contains"):
                assert step["expect_contains"] in response, (
                    f"Step {i}: 응답에 '{step['expect_contains']}' 없음\n"
                    f"실제 응답: {response[:200]}"
                )


# =============================================================================
# 커스텀 프롬프트 테스트 (자유 입력)
# =============================================================================

class TestCustomPrompts:
    """자유롭게 프롬프트를 편집하여 테스트.

    PROMPTS 리스트만 수정하면 된다.
    expect_contains가 None이면 검증 없이 응답만 출력.
    """

    # ── 여기를 자유롭게 수정하세요 ──
    PROMPTS = [
        {"input": "1", "expect_contains": "Conventional"},
        {"input": "A001 LOT 분석해줘 기간은 20250101부터 20250131까지 공정은 OPER_001이야", "expect_contains": None},
        # 추가 프롬프트를 여기에 작성
        # {"input": "여기에 입력", "expect_contains": None},
    ]

    def test_custom_flow(self):
        """커스텀 프롬프트 순차 실행"""
        at = create_app()

        for i, step in enumerate(self.PROMPTS, 1):
            prompt = step["input"]
            via = step.get("via", "chat")
            at = send_message(at, prompt, via=via)
            response = get_last_assistant_message(at)
            state = get_current_state(at)

            print_step(i, prompt, response, state)

            if step.get("expect_contains"):
                assert step["expect_contains"] in response, (
                    f"Step {i}: 응답에 '{step['expect_contains']}' 없음\n"
                    f"실제 응답: {response[:200]}"
                )


# =============================================================================
# 엣지 케이스 테스트
# =============================================================================

class TestEdgeCases:
    """경계 조건 및 예외 상황 테스트."""

    def test_invalid_workflow_number(self):
        """잘못된 워크플로우 번호 입력"""
        at = create_app()
        at = send_message(at, "9")
        response = get_last_assistant_message(at)
        # 메뉴를 다시 보여줘야 함
        assert "분석" in response, f"메뉴 재표시 안됨: {response[:200]}"

    def test_empty_input(self):
        """빈 입력 처리"""
        at = create_app()
        at = send_message(at, " ")
        response = get_last_assistant_message(at)
        assert response  # 어떤 응답이든 있어야 함

    def test_korean_natural_language(self):
        """자연어 입력으로 워크플로우 선택"""
        at = create_app()
        at = send_message(at, "MAP 분석하고 싶어")
        response = get_last_assistant_message(at)
        assert "MAP" in response

    def test_date_formats(self):
        """다양한 날짜 형식 파싱"""
        at = create_app()
        at = send_message(at, "1")  # conventional

        # 다양한 날짜 형식
        at = send_message(at, "LOT A001 OPER_001 2025-01-01 ~ 2025/01/31")
        response = get_last_assistant_message(at)
        # 날짜가 파싱되었는지 확인
        print(f"날짜 파싱 결과:\n{response[:300]}")
