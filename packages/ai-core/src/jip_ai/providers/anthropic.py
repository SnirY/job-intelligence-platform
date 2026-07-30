"""Anthropic adapter.

The only module in the platform that imports a model provider's SDK. Everything
it knows about the domain is "here is a system prompt, a user message, and a
JSON Schema"; everything the domain knows about it is the ``LLMProvider``
protocol.

The SDK is imported lazily so the package stays importable — and its unit tests
runnable — on a machine that has no provider library installed.
"""

from __future__ import annotations

import logging
from typing import Any

from jip_ai.failures import AIError, AIFailureCode
from jip_ai.provider import StructuredRequest, StructuredResult, TokenUsage
from jip_ai.structured import parse_structured_output

logger = logging.getLogger(__name__)

PROVIDER_NAME = "anthropic"


class AnthropicProvider:
    """:class:`~jip_ai.provider.LLMProvider` backed by the Anthropic Messages API."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def generate_structured(self, request: StructuredRequest, *, model: str) -> StructuredResult:
        output_config: dict[str, Any] = {}
        if request.constrain_output:
            # Constrains generation to the schema. Checked again on the way back:
            # a provider honouring the schema is a convenience, and
            # `docs/11-engineering-standards.md` still treats the output as
            # untrusted until our own validation passes.
            #
            # Skipped when the caller sets `constrain_output=False`, which exists
            # for a schema this API will not compile into a grammar (DEV-017).
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        if request.effort is not None:
            output_config["effort"] = request.effort

        # Omitted entirely when empty rather than sent as `{}`: an unconstrained
        # request with no effort set has nothing to say here, and the provider
        # should see the same request it would have seen before this option
        # existed.
        extra: dict[str, Any] = {"output_config": output_config} if output_config else {}

        try:
            message = self._client.messages.create(
                model=model,
                max_tokens=request.max_output_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                **extra,
            )
        except Exception as exc:
            raise _classify(exc) from exc

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            # A safety decline, not a malformed answer. Retrying the same
            # document would decline again, so it is reported as unavailable
            # content rather than a transient provider fault.
            raise AIError(
                AIFailureCode.CONTENT_UNAVAILABLE,
                "The model declined to process this document.",
            )

        text = _first_text(message)
        if stop_reason == "max_tokens":
            # Truncated JSON parses as invalid rather than as a short answer, but
            # saying so plainly beats letting the JSON error be the explanation.
            raise AIError(
                AIFailureCode.INVALID_OUTPUT,
                "The model's answer was cut off before it finished.",
                details="stop_reason=max_tokens",
            )

        return StructuredResult(
            payload=parse_structured_output(text),
            raw_text=text,
            model=getattr(message, "model", model),
            usage=_usage(message),
            stop_reason=stop_reason,
        )

    def generate_text(self, system: str, user: str, *, model: str, max_output_tokens: int) -> str:
        try:
            message = self._client.messages.create(
                model=model,
                max_tokens=max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            raise _classify(exc) from exc
        return _first_text(message)


def _first_text(message: Any) -> str:
    """Concatenate the text blocks of a response.

    Responses are a list of typed blocks — thinking blocks appear alongside text
    on models that reason before answering — so indexing ``content[0]`` reads
    whichever block happened to come first.
    """
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(str(getattr(block, "text", "")))
    return "".join(parts)


def _usage(message: Any) -> TokenUsage:
    usage = getattr(message, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cached_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    )


def _classify(exc: Exception) -> AIError:
    """Map an SDK exception onto the documented failure taxonomy.

    Matched on the exception class name rather than by importing the SDK's
    classes: this module must stay importable without the SDK installed, and an
    ``isinstance`` check would need it at import time.
    """
    name = type(exc).__name__
    message = str(exc)

    if name == "RateLimitError":
        return AIError(
            AIFailureCode.RATE_LIMIT, "The AI provider is rate limiting us.", details=message
        )
    if name in {"APITimeoutError", "TimeoutError"}:
        return AIError(
            AIFailureCode.TIMEOUT, "The AI provider did not respond in time.", details=message
        )
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        # Not retriable in substance, but PROVIDER_ERROR is the documented code
        # and the operator-facing message is what makes it actionable.
        return AIError(
            AIFailureCode.PROVIDER_ERROR,
            "The AI provider rejected our credentials.",
            details=message,
        )

    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status == 429:
        return AIError(
            AIFailureCode.RATE_LIMIT, "The AI provider is rate limiting us.", details=message
        )

    # A 4xx means the provider read the request and refused it. Waiting cannot
    # change that, so retrying spends live calls on a guaranteed failure —
    # DEV-015, where a "credit balance too low" reply was retried five times
    # while the user was told we could not reach the provider.
    #
    # 429 is the exception and is handled above: it is the one 4xx that a wait
    # does fix. 5xx keeps the retriable default, because that genuinely is the
    # provider having a bad moment.
    if isinstance(status, int) and 400 <= status < 500:
        return AIError(
            AIFailureCode.PROVIDER_ERROR,
            "The AI provider rejected the request. Trying again will not change the outcome.",
            # The provider's own explanation names the cause — a billing limit,
            # a schema it will not compile — and it goes to the log rather than
            # the browser, per docs/10-api-contracts.md.
            details=message,
            retriable=False,
        )

    return AIError(
        AIFailureCode.PROVIDER_ERROR, "The AI provider could not be reached.", details=message
    )


def build_anthropic_client(api_key: str, *, timeout_seconds: float, max_retries: int = 0) -> Any:
    """Construct the SDK client.

    ``max_retries=0`` on purpose: retrying is
    :func:`jip_ai.retry.run_with_retry`'s job, and it records one ``AIRun`` per
    attempt. Letting the SDK retry underneath would hide those attempts and
    their cost from the trace that exists to show them.
    """
    import anthropic

    return anthropic.Anthropic(
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=max_retries,
    )
