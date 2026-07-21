"""
AiSocialFeed — Import-level test suite
Catches compile errors and missing imports before deployment.
Run: python -m pytest tests/ -v
"""
import importlib
import pytest


CRITICAL_MODULES = [
    "bot.platforms.base",
    "bot.platforms.fetchers",
    "bot.services.ai_service",
    "bot.services.payment_service",
    "bot.services.plan_service",
    "bot.services.platform_resolver",
    "bot.utils.url_validator",
    "worker.tasks",
    "worker.growth",
    "worker.infra",
    "config.settings",
]


@pytest.mark.parametrize("module_path", CRITICAL_MODULES)
def test_module_imports_cleanly(module_path):
    """Each critical module must import without SyntaxError or ImportError."""
    mod = importlib.import_module(module_path)
    assert mod is not None


def test_platform_registry_complete():
    """All 13 platforms must be registered in PLATFORM_FETCHERS."""
    from bot.platforms.fetchers import PLATFORM_FETCHERS
    from bot.models import Platform
    for platform in Platform:
        assert platform in PLATFORM_FETCHERS, f"Platform.{platform.name} missing from registry"


def test_rsshub_config_exists():
    """RSSHubConfig must be defined and instantiatable."""
    from config.settings import RSSHubConfig
    cfg = RSSHubConfig()
    assert hasattr(cfg, "url")
    assert hasattr(cfg, "cookie_twitter")


def test_payment_service_exports():
    """payment_service must export all three functions."""
    from bot.services.payment_service import (
        get_deposit_address,
        check_deposit,
        start_payment_monitor,
    )
    import asyncio
    assert asyncio.iscoroutinefunction(get_deposit_address)
    assert asyncio.iscoroutinefunction(check_deposit)
    assert asyncio.iscoroutinefunction(start_payment_monitor)


def test_no_sync_await_in_format_post():
    """_format_post must be async (BUG-1 regression test)."""
    import asyncio
    from bot.platforms.base import BasePlatformFetcher
    assert asyncio.iscoroutinefunction(BasePlatformFetcher._format_post)


def test_ssrf_validator():
    """SSRF validator must block internal hosts and private IPs."""
    from bot.utils.url_validator import is_safe_url
    assert not is_safe_url("http://redis:6379")
    assert not is_safe_url("http://db:5432")
    assert not is_safe_url("http://127.0.0.1/feed")
    assert not is_safe_url("http://192.168.1.1/feed")
    assert not is_safe_url("http://10.0.0.1/rss")
    assert is_safe_url("https://example.com/feed.rss")
    assert is_safe_url("https://news.ycombinator.com/rss")
