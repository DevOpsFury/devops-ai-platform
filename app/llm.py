from anthropic import Anthropic
from openai import OpenAI
from pydantic import SecretStr

from app.config import settings


class ProviderConfigurationError(RuntimeError):
    pass


def _secret_value(*values: SecretStr | None) -> str | None:
    for value in values:
        if value is not None and value.get_secret_value().strip():
            return value.get_secret_value()
    return None


def complete(system_prompt: str, user_prompt: str) -> str:
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        api_key = _secret_value(settings.anthropic_api_key, settings.llm_api_key)
        if api_key is None:
            raise ProviderConfigurationError("Set ANTHROPIC_API_KEY or LLM_API_KEY for Anthropic.")
        response = Anthropic(api_key=api_key, timeout=60).messages.create(
            model=settings.llm_model,
            max_tokens=1200,
            temperature=0.1,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    if provider in {"openai", "ollama"}:
        if provider == "openai":
            api_key = _secret_value(settings.openai_api_key, settings.llm_api_key)
            if api_key is None:
                raise ProviderConfigurationError("Set OPENAI_API_KEY or LLM_API_KEY for OpenAI.")
            client = OpenAI(api_key=api_key, timeout=60)
        else:
            client = OpenAI(
                api_key=_secret_value(settings.llm_api_key) or "ollama",
                base_url=settings.llm_base_url,
                timeout=60,
            )
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(f"{provider} returned an empty response.")
        return content

    raise ProviderConfigurationError("LLM_PROVIDER must be one of: anthropic, openai, ollama.")
