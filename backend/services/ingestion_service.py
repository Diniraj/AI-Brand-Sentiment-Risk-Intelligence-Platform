import os
import json
import time
import hashlib
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from datetime import datetime

import requests
from bs4 import BeautifulSoup


class IngestionService:
    """
    Discovery: Serper (Google Search API) -> URLs + snippets
    Scraping:  Apify actor (optional) -> page text

    Env supported:
    - SERPER_API_KEY (preferred) or SERPAPI_API_KEY (fallback to support your current .env key name)
    - APIFY_API_TOKEN
    - APIFY_ACTOR_ID (optional; default tries a reasonable crawler actor id)
    """

    def __init__(self) -> None:
        self.serper_key = (os.getenv("SERPER_API_KEY") or os.getenv("SERPAPI_API_KEY") or "").strip().strip('"')
        self.apify_token = (os.getenv("APIFY_API_TOKEN") or "").strip().strip('"')
        self.apify_enabled = str(os.getenv("APIFY_ENABLED") or "0").strip().lower() in {"1", "true", "yes", "on"}
        # Use a lightweight actor by default (low memory / demo-safe).
        self.apify_actor_id = (os.getenv("APIFY_ACTOR_ID") or "apify/google-search-scraper").strip().strip('"')
        self.cache_path = (os.getenv("INGESTION_CACHE_PATH") or "ingestion_cache.json").strip().strip('"')
        self.cache_ttl_s = int(os.getenv("INGESTION_CACHE_TTL_S") or "1800")  # 30 mins
        self.apify_wait_s = int(os.getenv("APIFY_WAIT_S") or "60")
        self.apify_memory_mbytes = int(os.getenv("APIFY_MEMORY_MBYTES") or "512")
        self.apify_max_queries = int(os.getenv("APIFY_MAX_QUERIES") or "3")
        self.max_pages_per_query = int(os.getenv("APIFY_MAX_PAGES_PER_QUERY") or "1")
        self.results_per_page = int(os.getenv("APIFY_RESULTS_PER_PAGE") or "3")
        self.max_total_items = int(os.getenv("APIFY_MAX_TOTAL_ITEMS") or "12")
        self.cache_schema_version = "2"

        self._mem_cache: Dict[str, Dict[str, Any]] = {}

    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                )
            }
        )
        return session

    def build_queries(self, brand: str, keywords: List[str], sources: Optional[List[str]] = None) -> List[str]:
        base = [f"{brand} {k}".strip() for k in keywords if str(k).strip()]
        site_filters = self._sources_to_site_filters(sources or [])
        expanded: List[str] = []
        for q in base:
            variants = [
                f"{q} complaints",
                f"{q} reviews",
                f"{q} service issue",
                f"{q} bad experience",
                f"{q} scam",
            ]
            if site_filters:
                for sf in site_filters:
                    expanded.extend([f"{v} {sf}".strip() for v in variants])
            else:
                expanded.extend(variants)
        # de-dupe while preserving order
        seen = set()
        out: List[str] = []
        for q in expanded:
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            out.append(q)
        return out[:20]

    def _source_queries(self, brand: str, keywords: List[str]) -> List[Tuple[str, str]]:
        queries: List[Tuple[str, str]] = [(brand, "brand")]
        for keyword in keywords:
            cleaned = str(keyword).strip()
            if cleaned:
                queries.append((cleaned, "product"))
        return queries

    def serper_search(self, query: str, num: int = 10) -> Dict[str, Any]:
        if not self.serper_key:
            raise RuntimeError("Missing SERPER_API_KEY (or SERPAPI_API_KEY) in environment")

        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": self.serper_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": max(1, min(int(num), 20))}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _reddit_mentions(
        self, session: requests.Session, query: str, matched_on: str, limit: int
    ) -> List[Dict[str, Any]]:
        response = session.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "sort": "new", "limit": max(1, min(limit, 10))},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        items: List[Dict[str, Any]] = []
        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            permalink = data.get("permalink", "")
            url = f"https://www.reddit.com{permalink}" if permalink else ""
            text = " ".join(filter(None, [data.get("title"), data.get("selftext")])).strip()
            source_meta = self._source_meta(url)
            items.append(
                {
                    "text": text,
                    "url": url,
                    "title": data.get("title") or "",
                    "snippet": data.get("selftext") or "",
                    "site_name": "Reddit",
                    "domain": source_meta["domain"],
                    "source_type": "reddit",
                    "provider": "reddit",
                    "query": query,
                    "matched_on": matched_on,
                    "author": data.get("author") or "unknown",
                    "published_at": datetime.utcfromtimestamp(data.get("created_utc", 0)).isoformat(),
                }
            )
        return items

    def _serper_site_mentions(
        self,
        session: requests.Session,
        query: str,
        matched_on: str,
        limit: int,
        source_name: str,
        site_filters: List[str],
        source_type: str,
    ) -> List[Dict[str, Any]]:
        if not self.serper_key:
            return []
        search_query = f"{query} ({' OR '.join(site_filters)})" if site_filters else query
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": self.serper_key, "Content-Type": "application/json"},
            json={"q": search_query, "num": max(1, min(limit, 10))},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        items: List[Dict[str, Any]] = []
        for item in payload.get("organic", [])[:limit]:
            url = (item.get("link") or "").strip()
            source_meta = self._source_meta(url)
            items.append(
                {
                    "text": (item.get("snippet") or item.get("title") or "").strip(),
                    "url": url,
                    "title": item.get("title") or "",
                    "snippet": item.get("snippet") or "",
                    "site_name": source_name,
                    "domain": source_meta["domain"],
                    "source_type": source_type or source_meta["source_type"],
                    "provider": "serper",
                    "query": query,
                    "matched_on": matched_on,
                    "author": item.get("source") or source_name,
                    "published_at": item.get("date") or "",
                }
            )
        return items

    def _complaints_board_mentions(
        self, session: requests.Session, query: str, matched_on: str, limit: int
    ) -> List[Dict[str, Any]]:
        url = f"https://www.complaintsboard.com/?search={requests.utils.quote(query)}"
        response = session.get(url, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select("article")[:limit]
        items: List[Dict[str, Any]] = []
        for card in cards:
            heading = card.select_one("h2, h3")
            link = card.select_one("a[href]")
            snippet = card.get_text(" ", strip=True)
            if not heading and not link:
                continue
            href = link["href"] if link and link.has_attr("href") else url
            if href.startswith("/"):
                href = f"https://www.complaintsboard.com{href}"
            items.append(
                {
                    "text": snippet[:500],
                    "url": href,
                    "title": heading.get_text(" ", strip=True) if heading else "",
                    "snippet": snippet[:500],
                    "site_name": "ComplaintsBoard",
                    "domain": "complaintsboard.com",
                    "source_type": "complaints",
                    "provider": "complaintsboard",
                    "query": query,
                    "matched_on": matched_on,
                    "author": "ComplaintsBoard",
                    "published_at": "",
                }
            )
        return items

    def _scrape_selected_sources(
        self, brand: str, keywords: List[str], sources: List[str], limit: int = 5
    ) -> List[Dict[str, Any]]:
        session = self._session()
        selected_sources = sources or ["reddit", "youtube", "twitter", "reviews", "complaints", "web"]
        provider_map = {
            "reddit": lambda q, m: self._reddit_mentions(session, q, m, limit),
            "youtube": lambda q, m: self._serper_site_mentions(
                session, q, m, limit, "YouTube", ["site:youtube.com", "site:m.youtube.com"], "youtube"
            ),
            "twitter": lambda q, m: self._serper_site_mentions(
                session, q, m, limit, "X", ["site:x.com", "site:twitter.com"], "twitter"
            ),
            "facebook": lambda q, m: self._serper_site_mentions(
                session, q, m, limit, "Facebook", ["site:facebook.com"], "facebook"
            ),
            "instagram": lambda q, m: self._serper_site_mentions(
                session, q, m, limit, "Instagram", ["site:instagram.com"], "instagram"
            ),
            "reviews": lambda q, m: self._serper_site_mentions(
                session,
                q,
                m,
                limit,
                "Reviews",
                ["site:trustpilot.com", "site:g2.com", "site:capterra.com", "site:sitejabber.com"],
                "reviews",
            ),
            "complaints": lambda q, m: self._complaints_board_mentions(session, q, m, limit),
            "web": lambda q, m: self._serper_site_mentions(session, q, m, limit, "Web", [], "web"),
            "news": lambda q, m: self._serper_site_mentions(
                session,
                q,
                m,
                limit,
                "News",
                ["site:news.google.com", "site:reuters.com", "site:bloomberg.com", "site:bbc.com"],
                "news",
            ),
            "app_reviews": lambda q, m: self._serper_site_mentions(
                session,
                q,
                m,
                limit,
                "App Reviews",
                ["site:play.google.com", "site:apps.apple.com"],
                "app_reviews",
            ),
        }

        items: List[Dict[str, Any]] = []
        for source in selected_sources:
            provider = provider_map.get(source)
            if not provider:
                continue
            for query, matched_on in self._source_queries(brand, keywords):
                try:
                    items.extend(provider(query, matched_on))
                except Exception:
                    continue
        return self._dedupe_items(items)

    def discover(self, queries: List[str], per_query: int = 5) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
        if not self.serper_key:
            raise RuntimeError("Missing SERPER_API_KEY (or SERPAPI_API_KEY) in environment")
        urls: List[str] = []
        snippets: List[str] = []
        items: List[Dict[str, Any]] = []

        for q in queries:
            try:
                data = self.serper_search(q, num=per_query)
                organic = data.get("organic") or []
                for item in organic:
                    link = (item.get("link") or "").strip()
                    title = (item.get("title") or "").strip()
                    snippet = (item.get("snippet") or "").strip()
                    if link:
                        urls.append(link)
                    if snippet:
                        snippets.append(snippet)
                    text = " ".join(part for part in [title, snippet] if part).strip()
                    if link or text:
                        source_meta = self._source_meta(link)
                        items.append(
                            {
                                "text": text or snippet or title or link,
                                "url": link,
                                "title": title,
                                "snippet": snippet,
                                "site_name": source_meta["site_name"],
                                "domain": source_meta["domain"],
                                "source_type": source_meta["source_type"],
                                "provider": "serper",
                                "query": q,
                            }
                        )
            except Exception:
                continue

        urls = self._dedupe(urls)[:30]
        snippets = self._dedupe(snippets)[:50]
        return urls, snippets, self._dedupe_items(items)[:50]

    def scrape_with_apify(self, urls: List[str], wait_secs: int = 120) -> List[str]:
        # Deprecated: we keep a fallback HTML fetcher below, but avoid heavy Apify crawling.
        return []

    def apify_google_search(self, queries: List[str]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
        """
        Lightweight Apify actor: apify/google-search-scraper
        Returns (urls, snippets) extracted from title/description.
        """
        if not self.apify_enabled or not self.apify_token or not queries:
            return [], [], []

        actor_id_for_url = self.apify_actor_id.replace("/", "~")
        run_url = f"https://api.apify.com/v2/acts/{actor_id_for_url}/run-sync-get-dataset-items"
        params = {
            "token": self.apify_token,
            "memory": str(max(128, min(self.apify_memory_mbytes, 1024))),
            "timeout": str(max(30, min(self.apify_wait_s, 120))),
            "clean": "true",
        }

        q_objs = []
        for q in queries[: max(1, min(self.apify_max_queries, 5))]:
            q_objs.append(
                {
                    "query": q,
                    "maxPagesPerQuery": max(1, min(self.max_pages_per_query, 2)),
                    "resultsPerPage": max(1, min(self.results_per_page, 5)),
                }
            )

        actor_input: Dict[str, Any] = {
            "queries": q_objs,
            "maxPagesPerQuery": max(1, min(self.max_pages_per_query, 2)),
            "resultsPerPage": max(1, min(self.results_per_page, 5)),
        }

        resp = requests.post(run_url, params=params, json=actor_input, timeout=90)
        resp.raise_for_status()
        items = resp.json()

        urls: List[str] = []
        snippets: List[str] = []
        items_out: List[Dict[str, Any]] = []
        count = 0
        if isinstance(items, list):
            for it in items:
                if count >= self.max_total_items:
                    break
                if not isinstance(it, dict):
                    continue
                url = (it.get("url") or it.get("link") or "").strip()
                title = (it.get("title") or "").strip()
                desc = (it.get("description") or it.get("snippet") or "").strip()
                if url:
                    urls.append(url)
                text = " ".join([title, desc]).strip()
                if text:
                    snippets.append(text)
                if url or text:
                    source_meta = self._source_meta(url)
                    items_out.append(
                        {
                            "text": text or title or desc or url,
                            "url": url,
                            "title": title,
                            "snippet": desc,
                            "site_name": source_meta["site_name"],
                            "domain": source_meta["domain"],
                            "source_type": source_meta["source_type"],
                            "provider": "apify",
                            "query": (it.get("searchQuery") or it.get("query") or "").strip(),
                        }
                    )
                count += 1

        return self._dedupe(urls)[:30], self._dedupe(snippets)[:50], self._dedupe_items(items_out)[:50]

    def scrape_fallback_requests(self, urls: List[str]) -> List[str]:
        texts: List[str] = []
        headers = {"User-Agent": "Mozilla/5.0 (compatible; BrandRiskBot/1.0)"}
        for u in urls[:10]:
            try:
                r = requests.get(u, headers=headers, timeout=20)
                if r.status_code >= 400:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = " ".join(soup.get_text(" ").split())
                if len(text) >= 200:
                    texts.append(text[:2000])
            except Exception:
                continue
        return self._dedupe(texts)[:20]

    def ingest_posts(
        self,
        brand: str,
        keywords: List[str],
        sources: Optional[List[str]] = None,
        per_query: int = 5,
        prefer_apify: bool = True,
    ) -> Dict[str, Any]:
        sources_norm = self._normalize_sources(sources or [])
        queries = self.build_queries(brand, keywords, sources=sources_norm)

        cache_key = self._cache_key(brand=brand, keywords=keywords, sources=sources_norm)
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        # Discovery layer: Serper first (cheap + fast); Apify search-scraper as fallback.
        urls: List[str] = []
        snippets: List[str] = []
        items: List[Dict[str, Any]] = []
        serper_error: Optional[str] = None
        apify_error: Optional[str] = None

        try:
            items = self._scrape_selected_sources(brand, keywords, sources_norm, limit=max(3, per_query))
            urls = [item.get("url", "") for item in items if item.get("url")]
            snippets = [item.get("text", "") for item in items if item.get("text")]
            if not items:
                urls, snippets, items = self.discover(queries, per_query=per_query)
        except Exception as e:
            serper_error = str(e)
            urls, snippets, items = [], [], []

        if (not urls and not snippets) and prefer_apify:
            try:
                urls, snippets, items = self.apify_google_search(queries)
            except Exception as e:
                apify_error = str(e)
                urls, snippets, items = [], [], []

        scraped: List[str] = []
        # Keep scraping minimal for demo-safety: only a few pages via requests if we have URLs.
        if urls:
            scraped = self.scrape_fallback_requests(urls)

        scraped_items: List[Dict[str, Any]] = []
        for url, text in zip(urls[: len(scraped)], scraped):
            source_meta = self._source_meta(url)
            scraped_items.append(
                {
                    "text": text,
                    "url": url,
                    "title": "",
                    "snippet": "",
                    "site_name": source_meta["site_name"],
                    "domain": source_meta["domain"],
                    "source_type": source_meta["source_type"],
                    "provider": "requests",
                    "query": "",
                }
            )

        combined_items = self._dedupe_items([*items, *scraped_items])
        combined_items = [item for item in combined_items if self._is_live_source_item(item)]
        posts = [item["text"] for item in combined_items if isinstance(item.get("text"), str) and item["text"].strip()]
        posts = posts[:50]
        combined_items = combined_items[:50]

        result = {
            "sources": sources_norm,
            "queries": queries,
            "urls": urls,
            "items": combined_items,
            "snippets_count": len(snippets),
            "scraped_count": len(scraped),
            "serper_error": serper_error,
            "apify_error": apify_error,
            "apify_enabled": self.apify_enabled,
            "posts": posts,
        }
        self._cache_set(cache_key, result)
        return result

    def _cache_key(self, brand: str, keywords: List[str], sources: List[str]) -> str:
        payload = {
            "schema_version": self.cache_schema_version,
            "brand": brand.strip().lower(),
            "keywords": [str(k).strip().lower() for k in keywords if str(k).strip()],
            "sources": sources,
            "max_pages_per_query": self.max_pages_per_query,
            "results_per_page": self.results_per_page,
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        hit = self._mem_cache.get(key)
        if hit and (now - float(hit.get("_cached_at", 0))) <= self.cache_ttl_s:
            return {k: v for k, v in hit.items() if k != "_cached_at"}

        try:
            if not self.cache_path:
                return None
            if not os.path.exists(self.cache_path):
                return None
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            entry = data.get(key)
            if not isinstance(entry, dict):
                return None
            if (now - float(entry.get("_cached_at", 0))) > self.cache_ttl_s:
                return None
            if not self._is_cache_entry_usable(entry):
                return None
            # warm mem cache
            self._mem_cache[key] = entry
            return {k: v for k, v in entry.items() if k != "_cached_at"}
        except Exception:
            return None

    def _cache_set(self, key: str, value: Dict[str, Any]) -> None:
        now = time.time()
        entry = {**value, "_cached_at": now}
        self._mem_cache[key] = entry
        try:
            if not self.cache_path:
                return
            existing: Dict[str, Any] = {}
            if os.path.exists(self.cache_path):
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    existing = json.load(f) or {}
            existing[key] = entry
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(existing, f)
        except Exception:
            pass

    @staticmethod
    def _is_cache_entry_usable(entry: Dict[str, Any]) -> bool:
        items = entry.get("items")
        if not isinstance(items, list):
            return False
        if not items:
            return True
        sample = items[0]
        if not isinstance(sample, dict):
            return False
        # Ignore older cache shapes that did not preserve source metadata.
        if "site_name" not in sample and "source_type" not in sample and "domain" not in sample:
            return False
        return True

    @staticmethod
    def _normalize_sources(sources: List[str]) -> List[str]:
        allowed = {
            "all",
            "web",
            "youtube",
            "reddit",
            "news",
            "twitter",
            "x",
            "facebook",
            "instagram",
            "tiktok",
            "app_reviews",
            "reviews",
            "complaints",
        }
        out: List[str] = []
        for s in sources:
            ss = str(s).strip().lower()
            if not ss:
                continue
            if ss not in allowed:
                continue
            if ss == "x":
                ss = "twitter"
            if ss == "all":
                return []
            if ss in out:
                continue
            out.append(ss)
        return out

    @staticmethod
    def _sources_to_site_filters(sources: List[str]) -> List[str]:
        # Empty => "All" (no site restriction)
        mapping = {
            "youtube": "site:youtube.com",
            "reddit": "site:reddit.com",
            "news": "(site:news.google.com OR site:reuters.com OR site:bloomberg.com OR site:bbc.com)",
            "twitter": "(site:twitter.com OR site:x.com)",
            "facebook": "site:facebook.com",
            "instagram": "site:instagram.com",
            "tiktok": "site:tiktok.com",
            "app_reviews": "(site:play.google.com OR site:apps.apple.com)",
            "web": "",  # same as no restriction
        }
        out: List[str] = []
        for s in sources:
            sf = mapping.get(s, "")
            if not sf:
                continue
            out.append(sf)
        return out[:2]

    @staticmethod
    def _dedupe(items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in items:
            k = x.strip()
            if not k:
                continue
            lk = k.lower()
            if lk in seen:
                continue
            seen.add(lk)
            out.append(k)
        return out

    @staticmethod
    def _source_meta(url: str) -> Dict[str, str]:
        parsed = urlparse(url or "")
        domain = (parsed.netloc or "").lower().replace("www.", "")
        source_type = "web"
        site_name = "Web"
        if "youtube.com" in domain or "youtu.be" in domain:
            source_type = "youtube"
            site_name = "YouTube"
        elif "reddit.com" in domain:
            source_type = "reddit"
            site_name = "Reddit"
        elif "twitter.com" in domain or "x.com" in domain:
            source_type = "twitter"
            site_name = "X / Twitter"
        elif "facebook.com" in domain:
            source_type = "facebook"
            site_name = "Facebook"
        elif "instagram.com" in domain:
            source_type = "instagram"
            site_name = "Instagram"
        elif "tiktok.com" in domain:
            source_type = "tiktok"
            site_name = "TikTok"
        elif "play.google.com" in domain or "apps.apple.com" in domain:
            source_type = "app_reviews"
            site_name = "App Reviews"
        elif any(review_domain in domain for review_domain in ["trustpilot.com", "g2.com", "capterra.com", "sitejabber.com"]):
            source_type = "reviews"
            site_name = "Reviews"
        elif "complaintsboard.com" in domain:
            source_type = "complaints"
            site_name = "ComplaintsBoard"
        elif any(news_domain in domain for news_domain in ["news.google.com", "reuters.com", "bloomberg.com", "bbc.com"]):
            source_type = "news"
            site_name = "News"
        if not domain:
            site_name = "Manual"
        return {"domain": domain or "manual", "source_type": source_type, "site_name": site_name}

    @staticmethod
    def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            url = str(item.get("url") or "").strip()
            if not text and not url:
                continue
            key = (text.lower(), url.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    @staticmethod
    def _is_live_source_item(item: Dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        url = str(item.get("url") or "").strip()
        domain = str(item.get("domain") or "").strip().lower()
        provider = str(item.get("provider") or "").strip().lower()
        site_name = str(item.get("site_name") or item.get("source") or "").strip().lower()
        if provider == "warning":
            return False
        if url:
            return True
        if domain and domain not in {"manual", "system"}:
            return True
        if site_name and site_name not in {"manual", "website", "web"}:
            return True
        return False


