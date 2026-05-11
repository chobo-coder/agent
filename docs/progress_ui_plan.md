# 실시간 진행 상태 UI 업데이트 계획

## 현재 문제

- `app.py`의 핸들러 함수(DB 조회, 전처리, 분석 등)가 실행되는 동안 사용자에게 아무런 피드백이 없음
- `st.spinner`, `st.status`, `st.progress` 등 Streamlit 제공 로딩 UI를 전혀 사용하지 않음
- DB 조회가 오래 걸리거나 대용량 데이터 전처리 시 사용자가 앱이 멈춘 것으로 오해할 수 있음

---

## 구현 방식

Streamlit `st.status` (expandable container + 단계별 업데이트)를 사용.
각 핸들러에 직접 `st.status` context manager를 추가 (A안 채택).

---

## @apply 수정 지시서

아래는 `app.py`에서 수정해야 하는 위치와 방법입니다.
**기존 로직은 변경하지 않고, `st.status` context manager로 감싸기만 합니다.**

---

### @apply 1: `_handle_collecting()` — 파라미터 추출

**파일:** `app.py`
**위치:** `_handle_collecting` 함수 내부, `_extract_params_with_llm()` 호출 부분
**방법:** LLM 파라미터 추출 호출을 `st.status`로 감싸기

```python
# before
parsed = _extract_params_with_llm(user_input, params)

# after
with st.status("조건을 분석하고 있습니다...", expanded=False) as status:
    status.update(label="입력에서 파라미터 추출 중...")
    parsed = _extract_params_with_llm(user_input, params)
    status.update(label="조건 분석 완료", state="complete")
```

---

### @apply 2: `_handle_collecting()` — Conventional DB 조회

**파일:** `app.py`
**위치:** `_handle_collecting` 함수 내부, 필수값 충족 후 conventional 분기 (`# conventional: 기존 로직`)
**방법:** QUERYING_DATA → SHOWING_QUERY_RESULTS 전이를 `st.status`로 감싸기

```python
# before
sm.transition_to(WorkflowState.QUERYING_DATA)
sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)

overview = _build_data_overview(params)
conditions = _format_conditions(params)

# after
with st.status("데이터를 조회하고 있습니다...", expanded=True) as status:
    status.update(label="SQL 쿼리 생성 중...")
    sm.transition_to(WorkflowState.QUERYING_DATA)
    status.update(label="DB에서 데이터 조회 중...")
    sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
    status.update(label="데이터 조회 완료", state="complete")

overview = _build_data_overview(params)
conditions = _format_conditions(params)
```

---

### @apply 3: `handle_user_input()` — S3 추가 로딩

**파일:** `app.py`
**위치:** `handle_user_input` 내 `SHOWING_QUERY_RESULTS` 상태, `if load:` 분기
**방법:** S3 로딩 전이를 `st.status`로 감싸기

```python
# before
sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
sm.transition_to(WorkflowState.LOADING_PARQUET)
sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
session.save_snapshot()

# after
with st.status("S3에서 데이터를 로딩하고 있습니다...", expanded=True) as status:
    status.update(label="S3 parquet 파일 탐색 중...")
    sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
    status.update(label="parquet 파일 읽는 중...")
    sm.transition_to(WorkflowState.LOADING_PARQUET)
    status.update(label="기존 데이터와 머지 중...")
    sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
    status.update(label="S3 로딩 완료", state="complete")
session.save_snapshot()
```

---

### @apply 4: `_handle_eda()` — EDA 실행

**파일:** `app.py`
**위치:** `_handle_eda` 함수 전체
**방법:** `run_eda()` 호출을 `st.status`로 감싸기

```python
# before
df = session.get_dataframe("query_result")
result = run_eda(df)

# after
df = session.get_dataframe("query_result")
with st.status("EDA 분석 중...", expanded=True) as status:
    status.update(label="결측치 분석 중...")
    result = run_eda(df)
    status.update(label="EDA 분석 완료", state="complete")
```

---

### @apply 5: `_apply_preprocess_plan()` — 전처리 적용 + Scanning

**파일:** `app.py`
**위치:** `_apply_preprocess_plan` 함수, `apply_plan()` ~ `run_threshold_scanning()` 구간 전체
**방법:** 전처리 적용 + scanning을 `st.status`로 감싸기

```python
# before
if plan and plan.actions and df is not None:
    result_df = apply_plan(df, plan)
    # ...
scanning_df = run_threshold_scanning(...)

# after
with st.status("전처리를 적용하고 있습니다...", expanded=True) as status:
    if plan and plan.actions and df is not None:
        for i, a in enumerate(plan.actions):
            status.update(label=f"[{i+1}/{len(plan.actions)}] {a.tool_name} 적용 중...")
        result_df = apply_plan(df, plan)
        # ... (기존 items/params 저장 로직 동일)
    else:
        result_df = df
        tool_names = []

    session.set_metadata("preprocess_plan", None)

    status.update(label="Threshold Scanning 실행 중...")
    scanning_df = run_threshold_scanning(...)
    session.set_dataframe("scanning_result", scanning_df)
    st.write(f"전처리 완료: {result_df.shape[0]:,}행 × {result_df.shape[1]}열" if result_df is not None else "")
    status.update(label="전처리 + Scanning 완료", state="complete")
```

---

### @apply 6: `handle_user_input()` — 예측 실행 (SHOWING_FEATURES 상태)

**파일:** `app.py`
**위치:** `handle_user_input` 내 `SHOWING_FEATURES` 상태, `compute_prediction_metrics()` ~ `plot_feature_scatter()` 구간
**방법:** 예측 지표 계산 + scatter plot을 `st.status`로 감싸기

```python
# before
metrics = compute_prediction_metrics(df, schema.TARGET_COLUMN, selections)
session.set_metadata("prediction_metrics", metrics)
plot_png = plot_feature_scatter(df, schema.TARGET_COLUMN, selections)
session.set_metadata("prediction_plot", plot_png)
sm.transition_to(WorkflowState.AWAITING_COMBINATIONS)
# ...

# after
with st.status("예측을 실행하고 있습니다...", expanded=True) as status:
    status.update(label="선택된 조건으로 지표 계산 중...")
    metrics = compute_prediction_metrics(df, schema.TARGET_COLUMN, selections)
    session.set_metadata("prediction_metrics", metrics)
    st.write(f"Screened: {metrics['screened']}건 / F1: {metrics['f1_score']}")

    status.update(label="Scatter Plot 생성 중...")
    plot_png = plot_feature_scatter(df, schema.TARGET_COLUMN, selections)
    session.set_metadata("prediction_plot", plot_png)

    sm.transition_to(WorkflowState.AWAITING_COMBINATIONS)
    sm.transition_to(WorkflowState.PREDICTING)
    sm.transition_to(WorkflowState.SHOWING_PREDICTIONS)
    session.save_snapshot()
    sm.transition_to(WorkflowState.COMPLETED)
    status.update(label="예측 완료", state="complete")
```

---

### @apply 7: `_handle_map_query()` — MAP LOT 조회

**파일:** `app.py`
**위치:** `_handle_map_query` 함수, `query_lot_fail_summary()` ~ `get_concentration_candidates()` 구간
**방법:** MAP 조회를 `st.status`로 감싸기

```python
# before
sm.transition_to(WorkflowState.MAP_QUERYING_LOT)
summary_df = map_pipeline.query_lot_fail_summary(params)
# ...
candidates = map_pipeline.get_concentration_candidates(summary_df)
sm.transition_to(WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION)

# after
with st.status("MAP 데이터를 조회하고 있습니다...", expanded=True) as status:
    status.update(label="LOT fail 집계 조회 중...")
    sm.transition_to(WorkflowState.MAP_QUERYING_LOT)
    summary_df = map_pipeline.query_lot_fail_summary(params)
    session.set_dataframe("map_fail_summary", summary_df)
    st.write(f"조회 완료: {len(summary_df)}건 (run × wafer)")

    status.update(label="Fail 몰림 분석 중...")
    candidates = map_pipeline.get_concentration_candidates(summary_df)
    session.set_metadata("map_concentration_candidates", candidates)
    status.update(label="MAP 조회 완료", state="complete")

sm.transition_to(WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION)
```

---

### @apply 8: `handle_user_input()` — Wafer Map 분석 (MAP_SHOWING_FAIL_CONCENTRATION 상태)

**파일:** `app.py`
**위치:** `handle_user_input` 내 `MAP_SHOWING_FAIL_CONCENTRATION` 상태, `query_wafer_map_detail()` ~ `plot_aggregate_map()` 구간
**방법:** wafer map 조회 + 분석 + 렌더링을 `st.status`로 감싸기

```python
# before
map_df = map_pipeline.query_wafer_map_detail(params, selected)
# ... (패턴 분석, aggregate, plot 생성)
sm.transition_to(WorkflowState.MAP_ANALYZING_WAFER_MAP)

# after
with st.status("Wafer Map을 분석하고 있습니다...", expanded=True) as status:
    status.update(label="Wafer Map 데이터 조회 중...")
    map_df = map_pipeline.query_wafer_map_detail(params, selected)
    session.set_dataframe("map_die_detail", map_df)

    status.update(label="패턴 분석 중 (edge/center/random)...")
    pattern = map_pipeline.classify_pattern(map_df)
    session.set_metadata("map_pattern", pattern)

    status.update(label="Aggregate Map 생성 중...")
    agg_df = map_pipeline.build_aggregate_fail_map(map_df)
    session.set_dataframe("map_aggregate", agg_df)

    # wafer별 plot
    plots = []
    for w in selected:
        status.update(label=f"Wafer Map 렌더링 중... ({w['wafer_id']})")
        png = map_pipeline.plot_wafer_map(map_df, w["wafer_id"], w["run_id"], layout)
        plots.append({"run_id": w["run_id"], "wafer_id": w["wafer_id"], "png": png})

    status.update(label="Aggregate Map 렌더링 중...")
    agg_png = map_pipeline.plot_aggregate_map(agg_df)
    plots.append({"run_id": "aggregate", "wafer_id": "all", "png": agg_png})
    session.set_metadata("map_plots", plots)
    status.update(label="MAP 분석 완료", state="complete")

sm.transition_to(WorkflowState.MAP_ANALYZING_WAFER_MAP)
```

---

### @apply 9: `_handle_map_prev_process_decision()` — 전공정 Merge + Similarity

**파일:** `app.py`
**위치:** `_handle_map_prev_process_decision` 함수, `merge_prev_process_data()` ~ `compute_feature_similarity()` 구간
**방법:** 전공정 분석을 `st.status`로 감싸기

```python
# before
map_df = session.get_dataframe("map_die_detail")
merged_df = map_pipeline.merge_prev_process_data(map_df, selected_options)
# ...
similarity_df = map_pipeline.compute_feature_similarity(merged_df, feature_cols)

# after
with st.status("전공정 데이터를 분석하고 있습니다...", expanded=True) as status:
    status.update(label="전공정 데이터 조회 + Merge 중...")
    map_df = session.get_dataframe("map_die_detail")
    merged_df = map_pipeline.merge_prev_process_data(map_df, selected_options)
    session.set_dataframe("map_prev_merged", merged_df)

    feature_cols = []
    for opt in selected_options:
        feature_cols.extend(opt["columns"])

    status.update(label="Feature Similarity 계산 중...")
    similarity_df = map_pipeline.compute_feature_similarity(merged_df, feature_cols)
    session.set_dataframe("map_similarity", similarity_df)
    status.update(label="전공정 분석 완료", state="complete")
```

---

### @apply 10: `_handle_yield_loading()` — 수율 Week 조회 + 전처리

**파일:** `app.py`
**위치:** `_handle_yield_loading` 함수, `resolve_weeks()` ~ `preprocess_yield()` 구간 전체
**방법:** 수율 조회 + 전처리를 `st.status`로 감싸기. week별 캐시/DB 상태 표시.

```python
# before
sm.transition_to(WorkflowState.YIELD_LOADING_DATA)
weeks = yield_pipeline.resolve_weeks(params)
raw_df = yield_pipeline.load_or_query(params, weeks)
# ...
sm.transition_to(WorkflowState.YIELD_PREPROCESSING)
# ...
summary = yield_pipeline.preprocess_yield(filtered_df)

# after
with st.status("수율 데이터를 조회하고 있습니다...", expanded=True) as status:
    sm.transition_to(WorkflowState.YIELD_LOADING_DATA)
    weeks = yield_pipeline.resolve_weeks(params)
    status.update(label=f"조회 대상: {', '.join(weeks)}")

    for i, week in enumerate(weeks):
        parquet_path = yield_pipeline.get_parquet_path(params["lot_cd"], week)
        if parquet_path.exists():
            status.update(label=f"[{i+1}/{len(weeks)}] {week} — 캐시 로드 중...")
        else:
            status.update(label=f"[{i+1}/{len(weeks)}] {week} — DB 조회 + 저장 중...")

    raw_df = yield_pipeline.load_or_query(params, weeks)
    session.set_dataframe("yield_raw", raw_df)
    st.write(f"로드 완료: {len(raw_df):,}행")

    sm.transition_to(WorkflowState.YIELD_PREPROCESSING)
    status.update(label="수율/불량률 계산 중...")
    filtered_df = yield_pipeline.filter_by_date(...)
    summary = yield_pipeline.preprocess_yield(filtered_df)
    # ... (session 저장)
    status.update(label="수율 데이터 준비 완료", state="complete")
```

---

## 적용 안 하는 곳

| 함수 | 이유 |
|------|------|
| `_handle_workflow_selection()` | 즉시 응답 (메뉴 파싱만) |
| `_handle_yield_request()` | 즉시 응답 (파싱 + 테이블 빌드) |
| `_parse_tool_selection()` | 순수 파싱 함수 |
| `handle_user_input()` 내 `SHOWING_DATA_OVERVIEW` | 전처리 미리보기는 즉시 응답 |

---

## 파일 변경 요약

| 파일 | @apply 수 | 변경 내용 |
|------|-----------|----------|
| `app.py` | 10개 | 각 핸들러에 `st.status` context manager 추가 |
| `ui/chat.py` | 0 | 변경 없음 |
| `pipeline/*.py` | 0 | 변경 없음 |
| `schema.py` | 0 | 변경 없음 |

---

## 참고 파일

| 파일 | 용도 |
|------|------|
| `docs/app_progress_ui.patch` | `app.py` 변경분 patch 파일. `git apply docs/app_progress_ui.patch`로 적용 가능 |
| `docs/progress_ui_plan.md` | 이 문서. @apply 1~10 수정 지시서 |

**루코드 적용 방법:**
1. 사내 코드의 `app.py`가 이미 다른 수정이 있어 patch가 충돌하면, 이 문서의 `@apply 1~10`을 참고하여 수동 적용
2. patch가 깨끗하게 적용되면: `git apply docs/app_progress_ui.patch`

---

## 완료 기준

- [x] `@apply 1` — 파라미터 추출 시 "조건을 분석하고 있습니다..." 표시
- [x] `@apply 2` — DB 조회 시 "데이터를 조회하고 있습니다..." 표시
- [x] `@apply 3` — S3 로딩 시 단계별 진행 표시
- [x] `@apply 4` — EDA 실행 시 "EDA 분석 중..." 표시
- [x] `@apply 5` — 전처리 시 도구별 진행 + Scanning 표시
- [x] `@apply 6` — 예측 시 지표 계산 + Scatter Plot 진행 표시
- [x] `@apply 7` — MAP LOT 조회 시 진행 표시
- [x] `@apply 8` — Wafer Map 분석 시 개별 wafer 진행 표시
- [x] `@apply 9` — 전공정 Merge + Similarity 진행 표시
- [x] `@apply 10` — 수율 week별 캐시/DB 구분 + 전처리 진행 표시
