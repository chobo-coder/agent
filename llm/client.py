"""OpenAI-compatible LLM client."""

import time
from openai import OpenAI, APITimeoutError, RateLimitError, APIConnectionError

import config


class LLMError(Exception):
    """LLM API 호출 실패"""
    pass


class LLMClient:
    """Thin wrapper around OpenAI-compatible API with retry."""

    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]

    def __init__(self):
        if not config.LLM_API_KEY:
            raise LLMError("LLM_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

        self._client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_API_BASE_URL,
        )
        self._model = config.LLM_MODEL
        self._temperature = config.LLM_TEMPERATURE
        self._max_tokens = config.LLM_MAX_TOKENS

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt and return the assistant's text response."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._call_with_retry(messages)

    def complete_with_history(
        self, messages: list[dict[str, str]], system: str | None = None
    ) -> str:
        """Send a multi-turn conversation."""
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        return self._call_with_retry(full_messages)

    def _call_with_retry(self, messages: list[dict]) -> str:
        """API 호출 + 재시도 로직"""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    timeout=30,
                )
                return response.choices[0].message.content or ""
            except (APITimeoutError, APIConnectionError) as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"API 연결 실패 ({self.MAX_RETRIES}회 재시도): {e}")
                time.sleep(self.RETRY_DELAYS[attempt])
            except RateLimitError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"Rate limit 초과: {e}")
                time.sleep(self.RETRY_DELAYS[attempt] * 2)
        return ""
