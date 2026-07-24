"""
SocialtoFeed — AI Service v3.2
DeepSeek integration. All AI operations in one place.
Single API call per post (combines all active operations).
FIX: Added missing aioredis import.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio  # noqa: F401 — keep for type hints in this module
from openai import AsyncOpenAI

from config.settings import config
from bot.models import LogModule
from bot.utils.logger import STFLogger

logger = logging.getLogger(__name__)
log = STFLogger(LogModule.AI)

_client: Optional[AsyncOpenAI] = None


def _ai_cache_key(operation: str, text: str, lang: str = "") -> str:
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"ai:{operation}:{text_hash}:{lang}"


async def _get_ai_cached(key: str) -> Optional[dict]:
    from bot.cache import get_redis  # PERF-4: shared pool
    try:
        r = await get_redis()
        val = await r.get(key)
        if val:
            return json.loads(val)
    except Exception:
        pass
    return None


async def _set_ai_cached(key: str, value: dict, ttl: int = 86400) -> None:
    try:
        from bot.cache import get_redis  # PERF-4
        r = await get_redis()
        await r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.deepseek.api_key,
            base_url=config.deepseek.base_url,
            timeout=config.deepseek.timeout,
            max_retries=config.deepseek.max_retries,
        )
    return _client


async def check_daily_limit(user_id: int) -> bool:
    """Returns True if user has AI calls remaining today."""
    try:
        from bot.cache import get_redis  # PERF-4
        r = await get_redis()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"ai:daily:{user_id}:{today}"
        count = await r.get(key)
        limit = config.deepseek.daily_limit_per_user
        if limit == 0:
            return True  # unlimited
        return int(count or 0) < limit
    except Exception:
        return True


async def increment_daily_usage(user_id: int) -> None:
    try:
        from bot.cache import get_redis  # PERF-4
        r = await get_redis()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"ai:daily:{user_id}:{today}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)
        await pipe.execute()
    except Exception:
        pass


async def process_post(
    post_text: str,
    user_id: int,
    user_language: str,
    post_language: str = "en",
    do_summary: bool = False,
    do_translate: bool = False,
    do_spam_check: bool = False,
    do_categorize: bool = False,
) -> dict:
    """
    Single AI call combining all requested operations.
    Returns dict with: summary, translation, is_spam, category, error
    """
    if not config.deepseek.is_configured:
        return {"error": "AI not configured"}

    if not post_text or len(post_text.strip()) < 30:
        return {}

    if not await check_daily_limit(user_id):
        return {"error": "Daily AI limit reached"}

    # Build operations list
    ops = []
    if do_summary:
        ops.append("summarize")
    if do_translate and post_language != user_language:
        ops.append(f"translate_to_{user_language}")
    if do_spam_check:
        ops.append("spam_check")
    if do_categorize:
        ops.append("categorize")

    if not ops:
        return {}

    # Check cache
    cache_key = _ai_cache_key(
        ":".join(ops), post_text[:500], user_language
    )
    cached = await _get_ai_cached(cache_key)
    if cached:
        return cached

    # Build prompt
    operations_desc = []
    if do_summary:
        operations_desc.append('- "summary": 1-2 sentence summary')
    if do_translate and post_language != user_language:
        lang_names = {
            "fa": "Persian/Farsi", "ar": "Arabic", "ru": "Russian",
            "zh": "Chinese", "tr": "Turkish", "de": "German",
            "fr": "French", "es": "Spanish", "hi": "Hindi",
            "pt": "Portuguese", "ja": "Japanese", "ko": "Korean",
        }
        lang_name = lang_names.get(user_language, user_language)
        operations_desc.append(f'- "translation": full translation to {lang_name}')
    if do_spam_check:
        operations_desc.append('- "is_spam": true/false (spam, ads, clickbait)')
    if do_categorize:
        operations_desc.append(
            '- "category": one of: news, tech, sports, entertainment, business, science, health, other'
        )

    prompt = (
        f"Analyze this social media post and return ONLY valid JSON with these fields:\n"
        + "\n".join(operations_desc)
        + f"\n\nPost:\n{post_text[:1000]}"
    )

    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model=config.deepseek.model_fast,
            messages=[
                {"role": "system", "content": "You are a JSON-only API. Return only valid JSON, no markdown."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=config.deepseek.max_tokens_summary + config.deepseek.max_tokens_translate,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        await increment_daily_usage(user_id)
        await _set_ai_cached(cache_key, result)
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"AI JSON parse error: {e}")
        return {"error": "AI response parse failed"}
    except Exception as e:
        logger.error(f"AI process_post error: {e}")
        return {"error": str(e)[:100]}


async def detect_language(text: str) -> Optional[str]:
    """Quick language detection using AI. Returns ISO 639-1 code or None."""
    if not config.deepseek.is_configured or not text:
        return None

    cache_key = _ai_cache_key("lang_detect", text[:200])
    cached = await _get_ai_cached(cache_key)
    if cached:
        return cached.get("lang")

    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model=config.deepseek.model_fast,
            messages=[
                {"role": "system", "content": "Return ONLY a JSON object: {\"lang\": \"ISO_CODE\"}"},
                {"role": "user", "content": f"Detect language: {text[:300]}"},
            ],
            max_tokens=20,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        await _set_ai_cached(cache_key, result, ttl=604800)  # 1 week
        return result.get("lang")
    except Exception as e:
        logger.debug(f"Language detection failed: {e}")
        return None


class AIService:
    @staticmethod
    async def health_check() -> bool:
        """Simple ping to check AI service status."""
        if not config.deepseek.is_configured:
            return False
        try:
            client = _get_client()
            resp = await client.chat.completions.create(
                model=config.deepseek.model_fast,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False

    @staticmethod
    async def answer_question(text: str, lang: str = "en") -> str:
        """Answers a user question directly."""
        if not config.deepseek.is_configured:
            return "Sorry, AI is not configured right now."

        system_prompt = "You are a helpful assistant."
        if lang == "fa":
            system_prompt += " Answer in Persian/Farsi."

        try:
            client = _get_client()
            resp = await client.chat.completions.create(
                model=config.deepseek.model_fast,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=1000,
                temperature=0.7,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"AI answer_question error: {e}")
            raise

    @staticmethod
    async def extract_audio_link(original_url: str) -> Optional[dict]:
        """Extract audio link using video_extractor."""
        try:
            from bot.services.video_extractor import extract_video_info
            info = await extract_video_info(original_url)

            if info and info.qualities:
                # Pick the best quality that has audio
                qualities_with_audio = [q for q in info.qualities if q.has_audio]
                if qualities_with_audio:
                    best = max(qualities_with_audio, key=lambda q: q.height)
                    return {"url": best.url, "title": info.title, "duration": info.duration_seconds, "filesize_mb": best.filesize_mb, "ext": best.ext}
        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")

        return None
