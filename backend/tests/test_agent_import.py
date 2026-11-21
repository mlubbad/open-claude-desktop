def test_agent_imports_and_run_turn_is_async_gen():
    import inspect

    from ocd_core import agent
    assert inspect.isasyncgenfunction(agent.run_turn)
    # the real (not docstring) event vocabulary is preserved verbatim
    src = inspect.getsource(agent.run_turn)
    assert "think_open" in src and "answer_open" in src
    # tool dispatch + effort config intact
    assert hasattr(agent, "EFFORT") and hasattr(agent, "run_turn")
