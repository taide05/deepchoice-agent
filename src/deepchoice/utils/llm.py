import os
import json_repair
from openai import AsyncOpenAI
from langchain_core.utils.json import parse_json_markdown


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_PRO_MODEL = "deepseek-v4-pro"


def _get_client() -> AsyncOpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    return AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120.0)


async def call_model(
    prompt: list[dict],
    model: str = DEFAULT_FLASH_MODEL,
    response_format: str | None = None,
) -> dict | str:
    client = _get_client()
    kwargs = {"model": model, "messages": prompt, "temperature": 0}
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content

    if response_format == "json":
        return parse_json_markdown(content, parser=json_repair.loads)
    return content
