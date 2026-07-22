import pytest
from bot.services.platform_resolver import _autodiscover_rss

def test_autodiscover_rss_type_first():
    """Test when type='application/rss+xml' appears before href."""
    html = '<html><head><link rel="alternate" type="application/rss+xml" title="RSS" href="https://example.com/feed.xml"></head></html>'
    base_url = "https://example.com"
    assert _autodiscover_rss(html, base_url) == "https://example.com/feed.xml"

def test_autodiscover_rss_href_first():
    """Test when href appears before type='application/rss+xml'."""
    html = '<html><head><link rel="alternate" href="https://example.com/rss.xml" type="application/rss+xml" title="RSS"></head></html>'
    base_url = "https://example.com"
    assert _autodiscover_rss(html, base_url) == "https://example.com/rss.xml"

def test_autodiscover_atom():
    """Test matching for type='application/atom+xml'."""
    html = '<html><head><link rel="alternate" type="application/atom+xml" title="Atom" href="https://example.com/atom.xml"></head></html>'
    base_url = "https://example.com"
    assert _autodiscover_rss(html, base_url) == "https://example.com/atom.xml"

def test_autodiscover_case_insensitive():
    """Test case insensitivity."""
    html = '<html><head><LINK REL="alternate" TYPE="application/rss+xml" HREF="https://example.com/FEED.XML"></head></html>'
    base_url = "https://example.com"
    assert _autodiscover_rss(html, base_url) == "https://example.com/FEED.XML"

def test_autodiscover_relative_url():
    """Test relative URLs resolving correctly using the base_url."""
    html = '<html><head><link rel="alternate" type="application/rss+xml" title="RSS" href="/feed.xml"></head></html>'
    base_url = "https://example.com/some/path"
    assert _autodiscover_rss(html, base_url) == "https://example.com/feed.xml"

def test_autodiscover_multiple_links():
    """Test document containing multiple link tags (ensuring it ignores stylesheets and picks the RSS link)."""
    html = '''
    <html>
    <head>
        <link rel="stylesheet" href="/style.css" type="text/css">
        <link rel="shortcut icon" href="/favicon.ico">
        <link rel="alternate" type="application/rss+xml" title="RSS" href="https://example.com/feed.xml">
    </head>
    </html>
    '''
    base_url = "https://example.com"
    assert _autodiscover_rss(html, base_url) == "https://example.com/feed.xml"

def test_autodiscover_no_rss():
    """Test a document with no matching RSS link returning None."""
    html = '<html><head><link rel="stylesheet" href="/style.css" type="text/css"></head></html>'
    base_url = "https://example.com"
    assert _autodiscover_rss(html, base_url) is None
