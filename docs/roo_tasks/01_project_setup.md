# Task 01: Project Setup

## Goal
프로젝트 디렉토리 구조 생성, 의존성 설치, 기본 설정 파일 구성

## Files
- `requirements.txt`
- `config.py`
- `.env.example`
- All `__init__.py` files

## Steps
1. `pip install -r requirements.txt`로 의존성 설치 확인
2. `.env.example` 생성 (모든 환경변수 키 나열)
3. `config.py`가 `.env`에서 올바르게 로딩되는지 확인
4. Streamlit 기본 실행 (`streamlit run app.py`) 정상 동작 확인

## Acceptance Criteria
- [ ] 모든 import 에러 없이 `app.py` 실행됨
- [ ] config 값들이 환경변수에서 로딩됨
- [ ] `.checkpoints/` 디렉토리 자동 생성됨
