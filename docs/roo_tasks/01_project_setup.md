# Task 01: Project Setup

## Goal
프로젝트 의존성 설치, 환경 설정 파일 구성, 기본 실행 확인

---

## 사전 조건
- Python 3.11+
- pip 또는 poetry 사용 가능
- AWS 자격증명 (S3 접근용)
- 사내 SDK 접근 권한

---

## 작업 목록

### 1-1. 환경변수 파일 생성

`.env.example` 파일 생성:

```env
# LLM
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2048

# S3
S3_BUCKET=your-bucket-name
S3_REGION=ap-northeast-2

# Internal SDK
SDK_API_URL=https://internal-api.company.com
SDK_API_KEY=your-sdk-key

# Checkpoints
CHECKPOINT_DIR=.checkpoints
```

실제 `.env` 파일은 `.gitignore`에 추가.

### 1-2. 의존성 설치 검증

```bash
pip install -r requirements.txt
python -c "import streamlit, pandas, numpy, openai, boto3, sklearn; print('OK')"
```

### 1-3. Streamlit 기본 실행 확인

```bash
streamlit run app.py
```

브라우저에서 타이틀 "Data Analysis Agent"가 표시되고, 채팅 입력창이 나타나는지 확인.

### 1-4. .gitignore 작성

```
.env
.checkpoints/
__pycache__/
*.pyc
.pytest_cache/
```

### 1-5. config.py 로딩 테스트

```python
# 수동 확인
from dotenv import load_dotenv
load_dotenv()
import config
assert config.LLM_API_KEY != ""
assert config.S3_BUCKET != ""
```

---

## 파일 체크리스트

| 파일 | 액션 | 설명 |
|------|------|------|
| `.env.example` | 신규 생성 | 환경변수 템플릿 |
| `.env` | 신규 생성 (로컬) | 실제 키 값 |
| `.gitignore` | 신규 생성 | 민감파일 제외 |
| `requirements.txt` | 확인 | 이미 존재, 버전 호환 확인 |
| `config.py` | 확인 | 이미 존재, 로딩 테스트만 |

---

## 완료 기준

- [ ] `pip install -r requirements.txt` 에러 없이 완료
- [ ] `streamlit run app.py` 실행 시 브라우저에 UI 표시
- [ ] `config.py`에서 모든 환경변수 정상 로딩
- [ ] `.checkpoints/` 디렉토리 자동 생성 확인
- [ ] `.env`가 git에 포함되지 않음
