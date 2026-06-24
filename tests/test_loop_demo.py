"""The bare-loop demo iterates tool_use -> tool_result until end_turn."""

from case_review.loop_demo import LOOP_TOOLS, TOOLS, run


def _tool_uses(messages: list[dict]) -> list[str]:
    return [
        block["name"]
        for m in messages
        if m["role"] == "assistant" and isinstance(m["content"], list)
        for block in m["content"]
        if block.get("type") == "tool_use"
    ]


def _tool_results(messages: list[dict]) -> list[dict]:
    return [
        block
        for m in messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for block in m["content"]
        if block.get("type") == "tool_result"
    ]


def test_loop_calls_both_tools_in_order():
    assert _tool_uses(run()) == ["look_up_order", "issue_refund"]


def test_each_tool_use_gets_a_result_fed_back():
    results = _tool_results(run())
    # Two tool calls -> two results handed back: the loop iterated, not single-shot.
    assert len(results) == 2
    assert all(not r["is_error"] for r in results)


def test_loop_terminates_on_end_turn_text():
    last = run()[-1]
    assert last["role"] == "assistant"
    # Final turn is plain text (end_turn) -- no trailing tool_use.
    assert all(block.get("type") != "tool_use" for block in last["content"])
    assert any("Refund issued" in block.get("text", "") for block in last["content"])


def test_live_tool_defs_match_the_executable_tools():
    # The live model is told about LOOP_TOOLS; the loop dispatches via TOOLS.
    # If they drift, the model can call a name that has no callable -> KeyError
    # in run_agentic_loop. Keep the advertised set and the executable set equal.
    advertised = {t["name"] for t in LOOP_TOOLS}
    assert advertised == set(TOOLS)


def test_live_tool_defs_are_well_formed():
    for tool in LOOP_TOOLS:
        assert tool["name"]
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
