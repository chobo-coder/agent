# Task 05: Chat UI

## Goal
Streamlit 채팅 인터페이스 완성 — StepResult 혼합 렌더링, 인터랙티브 위젯, 에러 표시

---

## 현재 상태

- `ui/chat.py`: `render_chat_history()`, `render_sidebar()`, `render_step_result()` 기본 구현
- `ui/components.py`: 위젯 함수 4개
- `ui/formatters.py`: DataFrame/Figure/Table 포맷터

---

## 구현 상세

### 5-1. ChatMessage 데이터 모델 확장

현재 `session.chat_history`에 `{"role", "content"}` 딕셔너리만 저장.
StepResult의 테이블/차트를 함께 표시하려면 구조 확장 필요:

```python
# ui/chat.py 상단에 정의

from dataclasses import dataclass, field
from typing import Any

@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str  # 텍스트 요약
    dataframes: dict[str, str] = field(default_factory=dict)  # key -> session_state key
    figures: list[str] = field(default_factory=list)  # session_state figure keys
    widget_type: str | None = None  # "multi_select" | "slider" | "confirm" | None
    widget_options: dict[str, Any] = field(default_factory=dict)
    state_at_creation: str = ""  # WorkflowState name
```

`SessionManager`에 메시지 추가 메서드 확장:

```python
# core/session.py에 추가

def add_rich_message(self, role: str, content: str, step_result=None, widget=None):
    msg = {
        "role": role,
        "content": content,
        "df_keys": list(step_result.dataframes.keys()) if step_result else [],
        "has_figures": bool(step_result and step_result.figures),
        "widget": widget,  # {"type": "multi_select", "options": [...]}
        "state": self.current_state.name,
    }
    st.session_state.chat_history.append(msg)

    # figures를 session_state에 저장 (st.pyplot용)
    if step_result and step_result.figures:
        fig_key = f"fig_{len(st.session_state.chat_history)}"
        st.session_state[fig_key] = step_result.figures
```

### 5-2. 채팅 렌더링 개선

`ui/chat.py`:

```python
def render_chat_history(session: SessionManager) -> None:
    """모든 메시지를 렌더링 (텍스트 + 테이블 + 차트 + 위젯)"""
    for i, msg in enumerate(session.chat_history):
        with st.chat_message(msg["role"]):
            # 텍스트 표시
            st.markdown(msg["content"])

            # DataFrame 표시
            for df_key in msg.get("df_keys", []):
                df = session.get_dataframe(df_key)
                if df is not None:
                    with st.expander(f"데이터: {df_key}", expanded=False):
                        format_dataframe(df)

            # Figure 표시
            fig_key = f"fig_{i+1}"
            if fig_key in st.session_state:
                for fig in st.session_state[fig_key]:
                    render_figure(fig)

            # 인터랙티브 위젯 (마지막 메시지에서만 활성)
            widget = msg.get("widget")
            if widget and i == len(session.chat_history) - 1:
                _render_widget(widget, session)


def _render_widget(widget: dict, session: SessionManager) -> str | None:
    """분기점에서 사용자 입력을 받는 위젯 렌더링"""
    wtype = widget["type"]

    if wtype == "yes_no":
        col1, col2 = st.columns(2)
        with col1:
            if st.button(widget.get("yes_label", "예"), key="btn_yes"):
                return "yes"
        with col2:
            if st.button(widget.get("no_label", "아니오"), key="btn_no"):
                return "no"

    elif wtype == "multi_select":
        selected = st.multiselect(
            widget.get("label", "항목 선택"),
            widget["options"],
            key="widget_multiselect",
        )
        if st.button("확인", key="btn_confirm_select"):
            return json.dumps(selected)

    elif wtype == "slider_confirm":
        value = st.slider(
            widget.get("label", "값 선택"),
            min_value=widget.get("min", 0.0),
            max_value=widget.get("max", 1.0),
            value=widget.get("default", 0.5),
            step=widget.get("step", 0.05),
            key="widget_slider",
        )
        if st.button("확인", key="btn_confirm_slider"):
            return str(value)

    return None
```

### 5-3. 사이드바 진행률 개선

```python
def render_sidebar(session: SessionManager) -> None:
    with st.sidebar:
        st.header("Workflow Progress")

        sm = session.state_machine
        progress = sm.progress_percent  # Task 02에서 추가한 property
        st.progress(progress, text=f"{int(progress * 100)}% 완료")

        st.divider()

        # 단계별 상태 표시
        STAGE_LABELS = {
            "IDLE": "대기",
            "QUERYING_DATA": "데이터 조회 중",
            "SHOWING_QUERY_RESULTS": "조회 결과 확인",
            "AWAITING_LOAD_DECISION": "추가 로딩 결정",
            "LOADING_PARQUET": "S3 데이터 로딩",
            "SHOWING_DATA_OVERVIEW": "데이터 오버뷰",
            "AWAITING_PREPROCESS": "전처리 선택",
            "PREPROCESSING": "전처리 실행 중",
            "SHOWING_PREPROCESSED": "전처리 결과",
            "ANALYZING_FEATURES": "피처 분석 중",
            "SHOWING_FEATURES": "피처 분석 결과",
            "AWAITING_COMBINATIONS": "피처 조합 선택",
            "PREDICTING": "예측 실행 중",
            "SHOWING_PREDICTIONS": "예측 결과",
            "COMPLETED": "완료",
        }

        current = sm.state
        all_states = list(WorkflowState)
        current_idx = all_states.index(current)

        for i, state in enumerate(all_states):
            label = STAGE_LABELS.get(state.name, state.name)
            if i < current_idx:
                st.markdown(f"✓ ~~{label}~~")
            elif i == current_idx:
                st.markdown(f"**▶ {label}**")
            else:
                st.markdown(f"○ {label}")

        st.divider()

        # 현재 컨텍스트 정보
        product = session.get_metadata("current_product")
        if product:
            st.info(f"분석 제품: {product}")

        # 저장된 DataFrame 목록
        dfs = st.session_state.get("workflow_context", {})
        if dfs:
            st.caption("저장된 데이터:")
            for key, df in dfs.items():
                st.caption(f"  • {key}: {df.shape[0]}행 x {df.shape[1]}열")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("처음부터", type="secondary"):
                session.reset()
                st.rerun()
        with col2:
            if st.button("체크포인트 로드"):
                # TODO: 체크포인트 선택 UI
                pass
```

### 5-4. 에러 상태 표시

```python
# ui/chat.py에 추가

def render_error(error: Exception, state_name: str) -> None:
    """에러 발생 시 사용자에게 안내"""
    with st.chat_message("assistant"):
        st.error(f"오류 발생 ({state_name})")
        st.markdown(f"""
**에러 내용:** {str(error)}

다음 중 하나를 시도해보세요:
- 다시 요청해주세요
- "처음부터" 버튼으로 워크플로우를 재시작하세요
- 문제가 지속되면 관리자에게 문의하세요
        """)
```

### 5-5. app.py 통합 (UI + Orchestrator)

```python
# app.py 수정

def main():
    st.set_page_config(page_title="Data Analysis Agent", layout="wide")
    st.title("Data Analysis Agent")

    session = SessionManager()
    orchestrator = Orchestrator(session)

    render_sidebar(session)
    render_chat_history(session)

    user_input = st.chat_input("분석 요청을 입력하세요...")
    if user_input:
        session.add_message("user", user_input)
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            try:
                with st.spinner("처리 중..."):
                    result = orchestrator.handle_input(user_input)

                # 텍스트 요약
                st.markdown(result.summary)

                # DataFrame 표시
                for key, df in result.dataframes.items():
                    with st.expander(f"데이터: {key}", expanded=True):
                        format_dataframe(df)

                # 차트 표시
                for fig in result.figures:
                    render_figure(fig)

                # 메시지 저장
                session.add_rich_message("assistant", result.summary, step_result=result)

            except Exception as e:
                render_error(e, session.current_state.name)

        st.rerun()
```

---

## 파일 체크리스트

| 파일 | 액션 | 변경 내용 |
|------|------|----------|
| `ui/chat.py` | 수정 | ChatMessage 모델, 혼합 렌더링, 위젯, 에러 표시 |
| `ui/components.py` | 수정 | 위젯 key 관리, 상태 연동 |
| `ui/formatters.py` | 확인 | 현재 상태 유지 |
| `core/session.py` | 수정 | `add_rich_message()` 추가 |
| `app.py` | 수정 | 통합 렌더링 로직 |

---

## 완료 기준

- [ ] 채팅에 텍스트 + DataFrame + 차트가 동시 표시
- [ ] DataFrame은 expander로 접기/펼치기 가능
- [ ] 사이드바에 진행률 바 + 단계 목록 표시
- [ ] 분기점에서 버튼/멀티셀렉트 위젯 표시
- [ ] 에러 발생 시 에러 메시지 + 복구 안내 표시
- [ ] Reset 버튼으로 전체 초기화 동작
- [ ] `streamlit run app.py`로 전체 UI 확인
