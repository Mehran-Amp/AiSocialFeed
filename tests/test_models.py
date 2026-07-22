import pytest
from datetime import datetime, timezone
from bot.models import _utcnow

def test_utcnow_returns_datetime():
    """Test that _utcnow returns a datetime object."""
    result = _utcnow()
    assert isinstance(result, datetime)

def test_utcnow_is_timezone_aware():
    """Test that _utcnow returns a timezone-aware datetime object set to UTC."""
    result = _utcnow()
    assert result.tzinfo is not None
    assert result.tzinfo == timezone.utc

def test_utcnow_is_current():
    """Test that _utcnow returns a time close to the current time."""
    now = datetime.now(timezone.utc)
    result = _utcnow()
    # Allowing a small delta in case of slight execution delay
    delta = result - now
    assert delta.total_seconds() < 1.0
    assert delta.total_seconds() >= 0.0
