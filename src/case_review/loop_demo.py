"""Bare agent loop, offline: `python -m case_review.loop_demo` (no API key).

Slide 5 ("Anatomy of the loop") in code. Drives `run_agentic_loop` with a
ScriptedClient and two trivial tools -- no coordinator, no gate, no subagents --
and prints every turn, so only the loop is on screen: the model decides, asks for
a tool, the tool runs, the result is handed back, and it repeats until
`stop_reason == "end_turn"`.

The coordinator demo (`python -m case_review.demo`) shows this same loop doing
real case-review work; this strips everything away to show the loop's shape.
A live variant would swap `ScriptedClient` for `ClaudeClient` (live.py); scripting
the turns keeps this deterministic and credit-free.
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


# The scripted model trajectory: tool_use -> (result) -> tool_use -> (result) ->
# end_turn. A real model would produce these turns from the prompt; scripting them
# keeps the demo deterministic and offline.
SCRIPT = [
    Response("tool_use", [tool_use_block("u1", "look_up_order", {"order_id": "12345"})]),
    Response("tool_use", [
        text_block("The order shipped, so I'll process the refund."),
        tool_use_block("u2", "issue_refund", {"order_id": "12345"}),
    ]),
    Response("end_turn", [text_block("Refund issued against order #12345.")]),
]


def _print_turn(message: dict) -> None:
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


def main() -> None:
    print("=== anatomy of the loop (offline, scripted model) ===")
    for message in run():
        _print_turn(message)
    print("\n  stop_reason == 'end_turn' -> loop exits (no tool asked for -> done).")


if __name__ == "__main__":
    main()
