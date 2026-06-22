"""The coordinator's agentic loop -- Messages-API shaped, model-agnostic.

Every control-flow decision keys off the protocol: `stop_reason`, the block
`type`, and `tool_use_id`. None of them read the assistant's prose. Termination
is `stop_reason == "end_turn"`; any other stop reason raises (a non-end_turn is
never silently treated as "done"); the step cap is a safety backstop that raises,
not a completion signal.

A tool may return a structured error result. The loop forwards it as a
tool_result with `is_error=True` -- it never swallows it into a clean result.
A tool that *raises* is a different case: an unknown tool name or a tool bug is a
programming error, not a model-recoverable condition, so the loop fails fast and
lets it propagate rather than masking it behind an `is_error` result.

`ModelClient` is the seam. `ScriptedClient` replays canned responses offline;
`ClaudeClient` (in `live.py`) calls the real API.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def tool_use_block(block_id: str, name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "id": block_id, "name": name, "input": tool_input}


def tool_result_block(tool_use_id: str, content: Any, *, is_error: bool = False) -> dict:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": text,
        "is_error": is_error,
    }


@dataclass
class Response:
    stop_reason: str
    content: list[dict]


class LoopError(RuntimeError):
    pass


class ModelClient(Protocol):
    def create(self, messages: list[dict]) -> Response: ...


class ScriptedClient:
    """Replays a fixed list of Responses -- offline driver for the loop."""

    def __init__(self, responses: list[Response]):
        self._responses = list(responses)
        self._index = 0

    def create(self, messages: list[dict]) -> Response:
        if self._index >= len(self._responses):
            raise LoopError("ScriptedClient exhausted: loop asked for another turn.")
        response = self._responses[self._index]
        self._index += 1
        return response


def run_agentic_loop(
    client: ModelClient,
    messages: list[dict],
    *,
    tools: dict[str, Callable[[dict, Any], Any]],
    pre_hooks: dict[str, Callable[[dict, Any], Any]],
    state: Any,
    max_steps: int = 25,
) -> list[dict]:
    for _ in range(max_steps):
        response = client.create(messages)
        # Append the assistant turn verbatim -- thinking and tool_use blocks intact.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return messages  # the ONLY completion signal
        if response.stop_reason != "tool_use":
            raise LoopError(f"unexpected stop_reason: {response.stop_reason}")

        tool_results = []
        for block in response.content:
            if block.get("type") != "tool_use":
                continue  # prose and thinking never drive control flow
            name, tool_use_id, tool_input = block["name"], block["id"], block["input"]

            pre = pre_hooks.get(name)
            if pre is not None:
                decision = pre(tool_input, state)
                if not decision.allowed:
                    tool_results.append(
                        tool_result_block(tool_use_id, decision.reason, is_error=True)
                    )
                    continue

            result = tools[name](tool_input, state)
            # A tool that returns a structured error is forwarded AS an error --
            # never laundered into a clean tool_result.
            is_error = isinstance(result, dict) and bool(result.get("isError"))
            tool_results.append(tool_result_block(tool_use_id, result, is_error=is_error))

        messages.append({"role": "user", "content": tool_results})

    raise LoopError("max steps exceeded -- backstop reached, not a completion.")
