"""LLM 프롬프트 테스트 에이전트.

각 프롬프트 템플릿에 대해 다양한 사용자 입력을 시뮬레이션하고,
LLM 응답을 파싱하여 기대값과 비교. 예외 상황을 자동으로 디버깅.

실행:
  python test_prompting.py                    # 전체 테스트
  python test_prompting.py --suite params     # 파라미터 추출만
  python test_prompting.py --suite features   # 피처 선택만
  python test_prompting.py --suite decisions  # 의사결정만
  python test_prompting.py --interactive      # 대화형 디버깅

환경:
  .env에 LLM_API_KEY 필요 (없으면 regex fallback만 테스트)
"""

import argparse
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, ".")

from llm.prompts import PromptBuilder, SYSTEM_PROMPT
from llm.parser import ResponseParser
from core.state_machine import WorkflowState
import schema


# =============================================================================
# 테스트 케이스 정의
# =============================================================================

@dataclass
class TestCase:
    """단일 프롬프트 테스트 케이스."""
    name: str
    user_input: str
    expected: dict[str, Any]
    suite: str  # "params" | "features" | "decisions"
    description: str = ""
    # 검증 모드: "exact" (값 일치) | "keys" (키 존재만) | "partial" (일부 값 일치)
    check_mode: str = "partial"


@dataclass
class TestResult:
    """테스트 결과."""
    case: TestCase
    passed: bool
    llm_response: str = ""
    parsed: dict = field(default_factory=dict)
    fallback_parsed: dict = field(default_factory=dict)
    error: str = ""
    duration: float = 0.0


# ── 파라미터 추출 테스트 ──
PARAM_TESTS = [
    TestCase(
        name="기본 전체 입력",
        user_input="LOT A01 oper_001 20250101 20250331 cat2 분석해줘",
        expected={"lot_cd": "A01", "oper": "OPER_001", "from_date": "20250101", "end_date": "20250331", "cat": "cat2"},
        suite="params",
        description="모든 파라미터가 한 문장에 있는 기본 케이스 (oper는 대문자 정규화)",
    ),
    TestCase(
        name="날짜 하이픈 포맷",
        user_input="LOT B02 oper_002 2025-01-01부터 2025-03-31까지 분석",
        expected={"lot_cd": "B02", "from_date": "20250101", "end_date": "20250331"},
        suite="params",
        description="하이픈 날짜를 YYYYMMDD로 변환하는지",
    ),
    TestCase(
        name="카테고리 없음",
        user_input="A01 oper_001 20250401 20250630",
        expected={"lot_cd": "A01", "from_date": "20250401", "end_date": "20250630", "cat": None},
        suite="params",
        description="cat 미입력 시 null 처리",
    ),
    TestCase(
        name="부분 입력 (LOT만)",
        user_input="LOT C03으로 분석해줘",
        expected={"lot_cd": "C03", "from_date": None, "end_date": None},
        suite="params",
        description="LOT만 있고 나머지 누락",
        check_mode="partial",
    ),
    TestCase(
        name="자연어 날짜 (상반기) [LLM전용]",
        user_input="LOT A01 oper_001 2025년 상반기 데이터 분석",
        expected={"lot_cd": "A01"},
        suite="params",
        description="'상반기' → 01~06 변환은 LLM만 가능. fallback은 LOT만 추출",
        check_mode="partial",
    ),
    TestCase(
        name="한국어 혼합 입력",
        user_input="A01 공정은 oper_001이고 기간은 1월부터 3월까지 cat1으로 분석해줘",
        expected={"lot_cd": "A01", "oper": "OPER_001", "cat": "cat1"},
        suite="params",
        description="자연스러운 한국어 문장에서 추출 (한국어 조사 제거)",
        check_mode="partial",
    ),
    TestCase(
        name="슬래시 날짜",
        user_input="A01 oper_001 2025/04/01 2025/06/30 분석 부탁",
        expected={"lot_cd": "A01", "from_date": "20250401", "end_date": "20250630"},
        suite="params",
        description="슬래시 구분 날짜 처리",
    ),
    TestCase(
        name="모호한 입력",
        user_input="데이터 좀 봐줘",
        expected={"lot_cd": None, "oper": None, "from_date": None, "end_date": None},
        suite="params",
        description="파라미터 정보가 전혀 없는 입력",
    ),
    TestCase(
        name="MAP 파라미터 (lot_no 포함)",
        user_input="LOT A01 LOT_001 oper_001 20250101 20250331 분석",
        expected={"lot_cd": "A01"},
        suite="params",
        description="MAP 워크플로우용 lot_no가 포함된 입력",
        check_mode="partial",
    ),
    TestCase(
        name="잡음 포함 입력",
        user_input="음... A01으로 해볼까 oper_001 그리고 20250101에서 20250331까지 해줘 고마워",
        expected={"lot_cd": "A01", "oper": "OPER_001", "from_date": "20250101", "end_date": "20250331"},
        suite="params",
        description="불필요한 텍스트 사이에서 파라미터 추출",
        check_mode="partial",
    ),
]

# ── 피처 선택 테스트 ──
FEATURE_TESTS = [
    TestCase(
        name="단일 피처 + 조건 + 임계값",
        user_input="col_3 >= 0.7 조건으로 예측해줘",
        expected={"selections": [{"feature": "col_3", "threshold": 0.7, "condition": ">="}]},
        suite="features",
    ),
    TestCase(
        name="복수 피처 (독립 조건)",
        user_input="col_3 >= 0.7, col_4 <= 0.3 조건으로 예측해줘",
        expected={"selections": [
            {"feature": "col_3", "threshold": 0.7, "condition": ">="},
            {"feature": "col_4", "threshold": 0.3, "condition": "<="},
        ]},
        suite="features",
    ),
    TestCase(
        name="피처만 (조건/임계값 없음)",
        user_input="col_3, col_4로 예측해줘",
        expected={"selections": [
            {"feature": "col_3", "threshold": None, "condition": None},
            {"feature": "col_4", "threshold": None, "condition": None},
        ]},
        suite="features",
    ),
    TestCase(
        name="공통 임계값",
        user_input="col_3이랑 col_4로 0.7 기준 예측",
        expected={"selections": [
            {"feature": "col_3", "threshold": 0.7},
            {"feature": "col_4", "threshold": 0.7},
        ]},
        suite="features",
        check_mode="partial",
    ),
    TestCase(
        name="존재하지 않는 피처",
        user_input="nonexistent_col >= 0.5 예측",
        expected={"selections": []},
        suite="features",
        description="AVAILABLE_FEATURES에 없는 피처 → 무시",
    ),
    TestCase(
        name="모호한 피처 요청",
        user_input="적당한 피처로 예측해줘",
        expected={"selections": []},
        suite="features",
        description="구체적 피처명 없는 입력",
    ),
]

# ── 의사결정 테스트 ──
DECISION_TESTS = [
    TestCase(
        name="추가 로딩 긍정",
        user_input="예, 추가 로딩해줘",
        expected={"load_additional": True},
        suite="decisions",
        check_mode="partial",
    ),
    TestCase(
        name="추가 로딩 부정",
        user_input="아니오, 충분합니다",
        expected={"load_additional": False},
        suite="decisions",
        check_mode="partial",
    ),
    TestCase(
        name="추가 로딩 모호",
        user_input="잘 모르겠는데...",
        expected={},
        suite="decisions",
        description="모호한 응답 처리",
        check_mode="keys",
    ),
    TestCase(
        name="전처리 선택 (결측치 평균)",
        user_input="결측치 평균으로 채우고 스케일링해줘",
        expected={"items": ["fill_mean", "standard_scaling"]},
        suite="decisions",
        description="키워드 '평균' → fill_mean, '스케일링' → standard_scaling",
        check_mode="partial",
    ),
    TestCase(
        name="전처리 선택 (전부)",
        user_input="전부 다 해줘",
        expected={},
        suite="decisions",
        description="'전부' → 모든 도구 선택 (13개)",
        check_mode="keys",
    ),
]

ALL_TESTS = PARAM_TESTS + FEATURE_TESTS + DECISION_TESTS


# =============================================================================
# 테스트 실행 엔진
# =============================================================================

class PromptTestAgent:
    """LLM 프롬프트를 테스트하고 디버깅하는 에이전트."""

    def __init__(self, use_llm: bool = True, verbose: bool = True):
        self.prompts = PromptBuilder()
        self.parser = ResponseParser()
        self.verbose = verbose
        self.use_llm = use_llm
        self.llm = None
        self.results: list[TestResult] = []

        if use_llm:
            try:
                from llm.client import LLMClient
                self.llm = LLMClient()
                self._log("LLM 클라이언트 초기화 성공")
            except Exception as e:
                self._log(f"LLM 사용 불가: {e}")
                self._log("regex fallback만 테스트합니다.")
                self.use_llm = False

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    # ── 프롬프트 생성 ──

    def _build_prompt(self, case: TestCase) -> str:
        """테스트 케이스에 맞는 프롬프트 생성."""
        if case.suite == "params":
            return self.prompts.build_param_extraction(case.user_input, {})
        elif case.suite == "features":
            return self.prompts._build_combination_prompt(case.user_input)
        elif case.suite == "decisions":
            # decision은 상태에 따라 분기
            if "로딩" in case.user_input or "충분" in case.user_input or "모르겠" in case.user_input:
                return self.prompts._build_load_decision_prompt(case.user_input)
            else:
                return self.prompts._build_preprocess_decision_prompt(case.user_input)
        return case.user_input

    # ── LLM 호출 ──

    def _call_llm(self, prompt: str) -> str:
        """LLM 호출. 실패 시 빈 문자열 반환."""
        if not self.llm:
            return ""
        return self.llm.complete(prompt, system=SYSTEM_PROMPT)

    # ── regex fallback 호출 ──

    def _call_fallback(self, case: TestCase) -> dict:
        """regex fallback 파서 호출."""
        if case.suite == "params":
            from app import _parse_params_fallback
            return _parse_params_fallback(case.user_input)
        elif case.suite == "features":
            from app import _parse_feature_selections_fallback
            results = _parse_feature_selections_fallback(case.user_input)
            return {"selections": results}
        elif case.suite == "decisions":
            # load decision vs preprocess decision 분기
            if "items" in case.expected:
                from app import _parse_tool_selection
                tools = _parse_tool_selection(case.user_input)
                return {"items": [t["id"] for t in tools]}
            else:
                from app import _parse_yes_no
                return {"load_additional": _parse_yes_no(case.user_input)}
        return {}

    # ── 검증 ──

    def _validate(self, parsed: dict, expected: dict, mode: str) -> tuple[bool, list[str]]:
        """파싱 결과와 기대값 비교. (통과 여부, 불일치 목록)"""
        mismatches = []

        if mode == "keys":
            # 키 존재만 확인
            for key in expected:
                if key not in parsed:
                    mismatches.append(f"키 누락: {key}")
            return len(mismatches) == 0, mismatches

        for key, exp_val in expected.items():
            act_val = parsed.get(key)

            if key == "selections" and isinstance(exp_val, list):
                # selections 배열 비교
                if not isinstance(act_val, list):
                    mismatches.append(f"selections: list 아님 (got {type(act_val).__name__})")
                    continue
                if mode == "exact" and len(act_val) != len(exp_val):
                    mismatches.append(f"selections 길이: {len(exp_val)} expected, {len(act_val)} got")
                for i, exp_sel in enumerate(exp_val):
                    if i >= len(act_val):
                        mismatches.append(f"selections[{i}]: 누락")
                        continue
                    act_sel = act_val[i]
                    for sk, sv in exp_sel.items():
                        av = act_sel.get(sk)
                        if mode == "partial" and sv is None:
                            continue
                        if av != sv:
                            mismatches.append(f"selections[{i}].{sk}: {sv!r} expected, {av!r} got")
                continue

            if mode == "partial" and exp_val is None:
                continue

            if act_val != exp_val:
                mismatches.append(f"{key}: {exp_val!r} expected, {act_val!r} got")

        return len(mismatches) == 0, mismatches

    # ── 단일 테스트 실행 ──

    def run_test(self, case: TestCase) -> TestResult:
        """단일 테스트 케이스 실행."""
        result = TestResult(case=case, passed=False)
        start = time.time()

        try:
            # 1) regex fallback 테스트
            fallback_parsed = self._call_fallback(case)
            result.fallback_parsed = fallback_parsed

            # 2) LLM 테스트
            if self.use_llm:
                prompt = self._build_prompt(case)
                llm_response = self._call_llm(prompt)
                result.llm_response = llm_response
                parsed = self.parser._extract_json(llm_response)
                result.parsed = parsed

                # LLM 결과 검증
                passed, mismatches = self._validate(parsed, case.expected, case.check_mode)
                result.passed = passed

                if not passed:
                    result.error = "; ".join(mismatches)
            else:
                # fallback만 검증
                result.parsed = fallback_parsed
                passed, mismatches = self._validate(fallback_parsed, case.expected, case.check_mode)
                result.passed = passed
                if not passed:
                    result.error = "; ".join(mismatches)

        except Exception as e:
            result.error = f"Exception: {e}\n{traceback.format_exc()}"

        result.duration = time.time() - start
        self.results.append(result)
        return result

    # ── 전체 스위트 실행 ──

    def run_suite(self, suite: str | None = None) -> list[TestResult]:
        """테스트 스위트 실행."""
        cases = ALL_TESTS if suite is None else [t for t in ALL_TESTS if t.suite == suite]

        self._log(f"\n{'='*60}")
        self._log(f"  Prompt Test Agent — {len(cases)} 케이스")
        self._log(f"  모드: {'LLM + Fallback' if self.use_llm else 'Fallback only'}")
        self._log(f"{'='*60}\n")

        results = []
        for i, case in enumerate(cases, 1):
            result = self.run_test(case)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            icon = "o" if result.passed else "x"
            self._log(f"  [{icon}] {i:2d}. {case.name} ({result.duration:.2f}s) — {status}")

            if not result.passed and self.verbose:
                self._log(f"       입력: {case.user_input}")
                self._log(f"       기대: {case.expected}")
                self._log(f"       결과: {result.parsed}")
                if result.fallback_parsed != result.parsed:
                    self._log(f"       fallback: {result.fallback_parsed}")
                self._log(f"       오류: {result.error}")

        self._print_summary(results)
        return results

    def _print_summary(self, results: list[TestResult]) -> None:
        """결과 요약 출력."""
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        total = len(results)
        avg_time = sum(r.duration for r in results) / total if total > 0 else 0

        self._log(f"\n{'='*60}")
        self._log(f"  결과: {passed}/{total} 통과 | {failed} 실패 | 평균 {avg_time:.2f}s")
        self._log(f"{'='*60}")

        # 실패 케이스 디버그 리포트
        failures = [r for r in results if not r.passed]
        if failures:
            self._log(f"\n{'─'*60}")
            self._log("  실패 케이스 디버그 리포트")
            self._log(f"{'─'*60}")

            for r in failures:
                self._log(f"\n  [{r.case.suite}] {r.case.name}")
                self._log(f"  입력: \"{r.case.user_input}\"")
                if r.case.description:
                    self._log(f"  설명: {r.case.description}")
                self._log(f"  기대값: {json.dumps(r.case.expected, ensure_ascii=False)}")

                if self.use_llm and r.llm_response:
                    self._log(f"  LLM 원문: {r.llm_response[:200]}")
                    self._log(f"  LLM 파싱: {json.dumps(r.parsed, ensure_ascii=False)}")

                self._log(f"  Fallback: {json.dumps(r.fallback_parsed, ensure_ascii=False)}")
                self._log(f"  오류: {r.error}")

                # 디버그 제안
                self._suggest_fix(r)

    def _suggest_fix(self, result: TestResult) -> None:
        """실패 원인을 분석하고 수정 제안."""
        case = result.case
        parsed = result.parsed
        fallback = result.fallback_parsed

        if case.suite == "params":
            for key in ["lot_cd", "oper", "from_date", "end_date", "cat"]:
                exp = case.expected.get(key)
                if exp is None:
                    continue
                if parsed.get(key) != exp and fallback.get(key) != exp:
                    self._log(f"  [제안] '{key}' 추출 실패 → regex 패턴 또는 LLM 프롬프트 예시 보강 필요")
                elif parsed.get(key) != exp and fallback.get(key) == exp:
                    self._log(f"  [제안] '{key}': LLM 실패, fallback 성공 → 프롬프트 예시에 유사 케이스 추가")
                elif parsed.get(key) == exp and fallback.get(key) != exp:
                    self._log(f"  [제안] '{key}': LLM 성공, fallback 실패 → _parse_params_fallback regex 보강")

        elif case.suite == "features":
            exp_sels = case.expected.get("selections", [])
            act_sels = parsed.get("selections", [])
            if len(act_sels) != len(exp_sels):
                self._log(f"  [제안] 피처 수 불일치 ({len(exp_sels)} vs {len(act_sels)}) → 프롬프트 예시 추가 또는 regex 패턴 수정")

    # ── 대화형 디버깅 ──

    def interactive_debug(self) -> None:
        """대화형 프롬프트 디버깅 모드."""
        self._log(f"\n{'='*60}")
        self._log("  대화형 프롬프트 디버깅")
        self._log(f"  명령어: params / features / decision_load / decision_preprocess / quit")
        self._log(f"{'='*60}\n")

        while True:
            mode = input("모드 선택> ").strip().lower()
            if mode in ("quit", "q", "exit"):
                break

            user_input = input("사용자 입력> ").strip()
            if not user_input:
                continue

            # 프롬프트 생성
            if mode == "params":
                prompt = self.prompts.build_param_extraction(user_input, {})
            elif mode == "features":
                prompt = self.prompts._build_combination_prompt(user_input)
            elif mode == "decision_load":
                prompt = self.prompts._build_load_decision_prompt(user_input)
            elif mode == "decision_preprocess":
                prompt = self.prompts._build_preprocess_decision_prompt(user_input)
            else:
                print(f"알 수 없는 모드: {mode}")
                continue

            print(f"\n--- 프롬프트 ({len(prompt)}자) ---")
            print(prompt[:500] + ("..." if len(prompt) > 500 else ""))

            # fallback
            print(f"\n--- Regex Fallback ---")
            if mode == "params":
                from app import _parse_params_fallback
                fb = _parse_params_fallback(user_input)
            elif mode == "features":
                from app import _parse_feature_selections_fallback
                fb = {"selections": _parse_feature_selections_fallback(user_input)}
            else:
                from app import _parse_yes_no
                fb = {"result": _parse_yes_no(user_input)}
            print(json.dumps(fb, ensure_ascii=False, indent=2))

            # LLM
            if self.use_llm:
                print(f"\n--- LLM 호출 ---")
                try:
                    start = time.time()
                    response = self._call_llm(prompt)
                    elapsed = time.time() - start
                    print(f"원문 ({elapsed:.2f}s): {response}")
                    parsed = self.parser._extract_json(response)
                    print(f"파싱: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
                except Exception as e:
                    print(f"LLM 오류: {e}")
            else:
                print("\n(LLM 미사용 — API 키 없음)")

            print()


# =============================================================================
# 메인
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="LLM 프롬프트 테스트 에이전트")
    parser.add_argument("--suite", choices=["params", "features", "decisions"],
                        help="특정 테스트 스위트만 실행")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="대화형 디버깅 모드")
    parser.add_argument("--no-llm", action="store_true",
                        help="LLM 없이 regex fallback만 테스트")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="통과 케이스 숨기고 실패만 표시")
    args = parser.parse_args()

    agent = PromptTestAgent(
        use_llm=not args.no_llm,
        verbose=True,
    )

    if args.interactive:
        agent.interactive_debug()
    else:
        results = agent.run_suite(args.suite)
        # exit code: 실패 수
        failures = sum(1 for r in results if not r.passed)
        sys.exit(min(failures, 1))


if __name__ == "__main__":
    main()
