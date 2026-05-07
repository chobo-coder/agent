# Task 05: Chat UI

## Goal
Streamlit 채팅 인터페이스 + 사이드바 워크플로우 진행률

## Files
- `ui/chat.py`
- `ui/components.py`
- `ui/formatters.py`

## Steps
1. `render_chat_history(session)` — 전체 대화 렌더링
2. `render_sidebar(session)` — 상태별 진행률 + Reset 버튼
3. `render_step_result(result)` — StepResult를 채팅 내 표시
4. `format_dataframe(df)` — 큰 DataFrame 축약 표시
5. `render_figure(fig)` — matplotlib figure 렌더링
6. `multi_select_widget`, `threshold_slider`, `confirm_button` 등 위젯

## Acceptance Criteria
- [ ] 채팅 메시지가 올바른 역할(user/assistant)로 표시
- [ ] DataFrame이 `st.dataframe`으로 표시됨
- [ ] 차트가 `st.pyplot`으로 표시됨
- [ ] 사이드바에 현재 상태 강조 표시됨
- [ ] Reset 버튼 동작
