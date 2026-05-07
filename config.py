"""Application configuration."""

import os
from dotenv import load_dotenv

load_dotenv()


# LLM settings
LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

# S3 settings
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "ap-northeast-2")

# Internal SDK settings
SDK_API_URL = os.getenv("SDK_API_URL", "")
SDK_API_KEY = os.getenv("SDK_API_KEY", "")

# Checkpoint settings
CHECKPOINT_DIR = os.getenv("CHECKPOINT_DIR", ".checkpoints")
