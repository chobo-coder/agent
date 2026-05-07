"""Main control loop: coordinates state machine, LLM, and pipeline.

워크플로우 3종을 Orchestrator가 라우팅:
  - conventional: 기존 분석 (전처리→피처→예측)
  - map_trend:    MAP 경향성 분석
  - equip_trend:  장비 경향성 분석

공통 구간 (파라미터 수집 → 조회 → 오버뷰)은 공유하고,
오버뷰 이후 워크플로우 유형에 따라 다른 핸들러 체인으로 분기.
"""

from core.session import SessionManager
from core.state_machine import WorkflowState, WorkflowType
from core.checkpoints import CheckpointManager
from llm.client import LLMClient
from llm.parser import ResponseParser
from llm.prompts import PromptBuilder
from pipeline.data_query import DataQueryHandler
from pipeline.data_loader import DataLoaderHandler
from pipeline.data_overview import DataOverviewHandler
from pipeline.preprocessing import PreprocessingHandler
from pipeline.feature_analysis import FeatureAnalysisHandler
from pipeline.prediction import PredictionHandler

# TODO: MAP 경향성 핸들러 import
# from pipeline.map_trend import (
#     MapParamHandler,       # MAP 파라미터 선택 (wafer, die 좌표 기준)
#     MapDataLoader,         # wafer map 데이터 로딩
#     MapAnalyzer,           # spatial pattern 분석 (클러스터링, edge/center 판별)
#     MapResultHandler,      # heatmap/시각화 결과 표시
#     MapCompareHandler,     # LOT 간 MAP 비교
# )

# TODO: 장비 경향성 핸들러 import
# from pipeline.equip_trend import (
#     EquipParamHandler,     # 장비/챔버/센서 선택
#     EquipDataLoader,       # 장비 센서 시계열 데이터 로딩
#     EquipTrendAnalyzer,    # 시계열 트렌드 분석 (drift, shift, SPC rule 위반)
#     EquipTrendResult,      # 시계열 차트/SPC 차트 표시
#     EquipCorrelation,      # 장비 파라미터 ↔ 불량률 상관 분석
# )


class StepResult:
    """Unified result from any pipeline step."""

    def __init__(
        self,
        dataframes: dict | None = None,
        figures: list | None = None,
        summary: str = "",
        metadata: dict | None = None,
    ):
        self.dataframes = dataframes or {}
        self.figures = figures or []
        self.summary = summary
        self.metadata = metadata or {}


class Orchestrator:
    """Drives the workflow by routing inputs to the right handler."""

    def __init__(self, session: SessionManager):
        self.session = session
        self.llm = LLMClient()
        self.parser = ResponseParser()
        self.prompts = PromptBuilder()
        self.checkpoints = CheckpointManager()

        # ── 공통 핸들러 (모든 워크플로우가 사용) ──
        self._common_handlers = {
            WorkflowState.QUERYING_DATA: DataQueryHandler(),
            WorkflowState.LOADING_PARQUET: DataLoaderHandler(),
            WorkflowState.SHOWING_DATA_OVERVIEW: DataOverviewHandler(),
        }

        # ── 워크플로우별 핸들러 ──
        self._workflow_handlers: dict[WorkflowType, dict] = {
            WorkflowType.CONVENTIONAL: {
                WorkflowState.PREPROCESSING: PreprocessingHandler(),
                WorkflowState.ANALYZING_FEATURES: FeatureAnalysisHandler(),
                WorkflowState.PREDICTING: PredictionHandler(),
            },

            # TODO: MAP 경향성 핸들러 등록
            # WorkflowType.MAP_TREND: {
            #     WorkflowState.MAP_SELECTING_PARAMS: MapParamHandler(),
            #     WorkflowState.MAP_LOADING_DATA: MapDataLoader(),
            #     WorkflowState.MAP_ANALYZING: MapAnalyzer(),
            #     WorkflowState.MAP_SHOWING_RESULTS: MapResultHandler(),
            #     WorkflowState.MAP_COMPARING: MapCompareHandler(),
            # },

            # TODO: 장비 경향성 핸들러 등록
            # WorkflowType.EQUIP_TREND: {
            #     WorkflowState.EQUIP_SELECTING_PARAMS: EquipParamHandler(),
            #     WorkflowState.EQUIP_LOADING_DATA: EquipDataLoader(),
            #     WorkflowState.EQUIP_TREND_ANALYZING: EquipTrendAnalyzer(),
            #     WorkflowState.EQUIP_SHOWING_TREND: EquipTrendResult(),
            #     WorkflowState.EQUIP_CORRELATION: EquipCorrelation(),
            # },
        }

    def _get_handler(self, state: WorkflowState):
        """현재 상태에 맞는 핸들러 반환 (공통 → 워크플로우별 순서로 탐색)"""
        handler = self._common_handlers.get(state)
        if handler:
            return handler

        wf_type = self.session.state_machine.workflow_type
        wf_handlers = self._workflow_handlers.get(wf_type, {})
        return wf_handlers.get(state)

    def handle_input(self, user_input: str) -> StepResult:
        """Process user input based on current workflow state."""
        sm = self.session.state_machine

        # 워크플로우 선택
        if sm.state == WorkflowState.SELECTING_WORKFLOW:
            return self._handle_workflow_selection(user_input)

        # At decision points, use LLM to classify intent
        if sm.is_decision_point:
            return self._handle_decision(user_input)

        # At IDLE, start new workflow
        if sm.state == WorkflowState.IDLE:
            return self._start_workflow(user_input)

        # Otherwise, auto-advance
        return self._auto_advance()

    def _handle_workflow_selection(self, user_input: str) -> StepResult:
        """사용자 입력에서 워크플로우 유형 판별"""
        # TODO: LLM 또는 키워드로 워크플로우 유형 분류
        # wf_type = self._classify_workflow(user_input)
        # self.session.state_machine.set_workflow_type(wf_type)
        # self.session.set_metadata("workflow_type", wf_type.value)

        # 현재: conventional 고정
        sm = self.session.state_machine
        sm.set_workflow_type(WorkflowType.CONVENTIONAL)
        self.session.set_metadata("workflow_type", WorkflowType.CONVENTIONAL.value)
        sm.transition_to(WorkflowState.COLLECTING_PARAMS)
        return StepResult(summary="기존 분석 워크플로우로 진행합니다.")

    # TODO: 워크플로우 유형 분류기
    # def _classify_workflow(self, user_input: str) -> WorkflowType:
    #     """사용자 입력에서 워크플로우 유형 판별.
    #
    #     키워드 기반 분류:
    #       - "MAP", "wafer map", "공간 패턴" → MAP_TREND
    #       - "장비", "챔버", "센서", "경향", "drift" → EQUIP_TREND
    #       - 그 외 → CONVENTIONAL
    #
    #     LLM 기반 분류:
    #       prompt = prompts.build_workflow_classification(user_input)
    #       response = llm.complete(prompt)
    #       return parser.parse_workflow_type(response)
    #     """
    #     text_lower = user_input.lower()
    #     if any(kw in text_lower for kw in ["map", "wafer", "공간", "다이"]):
    #         return WorkflowType.MAP_TREND
    #     if any(kw in text_lower for kw in ["장비", "챔버", "센서", "drift", "경향"]):
    #         return WorkflowType.EQUIP_TREND
    #     return WorkflowType.CONVENTIONAL

    def _start_workflow(self, user_input: str) -> StepResult:
        """워크플로우 시작 → 유형 선택으로 진입"""
        self.session.state_machine.transition_to(WorkflowState.SELECTING_WORKFLOW)
        return self._handle_workflow_selection(user_input)

    def _handle_decision(self, user_input: str) -> StepResult:
        """Use LLM to classify user intent at decision points."""
        state = self.session.state_machine.state
        prompt = self.prompts.build_decision_prompt(state, user_input)
        response = self.llm.complete(prompt)
        decision = self.parser.parse_decision(state, response)

        next_state = self._resolve_next_state(state, decision)
        self.session.state_machine.transition_to(next_state)

        return self._execute_current_step()

    def _auto_advance(self) -> StepResult:
        """Advance to the next automatic state."""
        sm = self.session.state_machine
        next_state = sm.get_next_auto_state()
        if next_state:
            sm.transition_to(next_state)
        return self._execute_current_step()

    def _execute_current_step(self) -> StepResult:
        """Run the handler for the current state."""
        state = self.session.state_machine.state
        handler = self._get_handler(state)

        if handler is None:
            return StepResult(summary="대기 중입니다. 입력을 기다립니다.")

        result = handler.execute(self.session)

        # Save dataframes to session
        for key, df in result.dataframes.items():
            self.session.set_dataframe(key, df)

        # Checkpoint if needed
        if result.dataframes:
            self.checkpoints.save(state, result.dataframes)

        # Summarize with LLM
        if result.summary:
            prompt = self.prompts.build_summary_prompt(result.summary)
            result.summary = self.llm.complete(prompt)

        # Auto-advance after execution
        next_state = self.session.state_machine.get_next_auto_state()
        if next_state:
            self.session.state_machine.transition_to(next_state)

        return result

    def _resolve_next_state(
        self, current: WorkflowState, decision: dict
    ) -> WorkflowState:
        """Determine next state based on decision at a branching point."""
        if current == WorkflowState.SHOWING_QUERY_RESULTS:
            if decision.get("load_additional"):
                return WorkflowState.AWAITING_LOAD_DECISION
            return WorkflowState.SHOWING_DATA_OVERVIEW

        # ── conventional ──
        if current == WorkflowState.SHOWING_DATA_OVERVIEW:
            return WorkflowState.AWAITING_PREPROCESS

        if current == WorkflowState.SHOWING_FEATURES:
            return WorkflowState.AWAITING_COMBINATIONS

        # TODO: MAP 경향성 분기 판단
        # if current == WorkflowState.MAP_SHOWING_RESULTS:
        #     if decision.get("compare_lots"):
        #         return WorkflowState.MAP_COMPARING
        #     return WorkflowState.COMPLETED

        # TODO: 장비 경향성 분기 판단
        # if current == WorkflowState.EQUIP_SHOWING_TREND:
        #     if decision.get("analyze_correlation"):
        #         return WorkflowState.EQUIP_CORRELATION
        #     return WorkflowState.COMPLETED

        return WorkflowState.IDLE
