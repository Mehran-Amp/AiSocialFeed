import pytest
import hashlib
from bot.models import SentPost, Bookmark

def test_sentpost_make_hash():
    url = "https://example.com/post/123"
    expected_hash = hashlib.sha256(url.encode()).hexdigest()
    assert SentPost.make_hash(url) == expected_hash

def test_bookmark_make_hash():
    url = "https://example.com/post/456"
    expected_hash = hashlib.sha256(url.encode()).hexdigest()
    assert Bookmark.make_hash(url) == expected_hash

def test_make_hash_empty_string():
    url = ""
    expected_hash = hashlib.sha256(url.encode()).hexdigest()
    assert SentPost.make_hash(url) == expected_hash
    assert Bookmark.make_hash(url) == expected_hash

def test_make_hash_special_chars():
    url = "https://example.com/post/?q=123&test=true#hash!@#$%^&*()"
    expected_hash = hashlib.sha256(url.encode()).hexdigest()
    assert SentPost.make_hash(url) == expected_hash
    assert Bookmark.make_hash(url) == expected_hash
