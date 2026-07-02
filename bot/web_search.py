"""
Multi-engine web search for AI Mega Bot — DuckDuckGo HTML → SearXNG → Yandex.

Used to verify/supplement news, events, facts, prices that come up in chat.
All endpoints are free and require NO API keys. Results are returned as a
formatted context string that is injected into the AI prompt so the model can
USE the web info in its answer (not just append a URL).
"""

import asyncio
import logging
import re
from typing import Dict, List
from urllib.parse import quote_plus

import httpx

from bot.config import config

logger = logging.getLogger("mega.web_search")


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str = "", source: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source


_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&#39;|&apos;", "'", s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    return re.sub(r"\s+", " ", s).strip()


async def search_ddg_html(query: str, max_results: int = 5) -> List[SearchResult]:
    results: List[SearchResult] = []
    try:
        async with httpx.AsyncClient(timeout=config.SEARCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            params = {"q": query, "kl": "ru-ru", "no_redirect": "1"}
            resp = await client.get("https://html.duckduckgo.com/html/", params=params, headers=_HEADERS)
            if resp.status_code == 202:
                resp = await client.get("https://lite.duckduckgo.com/lite/",
                                        params={"q": query, "kl": "ru-ru"}, headers=_HEADERS)
                if resp.status_code != 200:
                    return results
                urls = re.findall(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"', resp.text)
                titles = re.findall(r'<a[^>]+class="result-link"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
                snippets = re.findall(r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>', resp.text, re.DOTALL)
                for i, url in enumerate(urls[:max_results]):
                    title = _clean_html(titles[i]) if i < len(titles) else ""
                    snippet = _clean_html(snippets[i]) if i < len(snippets) else ""
                    if url and title:
                        results.append(SearchResult(title, url, snippet, "duckduckgo_lite"))
                return results
            if resp.status_code != 200:
                return results
            blocks = re.findall(
                r'<a rel="nofollow" class="result__a" href="([^"]+?)".*?>(.*?)</a>.*?'
                r'<a class="result__snippet".*?>(.*?)</a>',
                resp.text, re.DOTALL,
            )
            for url, title, snippet in blocks[:max_results]:
                results.append(SearchResult(_clean_html(title), url, _clean_html(snippet), "duckduckgo"))
    except Exception as e:
        logger.debug(f"DDG search error: {e}")
    return results


async def search_searxng(query: str, max_results: int = 5) -> List[SearchResult]:
    results: List[SearchResult] = []
    instances = [
        "https://searx.be/search",
        "https://search.sapti.me/search",
        "https://searx.tiekoetter.com/search",
    ]
    for instance in instances:
        try:
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
                resp = await client.get(instance, params={"q": query, "format": "html"}, headers=_HEADERS)
            if resp.status_code != 200:
                continue
            urls = re.findall(r'<h[34]>.*?<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
            for url, title in urls[:max_results]:
                title = _clean_html(title)
                if url and title and "searx" not in url:
                    results.append(SearchResult(title=title, url=url, source="searxng"))
            if results:
                break
        except Exception as e:
            logger.debug(f"SearXNG search error ({instance}): {e}")
    return results


async def search_yandex(query: str, max_results: int = 5) -> List[SearchResult]:
    results: List[SearchResult] = []
    try:
        async with httpx.AsyncClient(timeout=config.SEARCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = await client.get(
                "https://yandex.ru/search/",
                params={"text": query, "lr": 213},
                headers={**_HEADERS, "Cookie": "yandex_gid=213"},
            )
            if resp.status_code != 200:
                return results
            blocks = re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', resp.text)
            for url, title in blocks[:max_results]:
                title = _clean_html(title)
                if title and len(title) > 5 and "yandex" not in url:
                    results.append(SearchResult(title, url, "", "yandex"))
    except Exception as e:
        logger.debug(f"Yandex search error: {e}")
    return results


async def web_search(query: str, max_results: int = 5) -> List[SearchResult]:
    """Try DDG first, then SearXNG, then Yandex. Returns combined unique results."""
    results = await search_ddg_html(query, max_results=max_results)
    if not results:
        results = await search_searxng(query, max_results=max_results)
    if not results:
        results = await search_yandex(query, max_results=max_results)
    seen = set()
    unique = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            unique.append(r)
    return unique[:max_results]


def format_search_results(results: List[SearchResult], max_items: int = 3) -> str:
    if not results:
        return ""
    lines = []
    for r in results[:max_items]:
        snippet = f" — {r.snippet}" if r.snippet else ""
        lines.append(f"• {r.title}{snippet}\n  {r.url}")
    return "\n".join(lines)


async def verify_claim(claim: str, fast: bool = True) -> str:
    """Quick verify/supplement a claim via web search (5s). Returns formatted context."""
    timeout = 5.0 if fast else config.SEARCH_TIMEOUT_SECONDS
    try:
        results = await asyncio.wait_for(web_search(claim, max_results=3), timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        return ""
    if not results:
        return ""
    return format_search_results(results, max_items=2)


async def fetch_article(url: str, max_chars: int = 1500) -> str:
    """Fetch a URL and extract its main text content (best-effort).

    Returns up to max_chars of cleaned text. Used to give Василий detailed
    context for supplementing news/events — not just the search snippet.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(url, headers=_HEADERS)
        if r.status_code != 200:
            return ""
        html = r.text
        # Remove scripts/styles/nav
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Prefer <article> / <main> / <p> content
        article = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL | re.IGNORECASE)
        if article:
            html = article.group(1)
        else:
            main = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
            if main:
                html = main.group(1)
        # Extract paragraph text
        paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
        if not paras:
            paras = [html]
        text = "\n".join(_clean_html(p) for p in paras)
        text = re.sub(r"\s+", " ", text).strip()
        # Filter out very short / nav-like fragments
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 30]
        out = " ".join(sentences)
        return out[:max_chars]
    except Exception as e:
        logger.debug(f"fetch_article error ({url}): {e}")
        return ""


async def research_topic(topic: str, max_queries: int = 2) -> str:
    """Deep research a news/event topic for detailed supplementation.

    Strategy:
      1. Run up to max_queries search variations (original + simplified).
      2. From combined results, fetch the top 2 articles' full content.
      3. Return a rich context block: titles + snippets + article excerpts + URLs.

    This is what powers Василий's "развёрнуто дополнять события и новости".
    Timeout: ~20s total (2 searches + 2 article fetches, concurrent).
    """
    topic = (topic or "").strip()
    if len(topic) < 5:
        return ""

    # Build query variations: original + a shortened version (first ~60 chars)
    queries = [topic[:300]]
    short = topic[:60].split("—")[0].split(":")[0].strip()
    if short and short.lower() != topic[:60].lower():
        queries.append(short)

    # Run searches concurrently
    async def _q(q: str) -> List[SearchResult]:
        try:
            return await asyncio.wait_for(web_search(q, max_results=5), timeout=8.0)
        except (asyncio.TimeoutError, Exception):
            return []

    search_results_lists = await asyncio.gather(*[_q(q) for q in queries[:max_queries]])
    # Flatten + dedup by URL
    seen = set()
    all_results: List[SearchResult] = []
    for lst in search_results_lists:
        for r in lst:
            if r.url not in seen:
                seen.add(r.url)
                all_results.append(r)
    if not all_results:
        return ""

    # Fetch top 2 articles' full content (concurrent, 8s each)
    top = all_results[:2]
    articles = await asyncio.gather(*[fetch_article(r.url, max_chars=1200) for r in top])

    # Assemble rich context
    lines = [f"Развёрнутые результаты веб-поиска по теме «{topic[:80]}»:"]
    for i, r in enumerate(all_results[:4]):
        snippet = f" — {r.snippet}" if r.snippet else ""
        lines.append(f"\n[{i+1}] {r.title}{snippet}\n    {r.url}")
    for i, (r, content) in enumerate(zip(top, articles)):
        if content:
            lines.append(f"\nСодержание статьи [{i+1}] ({r.title[:60]}):\n{content}")
    lines.append(
        "\nИспользуй эти данные чтобы РАЗВЁРНУТО дополнить ответ: приведи "
        "конкретные факты, цифры, даты, контекст. Упомяни источник ссылкой."
    )
    return "\n".join(lines)


def first_url(context: str) -> str:
    """Extract the first URL from a web-search context string."""
    m = re.search(r"https?://\S+", context or "")
    return m.group(0) if m else ""


def all_urls(context: str) -> list:
    """Extract all URLs from a web-search context string."""
    return re.findall(r"https?://\S+", context or "")
