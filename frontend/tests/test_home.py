"""Tests for the chat-home greeting helper."""
from __future__ import annotations

import pytest
from aj360_app.state import _time_greeting


@pytest.mark.parametrize("hour", [5, 6, 11])
def test_time_greeting_morning(hour):
    assert _time_greeting(hour) == "Good morning"


@pytest.mark.parametrize("hour", [12, 15, 17])
def test_time_greeting_afternoon(hour):
    assert _time_greeting(hour) == "Good afternoon"


@pytest.mark.parametrize("hour", [18, 21, 23, 0, 4])
def test_time_greeting_evening(hour):
    assert _time_greeting(hour) == "Good evening"
