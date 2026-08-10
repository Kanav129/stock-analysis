from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from config.llm_config import _chat_llm, resolve_analysis_model
from evals.decision_scoring.structure import StructureResult, validate_decision_payload
from rag_graphs.research_graph.nodes.synthesize_decision import DecisionOutput


@dataclass
class InvokeResult:
    call_ok: bool
    schema_method: Literal["function_calling", "json_parse", "failed"]
    structure: StructureResult
    raw_error: str | None
    latency_ms: float
    model: str


def _as_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError(f"decision output must be a model or mapping, got {type(value).__name__}")


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    raise TypeError("LLM response content must be text")


def _extract_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("LLM response did not contain a JSON object")


def invoke_decision(
    *,
    system_prompt: str,
    temperature: float,
    enable_thinking: bool,
    ticker: str,
    context: str,
) -> InvokeResult:
    started = perf_counter()
    model = resolve_analysis_model()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "human",
                "Ticker: {ticker}\n\nResearch context:\n{context}",
            ),
        ]
    )
    prompt_value = prompt.invoke({"ticker": ticker, "context": context})
    llm = _chat_llm(
        model,
        temperature,
        enable_thinking=enable_thinking,
    )

    function_error: Exception | None = None
    last_payload: dict[str, Any] | None = None
    try:
        structured_llm = llm.with_structured_output(
            DecisionOutput,
            method="function_calling",
            include_raw=True,
        )
        response = structured_llm.invoke(prompt_value)
        if isinstance(response, Mapping) and "parsed" in response:
            parsed = response.get("parsed")
            if parsed is None:
                parsing_error = response.get("parsing_error")
                raise ValueError(
                    f"structured output parsing failed: {parsing_error or 'no parsed value'}"
                )
        else:
            parsed = response
        last_payload = _as_payload(parsed)
        validated = DecisionOutput.model_validate(last_payload).model_dump()
        structure = validate_decision_payload(validated)
        return InvokeResult(
            call_ok=True,
            schema_method="function_calling",
            structure=structure,
            raw_error=None,
            latency_ms=(perf_counter() - started) * 1000,
            model=model,
        )
    except Exception as exc:
        function_error = exc

    if enable_thinking:
        try:
            raw = llm.invoke(prompt_value)
            last_payload = _extract_json_object(_message_text(raw.content))
            validated = DecisionOutput.model_validate(last_payload).model_dump()
            structure = validate_decision_payload(validated)
            return InvokeResult(
                call_ok=True,
                schema_method="json_parse",
                structure=structure,
                raw_error=str(function_error),
                latency_ms=(perf_counter() - started) * 1000,
                model=model,
            )
        except Exception as fallback_error:
            raw_error = (
                f"function_calling: {function_error}; json_parse: {fallback_error}"
            )
    else:
        raw_error = str(function_error)

    structure = validate_decision_payload(last_payload or {})
    return InvokeResult(
        call_ok=False,
        schema_method="failed",
        structure=structure,
        raw_error=raw_error,
        latency_ms=(perf_counter() - started) * 1000,
        model=model,
    )
