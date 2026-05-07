# Architecture: Data Analysis Agent

## Overview

Streamlit 채팅 기반의 데이터 분석 에이전트. FSM(Finite State Machine)으로 워크플로우를 제어하고, LLM은 3개 분기점에서만 사용자 의도를 해석한다.

## System Architecture

```
┌─────────────────────────────────────────────────┐
│                   Streamlit UI                    │
│  (chat.py, components.py, formatters.py)         │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                 Orchestrator                      │
│  (state routing, LLM coordination)               │
└───┬──────────────┬───────────────┬──────────────┘
    │              │               │
┌───▼───┐   ┌─────▼─────┐   ┌────▼────┐
│  FSM  │   │    LLM    │   │Pipeline │
│       │   │ (3 roles) │   │Handlers │
└───────┘   └───────────┘   └────┬────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
              ┌─────▼───┐  ┌─────▼───┐  ┌─────▼───┐
              │SDK Wrap. │  │S3 Wrap. │  │Checkpts │
              └─────────┘  └─────────┘  └─────────┘
```

## Workflow States

```
IDLE → QUERYING_DATA → SHOWING_QUERY_RESULTS → [Decision]
  → AWAITING_LOAD_DECISION → LOADING_PARQUET → SHOWING_DATA_OVERVIEW → [Decision]
  → AWAITING_PREPROCESS → PREPROCESSING → SHOWING_PREPROCESSED
  → ANALYZING_FEATURES → SHOWING_FEATURES → [Decision]
  → AWAITING_COMBINATIONS → PREDICTING → SHOWING_PREDICTIONS → COMPLETED
```

## LLM Integration Points

| State | Role | Input | Output |
|-------|------|-------|--------|
| SHOWING_QUERY_RESULTS | Intent Classifier | User text | `{load_additional: bool}` |
| SHOWING_DATA_OVERVIEW | Parameter Extractor | User text | `{items: [...], params: {}}` |
| SHOWING_FEATURES | Parameter Extractor | User text | `{features: [...], threshold: float}` |
| All result states | Result Summarizer | Raw stats | Natural language summary |

## Data Flow

- DataFrames are stored in `st.session_state.workflow_context` (keyed by step name)
- Chat history stores only text summaries (no DataFrames)
- Checkpoints save DataFrames to disk as parquet for recovery

## Key Design Decisions

1. **FSM over free-form agent**: Fixed workflow ensures predictability; LLM only interprets at branching points
2. **StepResult as universal interface**: All handlers return the same structure
3. **Checkpoint after each data-producing step**: Enables workflow resume
4. **Separation of UI from logic**: Pipeline handlers are UI-agnostic; rendering happens in ui/ layer
