import pytest
from bot.utils.url_validator import is_safe_url

def test_safe_urls():
    assert is_safe_url("http://example.com") is True
    assert is_safe_url("https://www.google.com/path?query=1") is True
    assert is_safe_url("http://8.8.8.8") is True
    assert is_safe_url("https://[2001:4860:4860::8888]/") is True
    assert is_safe_url("http://news.ycombinator.com/rss") is True

def test_blocked_hosts():
    blocked = [
        "redis", "db", "stf_redis", "stf_db", "stf_rsshub",
        "stf_worker", "stf_bot", "stf_admin", "stf_backup",
        "localhost", "localtest.me"
    ]
    for host in blocked:
        assert is_safe_url(f"http://{host}") is False
        assert is_safe_url(f"https://{host}/path") is False
        assert is_safe_url(f"http://{host.upper()}") is False

def test_blocked_private_ips():
    blocked_ips = [
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "127.0.1.1",
        "169.254.169.254",
        "[fc00::1]",
        "[fd12:3456:789a:1::1]",
        "[::1]",
    ]
    for ip in blocked_ips:
        assert is_safe_url(f"http://{ip}") is False
        assert is_safe_url(f"https://{ip}/path") is False

def test_edge_cases():
    assert is_safe_url("") is False
    assert is_safe_url("not a url") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("http://") is False
