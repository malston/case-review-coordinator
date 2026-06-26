"""Bare agent loop, offline: `python -m case_review.loop_demo` (no API key).

Slide 5 ("Anatomy of the loop") in code. Drives `run_agentic_loop` with a
ScriptedClient and two trivial tools -- no coordinator, no gate, no subagents --
and prints every turn, so only the loop is on screen: the model decides, asks for
a tool, the tool runs, the result is handed back, and it repeats until
`stop_reason == "end_turn"`.

The coordinator demo (`python -m case_review.demo`) shows this same loop doing
real case-review work; this strips everything away to show the loop's shape.
The offline path uses ScriptedClient to keep turns deterministic and credit-free.
A live variant uses ClaudeClient (live.py) instead, with the same loop.
"""

from typing import Any

from case_review.loop import (
    Response,
    ScriptedClient,
    run_agentic_loop,
    text_block,
    tool_use_block,
)


# Two trivial tools. Each takes (tool_input, state) and returns a result the loop
# wraps into a tool_result. Nothing domain-specific -- the point is the loop.
def look_up_order(tool_input: dict, _state: Any) -> dict:
    return {"order_id": tool_input["order_id"], "status": "shipped"}


def issue_refund(tool_input: dict, _state: Any) -> dict:
    return {"refund_id": "rf_001", "order_id": tool_input["order_id"], "status": "refunded"}


TOOLS = {"look_up_order": look_up_order, "issue_refund": issue_refund}


# Tool definitions the live model reads (name + description + input schema). The
# offline path scripts the model's turns, so it doesn't need these; the live path
# (`--live`) sends them to the real model so it can choose. The advertised names
# must match TOOLS, or the loop would dispatch a call it can't execute.
LOOP_TOOLS = [
    {
        "name": "look_up_order",
        "description": "Look up an order by its ID; returns the order's current status.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "issue_refund",
        "description": "Issue a refund for an order. Look the order up first to confirm "
        "it shipped before refunding.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
]

LOOP_SYSTEM = (
    "You are an order-support agent. Use the tools to resolve the user's "
    "request, then stop."
)


# The scripted model trajectory: tool_use -> (result) -> tool_use -> (result) ->
# end_turn. A real model would produce these turns from the prompt; scripting them
# keeps the demo deterministic and offline.
SCRIPT = [
    Response("tool_use", [
        text_block("I'll look up the order to confirm it shipped before issuing the refund."),
        tool_use_block("u1", "look_up_order", {"order_id": "12345"}),
    ]),
    Response("tool_use", [
        text_block("The order shipped, so I'll process the refund."),
        tool_use_block("u2", "issue_refund", {"order_id": "12345"}),
    ]),
    Response("end_turn", [text_block("Refund issued against order #12345.")]),
]


def _print_turn(message: dict) -> None:
    """Print a single turn of the loop in human-readable form."""
    role, content = message["role"], message["content"]
    if isinstance(content, str):
        print(f"  {role}: {content}")
        return
    for block in content:
        kind = block.get("type")
        if kind == "text":
            print(f"  {role} (text): {block['text']}")
        elif kind == "tool_use":
            print(f"  {role} -> tool_use: {block['name']}({block['input']})")
        elif kind == "tool_result":
            flag = " [is_error]" if block.get("is_error") else ""
            print(f"  {role} <- tool_result{flag}: {block['content']}")


def run() -> list[dict]:
    """Drive the bare loop offline and return the full message transcript."""
    return run_agentic_loop(
        ScriptedClient(SCRIPT),
        [{"role": "user", "content": "Look up order #12345 and refund it."}],
        tools=TOOLS,
        pre_hooks={},
        state=None,
    )


def run_live() -> list[dict]:
    """Drive the same bare loop against the real API. Opt-in: needs the live extra
    (`make install-live`) and ANTHROPIC_API_KEY. The model -- not a script --
    decides to look the order up before refunding it."""
    from case_review.live import ClaudeClient

    client = ClaudeClient(system=LOOP_SYSTEM, tools=LOOP_TOOLS)
    return run_agentic_loop(
        client,
        [{"role": "user", "content": "Look up order #12345 and refund it."}],
        tools=TOOLS,
        pre_hooks={},
        state=None,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Anatomy of the agent loop.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="drive the loop against the real API (needs `make install-live` + ANTHROPIC_API_KEY)",
    )
    args = parser.parse_args()

    if args.live:
        print("=== anatomy of the loop (LIVE -- real model decides) ===")
        transcript = run_live()
    else:
        print("=== anatomy of the loop (offline, scripted model) ===")
        transcript = run()
    for message in transcript:
        _print_turn(message)
    print("\n  stop_reason == 'end_turn' -> loop exits (no tool asked for -> done).")


if __name__ == "__main__":
    main()
