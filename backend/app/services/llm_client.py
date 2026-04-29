import logging
import random
import time

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenAICompatClient:
    def __init__(self) -> None:
        self._default_client = OpenAI(
            api_key=settings.openai_api_key or "EMPTY",
            base_url=settings.openai_base_url,
        )

    def chat(
        self,
        message: str,
        system_prompt: str,
        override_api_key: str | None = None,
        override_base_url: str | None = None,
        override_model: str | None = None,
        max_retries: int | None = None,
        backoff_base_seconds: float = 1.5,
    ) -> str:
        api_key = override_api_key or settings.openai_api_key
        base_url = override_base_url or settings.openai_base_url
        model = override_model or settings.openai_model
        if max_retries is None:
            max_retries = settings.translate_max_retries

        if not api_key:
            return "No API key configured. Set OPENAI_API_KEY or provide override_api_key."

        client = self._default_client
        if override_api_key or override_base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)

        for attempt in range(max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    temperature=0.2,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                is_last_attempt = attempt >= max_retries
                if is_last_attempt or not _is_retryable_error(exc):
                    raise

                # Honor server Retry-After header if present, else exponential
                # backoff with jitter to avoid thundering herd under concurrency.
                retry_after = _retry_after_seconds(exc)
                if retry_after is not None:
                    delay_seconds = retry_after
                else:
                    delay_seconds = backoff_base_seconds * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "LLM call retryable error (attempt %d/%d), sleeping %.2fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay_seconds,
                    exc,
                )
                time.sleep(delay_seconds)

        return ""


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    if isinstance(status_code, int) and 500 <= status_code < 600:
        return True

    message = str(exc).lower()
    retryable_keywords = ("rate", "throttl", "quota", "timeout", "temporar", "connection")
    return any(keyword in message for keyword in retryable_keywords)


llm_client = OpenAICompatClient()
