# Task 04: Pipeline Steps

## Goal
6개 파이프라인 핸들러 + 2개 wrapper 구현

## Files
- `pipeline/data_query.py`
- `pipeline/data_loader.py`
- `pipeline/data_overview.py`
- `pipeline/preprocessing.py`
- `pipeline/feature_analysis.py`
- `pipeline/prediction.py`
- `wrappers/sdk_wrapper.py`
- `wrappers/s3_wrapper.py`
- `tests/test_pipeline.py`

## Steps

### Wrappers
1. `SDKWrapper.execute_query(sql)` — 사내 SDK 연동 (실제 구현 필요)
2. `S3Wrapper.read_parquet(prefix)` — boto3로 S3 parquet 읽기

### Handlers (모두 BaseHandler 상속, execute(session) → StepResult)
3. `DataQueryHandler` — SQL 빌드 + 실행
4. `DataLoaderHandler` — S3 로딩 + 기존 데이터 머지
5. `DataOverviewHandler` — describe(), 결측치, 기본 통계
6. `PreprocessingHandler` — missing/outlier/encoding/scaling/selection
7. `FeatureAnalysisHandler` — 상관분석 + heatmap
8. `PredictionHandler` — 피처 조합 점수 + threshold 적용

### Tests
9. Mock wrapper로 각 핸들러 입출력 검증
10. 전처리 각 옵션 단위 테스트

## Acceptance Criteria
- [ ] 모든 핸들러가 `StepResult` 반환
- [ ] Mock 테스트에서 DataFrame shape 올바름
- [ ] 상관분석 figure 생성됨
- [ ] `pytest tests/test_pipeline.py` 통과
