from __future__ import annotations

import inspect
import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from openai import APIStatusError, AsyncOpenAI

from .provider import LLMResult, UnsupportedLLMFeatureError

logger = logging.getLogger("director_studio.llm.openai_compatible")


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    value = getattr(obj, key, None)
    if value is not None:
        return value
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, dict):
        return extra.get(key, default)
    return default


def _image_url(value: str) -> str:
    if value.startswith(("data:", "http://", "https://")):
        return value
    return f"data:image/jpeg;base64,{value}"


def _normalize_tool_messages(
    converted: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map Ollama-style tool call/result messages onto the OpenAI schema.

    The Director orchestrator builds a single conversation for both the Ollama
    and OpenAI-compatible backends. Ollama pairs a tool result with its call by
    name, while the OpenAI Chat Completions API requires every assistant tool
    call to carry an ``id`` and every tool result to answer with a matching
    ``tool_call_id``. Without this mapping the served model cannot tell which
    result belongs to which call and repeats the same tool on every turn until
    the turn budget is exhausted.
    """
    counter = 0
    pending: dict[str, list[str]] = {}
    for message in converted:
        role = message.get("role")
        if role == "assistant":
            calls = message.get("tool_calls")
            if not calls:
                continue
            pending = {}
            normalized: list[dict[str, Any]] = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = str(function.get("name") or call.get("name") or "")
                arguments = function.get("arguments", call.get("arguments"))
                if isinstance(arguments, (dict, list)):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                elif arguments is None:
                    arguments = "{}"
                else:
                    arguments = str(arguments)
                call_id = str(call.get("id") or "").strip() or f"call_{counter}"
                counter += 1
                normalized.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
                pending.setdefault(name, []).append(call_id)
            message["tool_calls"] = normalized
        elif role == "tool":
            name = str(message.pop("tool_name", "") or "")
            call_id = pending[name].pop(0) if pending.get(name) else ""
            if not call_id:
                for key in list(pending):
                    if pending[key]:
                        call_id = pending[key].pop(0)
                        break
            if call_id:
                message["tool_call_id"] = call_id
    return converted


def _messages(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for source in items:
        message = dict(source)
        images = list(message.pop("images", []) or [])
        if images:
            original = message.get("content")
            content = list(original) if isinstance(original, list) else []
            if not isinstance(original, list):
                content.append({"type": "text", "text": str(original or "")})
            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_url(str(image))},
                }
                for image in images
            )
            message["content"] = content
        converted.append(message)
    return _normalize_tool_messages(converted)


def _response_format(
    schema: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    if schema is None:
        return None
    if isinstance(schema, str):
        return {"type": "json_object"} if schema == "json" else {"type": schema}
    if schema.get("type") in {"json_schema", "json_object", "text"}:
        return dict(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "director_output",
            "strict": True,
            "schema": dict(schema),
        },
    }


def _reasoning(obj: Any) -> str:
    return str(
        _value(obj, "reasoning_content")
        or _value(obj, "reasoning")
        or _value(obj, "thinking")
        or ""
    )


def _error_text(exc: BaseException) -> str:
    pieces = [str(exc)]
    body = getattr(exc, "body", None)
    if body:
        try:
            pieces.append(json.dumps(body, ensure_ascii=False))
        except TypeError:
            pieces.append(str(body))
    return " ".join(pieces)


def _unsupported_feature(
    exc: BaseException,
    *,
    has_tools: bool,
    has_format: bool,
    has_images: bool,
) -> str | None:
    status = getattr(exc, "status_code", None)
    if status not in {400, 404, 422}:
        return None
    text = _error_text(exc).lower()
    rejection = any(
        marker in text
        for marker in (
            "not support",
            "unsupported",
            "unknown field",
            "unknown parameter",
            "unrecognized",
            "extra_forbidden",
            "not implemented",
        )
    )
    if not rejection:
        return None
    if has_images and any(
        marker in text
        for marker in ("image", "image_url", "vision", "multimodal")
    ):
        return "vision"
    if has_tools and any(marker in text for marker in ("tool", "function")):
        return "tools"
    if has_format and any(
        marker in text
        for marker in (
            "response_format",
            "json_schema",
            "structured output",
            "not implemented",
        )
    ):
        return "response_format"
    return None


def _json_instruction(schema: dict[str, Any] | str | None) -> str:
    rendered = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return (
        "Return only valid JSON matching this requested schema or format. "
        f"Do not wrap it in Markdown: {rendered}"
    )


def _append_instruction(
    messages: Sequence[dict[str, Any]],
    instruction: str,
) -> list[dict[str, Any]]:
    copied = _messages(messages)
    for message in reversed(copied):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content.append({"type": "text", "text": instruction})
        else:
            message["content"] = f"{str(content or '')}\n\n{instruction}"
        break
    return copied


def _request_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if not options:
        return {}
    allowed = {
        "temperature",
        "top_p",
        "seed",
        "stop",
        "presence_penalty",
        "frequency_penalty",
        "max_tokens",
        "enable_thinking",
        "reasoning_effort",
    }
    result = {key: value for key, value in options.items() if key in allowed}
    if "max_tokens" not in result and options.get("num_predict") is not None:
        result["max_tokens"] = options["num_predict"]
    return result


class OpenAICompatibleClient:
    """Common Chat Completions client for OpenAI-compatible servers."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout: float = 600.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http_client = (
            httpx.AsyncClient(transport=transport, timeout=timeout)
            if transport is not None
            else None
        )
        kwargs: dict[str, Any] = {
            "api_key": api_key or "not-needed",
            "base_url": self.base_url,
            "timeout": timeout,
            "max_retries": 0,
        }
        if self._http_client is not None:
            kwargs["http_client"] = self._http_client
        self._client = AsyncOpenAI(**kwargs)

    async def close(self) -> None:
        await self._client.close()

    async def list_models(self) -> list[str]:
        page = await self._client.models.list()
        return [str(item.id) for item in page.data if getattr(item, "id", None)]

    async def health(self) -> bool:
        try:
            await self.list_models()
            return True
        except (httpx.HTTPError, APIStatusError, OSError):
            return False

    async def chat_response(
        self,
        model: str,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        format: dict[str, Any] | str | None = None,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        require_vision: bool = False,
    ) -> LLMResult:
        del keep_alive
        converted = _messages(messages)
        request: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "stream": False,
            **_request_options(options),
        }
        # Server-side thinking controls are not SDK params; pass via extra_body.
        extra_body: dict[str, Any] = {}
        for key in ("enable_thinking", "reasoning_effort"):
            if key in request:
                extra_body[key] = request.pop(key)
        if extra_body:
            request["extra_body"] = extra_body
        if tools:
            request["tools"] = list(tools)
        converted_format = _response_format(format)
        if converted_format is not None:
            request["response_format"] = converted_format
        has_images = any(item.get("images") for item in messages)

        try:
            response = await self._client.chat.completions.create(**request)
        except APIStatusError as exc:
            if request.get("extra_body") and (
                "enable_thinking" in _error_text(exc).lower()
            ):
                request.pop("extra_body", None)
                response = await self._client.chat.completions.create(**request)
            else:
                feature = _unsupported_feature(
                    exc,
                    has_tools=bool(tools),
                    has_format=converted_format is not None,
                    has_images=has_images,
                )
                if feature == "response_format":
                    retry = dict(request)
                    retry.pop("response_format", None)
                    retry["messages"] = _append_instruction(
                        messages,
                        _json_instruction(format),
                    )
                    response = await self._client.chat.completions.create(**retry)
                elif feature in {"tools", "vision"}:
                    raise UnsupportedLLMFeatureError(feature, _error_text(exc)) from exc
                else:
                    raise

        if not response.choices:
            return {"content": "", "thinking": "", "tool_calls": []}
        choice = response.choices[0]
        message = choice.message
        normalized_calls: list[dict[str, Any]] = []
        for call in list(message.tool_calls or []):
            function = call.function
            arguments: Any = function.arguments or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            normalized_calls.append(
                {
                    "id": str(call.id or ""),
                    "name": str(function.name or ""),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                }
            )
        return {
            "content": str(message.content or ""),
            "thinking": _reasoning(message),
            "tool_calls": normalized_calls,
            "finish_reason": str(choice.finish_reason or ""),
        }

    async def chat_response_stream(
        self,
        model: str,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        format: dict[str, Any] | str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a tool-capable chat turn.

        Yields ``{"kind": "think"|"token", "text": ...}`` deltas as they arrive,
        then a final ``{"kind": "result", "result": LLMResult}`` with the
        assembled content, reasoning, and tool calls. Callers that cannot use a
        streaming server should fall back to :meth:`chat_response`.
        """
        converted = _messages(messages)
        request: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "stream": True,
            **_request_options(options),
        }
        extra_body: dict[str, Any] = {}
        for key in ("enable_thinking", "reasoning_effort"):
            if key in request:
                extra_body[key] = request.pop(key)
        if extra_body:
            request["extra_body"] = extra_body
        if tools:
            request["tools"] = list(tools)
        converted_format = _response_format(format)
        if converted_format is not None:
            request["response_format"] = converted_format

        content_parts: list[str] = []
        think_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        finish_reason = ""
        stream: Any = None
        try:
            try:
                stream = await self._client.chat.completions.create(**request)
            except APIStatusError as exc:
                if request.get("extra_body") and (
                    "enable_thinking" in _error_text(exc).lower()
                ):
                    request.pop("extra_body", None)
                    stream = await self._client.chat.completions.create(**request)
                else:
                    raise

            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                thinking = _reasoning(delta)
                if thinking:
                    think_parts.append(thinking)
                    yield {"kind": "think", "text": thinking}
                content = _value(delta, "content", "")
                if content:
                    text = str(content)
                    content_parts.append(text)
                    yield {"kind": "token", "text": text}
                for call in list(getattr(delta, "tool_calls", None) or []):
                    index = int(getattr(call, "index", 0) or 0)
                    entry = tool_calls.setdefault(
                        index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    call_id = getattr(call, "id", None)
                    if call_id:
                        entry["id"] = str(call_id)
                    function = getattr(call, "function", None)
                    if function is not None:
                        name = getattr(function, "name", None)
                        if name:
                            entry["name"] = str(name)
                        arguments = getattr(function, "arguments", None)
                        if arguments:
                            entry["arguments"] += str(arguments)
                if getattr(choice, "finish_reason", None):
                    finish_reason = str(choice.finish_reason)
        finally:
            # Close the HTTP stream in this generator so the SDK's async
            # generators do not get garbage-collected mid-request (which raises
            # "generator didn't stop after athrow()" and can mask the turn).
            if stream is not None:
                closer = getattr(stream, "aclose", None) or getattr(
                    stream, "close", None
                )
                if closer is not None:
                    try:
                        maybe = closer()
                        if inspect.isawaitable(maybe):
                            await maybe
                    except Exception:
                        logger.debug("stream close failed", exc_info=True)

        normalized_calls: list[dict[str, Any]] = []
        for index in sorted(tool_calls):
            entry = tool_calls[index]
            arguments: Any = entry["arguments"]
            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                arguments = {}
            normalized_calls.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "arguments": arguments if isinstance(arguments, dict) else {},
                }
            )
        yield {
            "kind": "result",
            "result": {
                "content": "".join(content_parts),
                "thinking": "".join(think_parts),
                "tool_calls": normalized_calls,
                "finish_reason": finish_reason,
            },
        }

    @staticmethod
    def _text(result: LLMResult) -> str:
        text = result.get("content", "")
        thinking = result.get("thinking", "")
        if thinking and "<think>" not in text.lower():
            return f"<think>{thinking}</think>\n{text}"
        return text

    async def generate(
        self,
        model: str,
        prompt: str,
        *,
        images: Sequence[str] | None = None,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = list(images)
        result = await self.chat_response(
            model,
            messages=[message],
            keep_alive=keep_alive,
            options=options,
            require_vision=bool(images),
        )
        return self._text(result)

    async def chat(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: Sequence[str] | None = None,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        require_vision: bool = False,
        format: dict[str, Any] | str | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        user: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user["images"] = list(images)
        messages.append(user)
        result = await self.chat_response(
            model,
            messages=messages,
            keep_alive=keep_alive,
            options=options,
            require_vision=require_vision,
            format=format,
        )
        return self._text(result)

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        *,
        images: Sequence[str] | None = None,
        system: str | None = None,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        async for item in self.chat_stream(
            model,
            prompt,
            system=system,
            images=images,
            keep_alive=keep_alive,
            options=options,
        ):
            yield item

    async def chat_stream(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: Sequence[str] | None = None,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        del keep_alive
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        user: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user["images"] = list(images)
        messages.append(user)
        stream = await self._client.chat.completions.create(
            model=model,
            messages=_messages(messages),
            stream=True,
            **_request_options(options),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            thinking = _reasoning(delta)
            if thinking:
                yield {"kind": "think", "text": thinking}
            content = _value(delta, "content", "")
            if content:
                yield {"kind": "token", "text": str(content)}
