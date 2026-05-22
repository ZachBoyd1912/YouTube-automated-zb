"""
Shared LLM client using DeepSeek via OpenRouter.
Uses the OpenAI SDK with a custom base_url — all DeepSeek models are OpenAI-API-compatible.

Usage:
    from shared.llm_client import forced_tool_call, chat_completion

    result = forced_tool_call(
        system="You are ...",
        user="...",
        tool=MY_TOOL_DICT,   # {"name": ..., "description": ..., "input_schema": {...}}
    )
    # result is the parsed dict of the tool's arguments
"""
import json
import logging
from typing import Any

from openai import OpenAI

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_REFERER = "https://github.com/ZachBoyd1912/YouTube-automated-zb"
_APP_TITLE = "YouTube Automation Pipeline"


def _client() -> OpenAI:
    return OpenAI(
        base_url=_OPENROUTER_BASE,
        api_key=config.OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": _REFERER,
            "X-Title": _APP_TITLE,
        },
    )


def _to_openai_tool(tool: dict) -> dict:
    """Convert an Anthropic-style tool dict to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", tool.get("parameters", {})),
        },
    }


@with_retry(max_attempts=3)
def forced_tool_call(
    system: str,
    user: str,
    tool: dict,
    messages_override: list[dict] | None = None,
    max_tokens: int = 4096,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Call DeepSeek (via OpenRouter) and force it to respond using the given tool.
    Returns the parsed tool arguments as a dict.

    Args:
        system: System prompt text.
        user: User message text.
        tool: Tool dict with keys: name, description, input_schema.
        messages_override: If provided, use these messages instead of [system+user].
        max_tokens: Max tokens for the response.
        model: Override the default LLM_MODEL.
    """
    llm = _client()
    openai_tool = _to_openai_tool(tool)
    tool_name = tool["name"]

    if messages_override:
        messages = messages_override
    else:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    response = llm.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=messages,
        tools=[openai_tool],
        tool_choice={"type": "function", "function": {"name": tool_name}},
        max_tokens=max_tokens,
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise ValueError(f"DeepSeek did not return a tool call for {tool_name!r}")

    call = message.tool_calls[0]
    if call.function.name != tool_name:
        raise ValueError(f"Expected tool {tool_name!r}, got {call.function.name!r}")

    result = json.loads(call.function.arguments)
    logger.debug("Tool call %r returned keys: %s", tool_name, list(result.keys()))
    return result


@with_retry(max_attempts=3)
def chat_completion(
    system: str,
    user: str,
    max_tokens: int = 2048,
    model: str | None = None,
) -> str:
    """Simple text completion — returns the assistant's reply as a string."""
    llm = _client()
    response = llm.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
