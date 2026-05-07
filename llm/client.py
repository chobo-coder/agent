"""OpenAI-compatible LLM client."""

from openai import OpenAI

import config


class LLMClient:
    """Thin wrapper around OpenAI-compatible API."""

    def __init__(self):
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

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""

    def complete_with_history(
        self, messages: list[dict[str, str]], system: str | None = None
    ) -> str:
        """Send a multi-turn conversation."""
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""
