import re
from bot.utils.alerts import _build_message

def test_build_message_basic():
    """Test basic formatting of _build_message with known severity."""
    msg = _build_message(
        severity="CRITICAL",
        title="System Down",
        body="The main server is not responding."
    )

    assert "🚨 <b>CRITICAL — System Down</b>" in msg
    assert "━━━━━━━━━━━━━━━━━━━━" in msg
    assert "The main server is not responding." in msg
    assert re.search(r"🕐 \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", msg)

def test_build_message_with_context():
    """Test formatting with additional context arguments."""
    msg = _build_message(
        severity="INFO",
        title="New User",
        body="User has registered.",
        user_id=12345,
        action_type="registration",
        session_id=None  # Should be excluded
    )

    assert "ℹ️ <b>INFO — New User</b>" in msg
    assert "User has registered." in msg
    assert "<b>User Id:</b> <code>12345</code>" in msg
    assert "<b>Action Type:</b> <code>registration</code>" in msg
    assert "Session Id" not in msg
    assert "None" not in msg

def test_build_message_fallback_icon():
    """Test fallback icon for unknown severity."""
    msg = _build_message(
        severity="UNKNOWN_SEVERITY",
        title="Unknown Event",
        body="Something happened."
    )

    assert "🔔 <b>UNKNOWN_SEVERITY — Unknown Event</b>" in msg
    assert "Something happened." in msg

def test_build_message_empty_body():
    """Test formatting when body is empty."""
    msg = _build_message(
        severity="WARNING",
        title="Low Disk Space",
        body="",
        disk="sda1",
        usage="90%"
    )

    assert "⚠️ <b>WARNING — Low Disk Space</b>" in msg
    assert "<b>Disk:</b> <code>sda1</code>" in msg
    assert "<b>Usage:</b> <code>90%</code>" in msg
