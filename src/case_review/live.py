"""Production client bindings for the Messages API.

Provides ClaudeClient for the coordinator loop and ClaudeDocumentReader for
isolated document analysis, both backed by the real API. Requires `poetry install
--with live` and an `ANTHROPIC_API_KEY`. The entire test suite and offline demo
run without this -- they use `StubDocumentReader` and `ScriptedClient`. The
`anthropic` SDK is imported lazily so logic-only paths work without it.

Model and request shape follow the current API: `claude-opus-4-8` with adaptive
thinking. The Document Reader runs as a genuinely isolated subagent -- its own
Messages request whose context is only the raw documents -- so its heavy reads
never enter the coordinator loop's window.
"""

import json
import re

from case_review.loop import Response
from case_review.schemas import Claim
from case_review.subagents import DocumentBundle

MODEL = "claude-opus-4-8"

COORDINATOR_SYSTEM = (
    "You are a case-review coordinator. The CASE FACTS block is load-bearing: "
    "treat it as ground truth and never contradict it. Use the tools in order: "
    "read_documents, resolve_counterparty, then (only if the counterparty "
    "resolved to exactly one party) fetch_history, then finalize_verdict. If the "
    "counterparty is ambiguous, do NOT pick one -- stop and report. You may not "
    "issue a verdict unless the claim-history check succeeded; the system enforces "
    "this regardless of what you say."
)

READER_INSTRUCTION = (
    "You are a Document Reader. Read the documents below in full and return ONLY a "
    "short JSON list of claims, each with its source citation and effective date. "
    "Do not summarize the documents; extract claims. Return JSON: "
    '{"claims": [{"field", "value", "source", "effective_date"}]}. '
    "effective_date is the ISO date the cited document/section took effect."
)

COORDINATOR_TOOLS = [
    {
        "name": "read_documents",
        "description": "Dispatch the isolated Document Reader over the case documents; "
        "returns a short list of claims with citations (not the raw text).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "resolve_counterparty",
        "description": "Resolve the counterparty name to a single record via the "
        "Records Service. Two same-named parties is ambiguous -- do not pick one.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fetch_history",
        "description": "Fetch the counterparty's prior claim-history (load-bearing). "
        "A timeout/outage returns a structured error, not an empty result.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "finalize_verdict",
        "description": "Synthesize the findings and issue the verdict. Blocked until "
        "identity is resolved and the claim-history check has succeeded.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def parse_claims(text: str) -> list[Claim]:
    """Extract the claim list a Document Reader returns, tolerating fences/prose.

    Prefers a fenced ```json block when present; otherwise falls back to the
    first balanced JSON object. A non-greedy scan avoids swallowing stray braces
    in the surrounding prose, and a missing `claims` key is a clear error rather
    than a bare KeyError.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else _first_json_object(text)
    if raw is None:
        raise ValueError("no JSON object found in Document Reader output")
    payload = json.loads(raw)
    if "claims" not in payload:
        raise ValueError("Document Reader output has no 'claims' key")
    return [Claim(**c) for c in payload["claims"]]


def _first_json_object(text: str) -> str | None:
    """Return the first balanced {...} object in `text`, or None.

    Tracks brace depth so a complete object is captured without greedily running
    to the last brace in trailing prose.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class ClaudeClient:
    """ModelClient backed by the Messages API. Defaults drive the coordinator loop;
    pass `system` and `tools` to drive a different loop (e.g. the bare-loop demo)."""

    def __init__(
        self,
        *,
        model: str = MODEL,
        max_tokens: int = 4096,
        system: str | None = None,
        tools: list[dict] | None = None,
    ):
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._system = system or COORDINATOR_SYSTEM
        self._tools = tools or COORDINATOR_TOOLS

    def create(self, messages: list[dict]) -> Response:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._system,
            tools=self._tools,
            thinking={"type": "adaptive"},
            messages=messages,
        )
        return Response(message.stop_reason, [block.model_dump() for block in message.content])


class ClaudeDocumentReader:
    """DocumentReader backed by the Messages API -- a genuinely isolated subagent.

    The raw documents are the entire context of this request and never enter the
    coordinator loop's window.
    """

    def __init__(self, *, model: str = MODEL, max_tokens: int = 4096):
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self.chars_read = 0

    def read(self, bundle: DocumentBundle) -> list[Claim]:
        docs = "\n\n".join(f"<doc name={name!r}>\n{text}\n</doc>"
                           for name, text in bundle.documents.items())
        self.chars_read = sum(len(t) for t in bundle.documents.values())
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": f"{READER_INSTRUCTION}\n\n{docs}"}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return parse_claims(text)
