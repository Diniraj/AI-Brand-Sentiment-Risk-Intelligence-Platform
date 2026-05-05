import os
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import urlparse

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from utils.preprocess import preprocess_posts
from services.sentiment_service import SentimentAnalyzer
from services.embedding_service import EmbeddingService
from services.vector_service import VectorService
from services.clustering_service import ClusteringService
from services.insight_service import InsightService
from services.ingestion_service import IngestionService
import risk_engine
import explanation_engine
import storage


# Ensure we load the .env that sits in the backend folder,
# regardless of where the app is started from.
BACKEND_DIR = Path(__file__).resolve().parent
env_path = BACKEND_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    # Fallback to default search if someone puts .env at project root
    load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    # Initialize SQLite storage
    storage.init_db()

    sentiment_analyzer = SentimentAnalyzer()
    embedding_service = EmbeddingService()
    vector_service = VectorService(index_path="vector_index.faiss")
    clustering_service = ClusteringService()
    insight_service = InsightService()
    ingestion_service = IngestionService()

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"status": "ok"})

    @app.post("/api/analyze")
    def analyze() -> Any:
        data = request.get_json(force=True) or {}
        brand = data.get("brand", "").strip()
        posts: List[str] = data.get("posts", [])
        sources_in = data.get("sources", [])
        sources: List[str]
        if isinstance(sources_in, str):
            sources = [s.strip() for s in sources_in.split(",") if s.strip()]
        elif isinstance(sources_in, list):
            sources = [str(s).strip() for s in sources_in if str(s).strip()]
        else:
            sources = []
        keywords_in = data.get("keywords", [])
        keywords: List[str]
        if isinstance(keywords_in, str):
            keywords = [k.strip() for k in keywords_in.split(",") if k.strip()]
        elif isinstance(keywords_in, list):
            keywords = [str(k).strip() for k in keywords_in if str(k).strip()]
        else:
            keywords = []

        ingestion_meta: Dict[str, Any] = {}
        raw_post_items: List[Dict[str, Any]] = []

        # If posts are not provided, ingest them using brand + keywords.
        if not posts:
            if not brand:
                return jsonify({"error": "brand is required when posts are not provided"}), 400
            if not keywords:
                return jsonify({"error": "keywords are required when posts are not provided"}), 400
            try:
                ingestion_meta = ingestion_service.ingest_posts(
                    brand=brand,
                    keywords=keywords,
                    sources=sources,
                    prefer_apify=False,
                )
                posts = ingestion_meta.get("posts", []) or []
                raw_post_items = ingestion_meta.get("items", []) or []
                if not raw_post_items:
                    return jsonify(
                        {
                            "error": "No live source posts were found. Try different keywords or sources."
                        }
                    ), 404
            except Exception as e:
                return jsonify({"error": f"ingestion failed: {e}"}), 502

        if not posts or not isinstance(posts, list):
            return jsonify({"error": "posts must be a non-empty list of strings"}), 400

        is_manual_input = bool(posts) and not ingestion_meta

        if not raw_post_items:
            raw_post_items = [
                {
                    "text": p,
                    "url": "",
                    "title": "",
                    "source": "Manual",
                    "snippet": "",
                    "site_name": "Manual",
                    "domain": "manual",
                    "source_type": "manual",
                    "provider": "manual",
                    "query": "",
                    "matched_on": "manual",
                }
                for p in posts
            ]

        cleaned_posts, post_items = _prepare_post_items(raw_post_items)
        if not is_manual_input:
            post_items = [item for item in post_items if _has_live_source(item)]
            cleaned_posts = [item.get("cleaned_text", "") for item in post_items if item.get("cleaned_text")]
            if not post_items:
                return jsonify(
                    {
                        "error": "No live source posts with website URLs were found. Try different keywords or sources."
                    }
                ), 404

        sentiments = sentiment_analyzer.analyze(cleaned_posts)
        embeddings = embedding_service.encode(cleaned_posts)

        # Retrieve similar past posts BEFORE adding the current batch,
        # so we don't just retrieve the same posts we are analyzing.
        retrieved_similar_posts: List[Dict[str, Any]] = []
        try:
            negative_posts = [
                p for p, s in zip(cleaned_posts, sentiments) if s.get("label") == "NEGATIVE"
            ][:3]
            query_posts = negative_posts if negative_posts else cleaned_posts[:1]
            seen = set()
            for qp in query_posts:
                q_emb = embedding_service.encode([qp])
                hits = vector_service.search(q_emb[0], top_k=5)
                for dist, meta in hits:
                    key = f"{meta.get('brand','')}|{meta.get('post','')}"
                    if key in seen:
                        continue
                    seen.add(key)
                    retrieved_similar_posts.append(
                        {
                            "distance": dist,
                            "brand": meta.get("brand", ""),
                            "post": meta.get("post", ""),
                        }
                    )
        except Exception:
            # Retrieval is best-effort; analysis still works without it.
            retrieved_similar_posts = []

        metadata = [
            {
                "brand": brand,
                "post": p,
                "url": item.get("url", ""),
                "source": item.get("source", item.get("site_name", "")),
                "site_name": item.get("site_name", ""),
                "domain": item.get("domain", ""),
                "source_type": item.get("source_type", ""),
                "provider": item.get("provider", ""),
            }
            for p, item in zip(cleaned_posts, post_items)
        ]
        vector_service.add_embeddings(embeddings, metadata)

        clusters = clustering_service.cluster(embeddings)

        # Simple sentiment summary
        summary_counts: Dict[str, int] = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
        display_counts: Dict[str, int] = {"positive": 0, "negative": 0, "mixed": 0}
        for post_text, s in zip(cleaned_posts, sentiments):
            label = s.get("label", "NEUTRAL")
            if label not in summary_counts:
                summary_counts["NEUTRAL"] += 1
            else:
                summary_counts[label] += 1
            display_counts[_display_sentiment_label(post_text, label)] += 1

        insight_payload = {
            "brand": brand or "Unknown Brand",
            "sentiment_summary": summary_counts,
            "clusters": clusters,
            "sample_negative_posts": [
                p
                for p, s in zip(cleaned_posts, sentiments)
                if s.get("label") == "NEGATIVE"
            ][:5],
            "retrieved_similar_posts": retrieved_similar_posts,
        }

        insights = insight_service.generate_insights(
            {
                **insight_payload,
                "posts": cleaned_posts,
            }
        )

        # Derive themes and keywords from insights
        themes = insights.get("key_themes") or insights.get("themes") or []
        risks = insights.get("risks") or []
        dominant_theme = themes[0] if themes else "None detected"
        keywords = risks[:5] if isinstance(risks, list) else []

        # Simple heuristic for complaint frequency & trend velocity
        complaint_freq = sum(
            1
            for t in themes
            if isinstance(t, str)
            and ("complaint" in t.lower() or "issue" in t.lower() or "support" in t.lower())
        ) * 20
        trend_increase = 30  # could be learned from history later

        risk_score, risk_level, negative_ratio = risk_engine.calculate_risk(
            sentiments,
            complaint_freq=complaint_freq,
            trend_increase=trend_increase,
        )

        # Human-readable overall sentiment from negative ratio
        if negative_ratio > 50:
            overall = "Negative"
        elif negative_ratio < 20:
            overall = "Positive"
        else:
            overall = "Mixed"

        explanation = explanation_engine.build_explanation(
            negative_ratio,
            trend_increase=trend_increase,
            dominant_theme=dominant_theme,
            keywords=keywords,
        )

        provider_used = insights.get("provider_used", "Unknown")

        # Sentiment breakdown (for dashboard)
        positive_posts = summary_counts.get("POSITIVE", 0)
        negative_posts = summary_counts.get("NEGATIVE", 0)
        neutral_posts = summary_counts.get("NEUTRAL", 0)

        # Architecture-friendly aliases
        model_used = provider_used  # alias for UI badge
        reputation_risks = risks if isinstance(risks, list) else []
        pr_strategy = (
            [insights.get("suggested_response")]
            if isinstance(insights.get("suggested_response"), str) and insights.get("suggested_response")
            else []
        )

        analyzed_post_items: List[Dict[str, Any]] = []
        for item, sentiment in zip(post_items, sentiments):
            base_label = (sentiment.get("label") or "NEUTRAL").upper()
            display_label = _display_sentiment_label(item.get("cleaned_text", ""), base_label)
            analyzed_post_items.append(
                {
                    **item,
                    "sentiment": base_label,
                    "display_sentiment": display_label.upper(),
                    "score": float(sentiment.get("score", 0.0)),
                }
            )

        response: Dict[str, Any] = {
            "brand": brand,
            "posts": cleaned_posts,
            "post_items": analyzed_post_items,
            "keywords": keywords,
            "sources": sources,
            "ingestion": ingestion_meta,
            "sentiments": sentiments,
            "clusters": clusters,
            "insights": insights,
            "themes": themes,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "overall_sentiment": overall,
            "provider_used": provider_used,
            "model_used": model_used,
            "positive_posts": positive_posts,
            "negative_posts": negative_posts,
            "neutral_posts": neutral_posts,
            "sentiment_distribution": display_counts,
            "reputation_risks": reputation_risks,
            "pr_strategy": pr_strategy,
            "explanation": explanation,
            "retrieved_similar_posts": retrieved_similar_posts,
        }

        # Persist for history view
        storage.save_analysis(response)

        return jsonify(response)

    @app.post("/api/search")
    def search() -> Any:
        """
        Semantic search over previously indexed posts (FAISS).
        Body: { "query": "text", "top_k": 5 }
        """
        data = request.get_json(force=True) or {}
        query = str(data.get("query", "")).strip()
        top_k = int(data.get("top_k", 5) or 5)
        if not query:
            return jsonify({"error": "query is required"}), 400
        top_k = max(1, min(top_k, 20))

        q_emb = embedding_service.encode([query])
        hits = vector_service.search(q_emb[0], top_k=top_k)
        results = [
            {
                "distance": dist,
                "brand": meta.get("brand", ""),
                "post": meta.get("post", ""),
                "url": meta.get("url", ""),
                "domain": meta.get("domain", ""),
                "source_type": meta.get("source_type", ""),
                "provider": meta.get("provider", ""),
            }
            for dist, meta in hits
        ]
        return jsonify({"query": query, "top_k": top_k, "results": results})

    @app.get("/api/history")
    def history() -> Any:
        brand = request.args.get("brand")
        records = storage.get_history(brand)
        return jsonify(records)

    return app

def _prepare_post_items(raw_items: List[Dict[str, Any]]) -> tuple[List[str], List[Dict[str, Any]]]:
    prepared_posts: List[str] = []
    prepared_items: List[Dict[str, Any]] = []
    seen = set()

    for item in raw_items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cleaned_list = preprocess_posts([text])
        if not cleaned_list:
            continue
        cleaned_text = cleaned_list[0]
        if cleaned_text in seen:
            continue
        seen.add(cleaned_text)

        url = _normalize_url(str(item.get("url") or "").strip())
        domain = str(item.get("domain") or "").strip()
        source_type = str(item.get("source_type") or "").strip()
        site_name = str(item.get("site_name") or item.get("source") or "").strip()
        inferred = _infer_source_meta(url)
        if not domain or not source_type:
            domain = domain or inferred["domain"]
            source_type = source_type or inferred["source_type"]
        if not site_name or site_name.lower() == "manual":
            site_name = inferred["site_name"]
        source_label = str(item.get("source") or "").strip()
        if not source_label or source_label.lower() == "manual":
            source_label = site_name or inferred["site_name"]

        prepared_posts.append(cleaned_text)
        prepared_items.append(
            {
                "text": text,
                "cleaned_text": cleaned_text,
                "url": url,
                "title": str(item.get("title") or "").strip(),
                "source": source_label,
                "snippet": str(item.get("snippet") or "").strip(),
                "site_name": site_name or "Manual",
                "domain": domain or "manual",
                "source_type": source_type or "manual",
                "provider": str(item.get("provider") or "manual").strip() or "manual",
                "query": str(item.get("query") or "").strip(),
                "matched_on": str(item.get("matched_on") or item.get("query") or "").strip(),
            }
        )

    return prepared_posts, prepared_items


def _infer_source_meta(url: str) -> Dict[str, str]:
    domain = (urlparse(url or "").netloc or "").lower().replace("www.", "")
    source_type = "web"
    site_name = "Web"
    if not domain:
        return {"domain": "manual", "source_type": "manual", "site_name": "Manual"}
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
    return {"domain": domain, "source_type": source_type, "site_name": site_name}


def _normalize_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("//"):
        return f"https:{cleaned}"
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    if cleaned.startswith("/"):
        return ""
    if "." in cleaned and " " not in cleaned:
        return f"https://{cleaned}"
    return ""


def _display_sentiment_label(text: str, label: str) -> str:
    label_upper = (label or "NEUTRAL").upper()
    text_lower = (text or "").lower()
    positive_cues = ["good", "great", "love", "helpful", "improved", "best", "fast", "affordable"]
    negative_cues = ["bad", "poor", "slow", "issue", "problem", "complaint", "scam", "low", "worst", "delay"]
    has_positive = any(word in text_lower for word in positive_cues)
    has_negative = any(word in text_lower for word in negative_cues)
    has_contrast = any(term in text_lower for term in [" but ", " however ", " although ", " though ", " while "])

    if label_upper == "NEUTRAL":
        return "mixed"
    if has_contrast and has_positive and has_negative:
        return "mixed"
    if label_upper == "POSITIVE":
        return "positive"
    if label_upper == "NEGATIVE":
        return "negative"
    return "mixed"


def _has_live_source(item: Dict[str, Any]) -> bool:
    url = str(item.get("url") or "").strip()
    domain = str(item.get("domain") or "").strip().lower()
    site_name = str(item.get("site_name") or item.get("source") or "").strip().lower()
    if url:
        return True
    if domain and domain != "manual":
        return True
    if site_name and site_name not in {"manual", "website", "web"}:
        return True
    return False


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app = create_app()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    # The Windows reloader can interrupt long model/HTTP calls during dev.
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)

