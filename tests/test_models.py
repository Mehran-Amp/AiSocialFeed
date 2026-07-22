import datetime
from bot.models import SystemLog, LogLevel, LogModule, Platform

def test_systemlog_to_debug_dict():
    """Test full serialization of a SystemLog."""
    dt = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    log = SystemLog(
        id=123,
        level=LogLevel.ERROR,
        module=LogModule.BOT,
        message="Test message",
        user_id=456,
        account_id=789,
        platform=Platform.YOUTUBE,
        details={"trace": "some trace"},
        extra={"ip": "127.0.0.1"},
        resolved=False,
        created_at=dt
    )

    result = log.to_debug_dict()

    assert result == {
        "id": 123,
        "time": dt.isoformat(),
        "level": "ERROR",
        "module": "bot",
        "message": "Test message",
        "user_id": 456,
        "account_id": 789,
        "platform": "youtube",
        "details": {"trace": "some trace"},
        "extra": {"ip": "127.0.0.1"},
        "resolved": False,
    }

def test_systemlog_to_debug_dict_minimal():
    """Test serialization of a SystemLog with minimal fields."""
    log = SystemLog(
        level=LogLevel.INFO,
        module=LogModule.SYSTEM,
        message="Minimal log",
        created_at=None,
    )

    result = log.to_debug_dict()

    assert result["id"] is None
    assert result["time"] is None
    assert result["level"] == "INFO"
    assert result["module"] == "system"
    assert result["message"] == "Minimal log"
    assert result["user_id"] is None
    assert result["account_id"] is None
    assert result["platform"] is None
    assert result["details"] is None
    assert result["extra"] is None
    assert result["resolved"] is None or result["resolved"] is False
