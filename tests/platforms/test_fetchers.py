import pytest
from datetime import datetime, timezone
import feedparser
import time

from bot.platforms.fetchers import _parse_entries

def test_parse_entries_standard():
    entry = feedparser.FeedParserDict({
        "id": "post-1",
        "link": "https://example.com/post-1",
        "title": "Test Title <b>bold</b>",
        "summary": "This is a summary. <img src=\"https://example.com/img.jpg\">",
    })
    entry.published_parsed = time.strptime("2023-01-01 12:00:00", "%Y-%m-%d %H:%M:%S")

    feed = feedparser.FeedParserDict()
    feed.entries = [entry]

    posts = _parse_entries(feed)
    assert len(posts) == 1
    post = posts[0]

    assert post.post_id == "post-1"
    assert post.title == "Test Title bold"
    assert post.url == "https://example.com/post-1"
    assert post.description == "This is a summary."
    assert post.image_url == "https://example.com/img.jpg"
    assert post.has_video is False
    assert post.author == ""
    assert isinstance(post.published_at, datetime)
    assert post.published_at.tzinfo == timezone.utc

def test_parse_entries_image_extraction():
    # Test media_thumbnail
    entry1 = feedparser.FeedParserDict({"id": "1", "summary": "Summary"})
    entry1.media_thumbnail = [{"url": "https://example.com/thumb.jpg"}]
    feed1 = feedparser.FeedParserDict()
    feed1.entries = [entry1]

    posts = _parse_entries(feed1)
    assert posts[0].image_url == "https://example.com/thumb.jpg"

    # Test enclosures image/jpeg
    entry2 = feedparser.FeedParserDict({"id": "2", "summary": "Summary"})
    entry2.enclosures = [{"type": "image/jpeg", "url": "https://example.com/enc.jpg"}]
    feed2 = feedparser.FeedParserDict()
    feed2.entries = [entry2]

    posts = _parse_entries(feed2)
    assert posts[0].image_url == "https://example.com/enc.jpg"

    # Test fallback to img tag in summary
    entry3 = feedparser.FeedParserDict({
        "id": "3",
        "summary": 'Check this out <img class="test" src="https://example.com/img_tag.jpg" />'
    })
    feed3 = feedparser.FeedParserDict()
    feed3.entries = [entry3]

    posts = _parse_entries(feed3)
    assert posts[0].image_url == "https://example.com/img_tag.jpg"

def test_parse_entries_has_video():
    # Video in summary
    entry1 = feedparser.FeedParserDict({"summary": "This is a ViDeO post."})
    feed1 = feedparser.FeedParserDict()
    feed1.entries = [entry1]
    assert _parse_entries(feed1)[0].has_video is True

    # mp4 in url
    entry2 = feedparser.FeedParserDict({"link": "https://example.com/test.MP4"})
    feed2 = feedparser.FeedParserDict()
    feed2.entries = [entry2]
    assert _parse_entries(feed2)[0].has_video is True

def test_parse_entries_fallback_post_id():
    entry = feedparser.FeedParserDict({"link": "https://example.com/no-id"})
    feed = feedparser.FeedParserDict()
    feed.entries = [entry]
    assert _parse_entries(feed)[0].post_id == "https://example.com/no-id"

def test_parse_entries_truncation():
    # Title > 200 chars, Description > 500 chars
    long_title = "A" * 250
    long_summary = "B" * 600

    entry1 = feedparser.FeedParserDict({
        "title": long_title,
        "summary": long_summary
    })
    feed1 = feedparser.FeedParserDict()
    feed1.entries = [entry1]

    post = _parse_entries(feed1)[0]
    assert len(post.title) == 200
    assert len(post.description) == 500

    # Check if entries list is truncated to 10
    entries = [feedparser.FeedParserDict({"id": str(i)}) for i in range(15)]
    feed2 = feedparser.FeedParserDict()
    feed2.entries = entries

    posts = _parse_entries(feed2)
    assert len(posts) == 10
    assert posts[0].post_id == "0"
    assert posts[9].post_id == "9"
