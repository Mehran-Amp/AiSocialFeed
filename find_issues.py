import glob
import re

account = "Mehran-Amp"
project = "AiSocialFeed"
hash = "4bd0c4c8fc7d39a616e6db89587d93b3056a648a"

issues = []

def _get_context(filepath, lineno):
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
            start = max(0, lineno - 10)
            end = min(len(lines), lineno + 10)
            return "".join(lines[start:end])
    except Exception:
        return ""

def add_issue(title, desc, filepath, lineno, confidence, rationale, category, impact, lang):
    context = _get_context(filepath, lineno)
