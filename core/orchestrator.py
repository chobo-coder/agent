"""Main control loop: coordinates state machine, LLM, and pipeline."""

from core.session import SessionManager
from core.state_machine import WorkflowState
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

        self._handlers = {
            WorkflowState.QUERYING_DATA: DataQueryHandler(),
            WorkflowState.LOADING_PARQUET: DataLoaderHandler(),
            WorkflowState.SHOWING_DATA_OVERVIEW: DataOverviewHandler(),
            WorkflowState.PREPROCESSING: PreprocessingHandler(),
            WorkflowState.ANALYZING_FEATURES: FeatureAnalysisHandler(),
            WorkflowState.PREDICTING: PredictionHandler(),
        }

    def handle_input(self, user_input: str) -> StepResult:
        """Process user input based on current workflow state."""
        sm = self.session.state_machine

        # At decision points, use LLM to classify intent
        if sm.is_decision_point:
            return self._handle_decision(user_input)

        # At IDLE, start new workflow
        if sm.state == WorkflowState.IDLE:
            return self._start_workflow(user_input)

        # Otherwise, auto-advance
        return self._auto_advance()

    def _start_workflow(self, user_input: str) -> StepResult:
        """Parse product from input and start querying."""
        prompt = self.prompts.build_product_extraction(user_input)
        response = self.llm.complete(prompt)
        product = self.parser.extract_product(response)

        self.session.set_metadata("current_product", product)
        self.session.state_machine.transition_to(WorkflowState.QUERYING_DATA)

        return self._execute_current_step()

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
        handler = self._handlers.get(state)

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

        if current == WorkflowState.SHOWING_DATA_OVERVIEW:
            return WorkflowState.AWAITING_PREPROCESS

        if current == WorkflowState.SHOWING_FEATURES:
            return WorkflowState.AWAITING_COMBINATIONS

        return WorkflowState.IDLE
