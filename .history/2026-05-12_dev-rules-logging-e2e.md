# 2026-05-12: 개발 규칙 정비 + 로깅 계획 + E2E 테스트

## 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `CLAUDE.md` | 개발 환경 제약 + 파일 소유권 + app.py 공유 규칙 전면 개정 |
| `docs/logging_plan.md` | 로깅 구현 계획서 (신규) |
| `test_workflow_e2e.py` | 워크플로우 E2E 테스트 스크립트 (신규) |

## 1. CLAUDE.md 개정 — 개발 환경 제약 및 파일 소유권

### 핵심 변경
- **단방향 동기화 한계 명시**: Claude → Roo만 가능, 역방향 불가
- **파일 소유권 테이블 추가**: Claude/Roo 각각의 파일과 수정 범위 명확화
- **app.py 공유 규칙 4가지**:
  1. Claude는 UI/흐름만 수정
  2. Roo는 데이터 처리만 수정
  3. Claude는 pipeline 호출 시 mock 호환 패턴 유지
  4. 함수 시그니처 변경 시 `pipeline/_interfaces.py`에 명시
- **핵심 규칙 개정**: 인터페이스 안정성, mock 기반 테스트, sync-roo가 유일한 소통 채널

### Roo 반영 사항
- `CLAUDE.md`의 파일 소유권 규칙을 참고하여 수정 범위 준수
- schema.py, pipeline/*.py, wrappers/*.py는 Roo가 자유롭게 수정 가능
- app.py 수정 시 **파이프라인 호출부, 실제 데이터 처리 로직** 영역만 변경

## 2. 로깅 구현 계획서 — `docs/logging_plan.md`

### 9개 로깅 영역
1. **Pipeline** (`agent.pipeline`) — 함수 진입/완료/에러, 실행 시간, 입출력 shape
2. **SQL** (`agent.sql`) — 쿼리 전문, 바인드 파라미터, 실행 시간, 반환 row 수
3. **LLM** (`agent.llm`) — 프롬프트 전문, 응답 전문, 파싱 결과, 토큰 사용량
4. **FSM** (`agent.fsm`) — 상태 전이 성공/거부, 워크플로우 시작/종료
5. **데이터 품질** (`agent.data`) — DataFrame shape, null 비율, 컬럼 불일치, 전처리 전후 비교
6. **Wrapper** (`agent.wrapper`) — SDK/S3 호출 엔드포인트, 응답 시간, 재시도
7. **사용자 입력** (`agent.app`) — 입력 원문, 파라미터 추출 결과, 검증 성공/실패
8. **세션/캐시** (`agent.session`) — 키 설정, 캐시 hit/miss
9. **에러 통합** — 모든 except에서 exc_info=True, 사용자 메시지와 로그 메시지 분리

### Roo 구현 순서
1. `config.py`에 logging basicConfig 추가
2. (선택) `utils/logging_utils.py`에 `@log_pipeline` 데코레이터
3. SQL → Wrapper → Pipeline → LLM → FSM → 데이터 품질 → 세션 → 사용자 입력 → 에러 통합

### 코드 패턴 예시
각 영역별 copy-paste 가능한 코드 패턴이 `docs/logging_plan.md`에 포함되어 있음.

## 3. E2E 테스트 스크립트 — `test_workflow_e2e.py`

### 개요
Streamlit `AppTest` 기반으로 서버 없이 워크플로우를 시뮬레이션하는 pytest 스크립트.

### 테스트 클래스
| 클래스 | 테스트 수 | 내용 |
|--------|----------|------|
| `TestConventionalWorkflow` | 3 | 전체 흐름 + 워크플로우 선택 + 파라미터 누락 |
| `TestMAPWorkflow` | 1 | MAP 전체 흐름 (선택→조회→wafer→전공정) |
| `TestYieldWorkflow` | 1 | 수율 전체 흐름 (선택→조회→상세→종료) |
| `TestCustomPrompts` | 1 | 자유 프롬프트 편집용 |
| `TestEdgeCases` | 4 | 잘못된 번호, 빈 입력, 자연어, 날짜 형식 |

### 실행 방법
```bash
# 전체 실행
.venv/bin/python -m pytest test_workflow_e2e.py -v -s

# 특정 워크플로우만
.venv/bin/python -m pytest test_workflow_e2e.py::TestConventionalWorkflow -v -s
```

### 프롬프트 편집
각 클래스의 `PROMPTS` 리스트를 수정:
```python
PROMPTS = [
    {"input": "1", "expect_contains": "Conventional"},
    {"input": "내용 입력", "expect_contains": None},       # 검증 없이 응답만 출력
    {"input": "col_3 >= 0.7", "via": "feat", "expect_contains": "예측"},  # text_input으로 전송
]
```

- `via`: `"chat"` (기본 chat_input), `"feat"` (피처 선택 text_input), `"candidate"` (MAP 후보 text_input)
- `expect_contains`: `None`이면 검증 스킵

### Roo 반영 사항
- 파이프라인 실제 구현 후 E2E 테스트에서 mock 응답이 실제 응답으로 바뀔 수 있음
- `expect_contains` 값을 실제 응답에 맞게 업데이트 필요
- 새 파이프라인 추가 시 `PROMPTS`에 해당 단계 추가 가능
