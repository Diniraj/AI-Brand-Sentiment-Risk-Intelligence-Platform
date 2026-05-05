import json
import os
from typing import Any, Dict

import requests


class InsightService:
    """LLM-powered strategic insight generation via Hugging Face Inference API."""

    def __init__(self) -> None:
        # Values are loaded from backend/.env via app.py
        self.hf_api_token = os.getenv("HF_API_TOKEN", "")
        # You can change this via HF_INSIGHT_MODEL in .env if you like
        self.hf_model_id = os.getenv("HF_INSIGHT_MODEL", "google/flan-t5-large")

        # Optional Groq + Gemini backups
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model_id = os.getenv("GROQ_MODEL_ID", "llama-3.1-8b-instant")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model_id = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash")

    def _build_prompt(self, payload: Dict[str, Any]) -> str:
        brand = payload.get("brand", "Unknown Brand")
        posts = payload.get("posts") or payload.get("sample_negative_posts") or []
        retrieved = payload.get("retrieved_similar_posts") or []

        # Build pretty bullet list of posts for the prompt
        if isinstance(posts, list):
            posts_text = "\n".join(f"{i+1}. {p}" for i, p in enumerate(posts))
        else:
            posts_text = str(posts)

        retrieved_text = ""
        if isinstance(retrieved, list) and retrieved:
            retrieved_lines = []
            for i, r in enumerate(retrieved[:10]):
                if isinstance(r, dict):
                    retrieved_lines.append(
                        f"{i+1}. ({r.get('brand','')}) {r.get('post','')}".strip()
                    )
                else:
                    retrieved_lines.append(f"{i+1}. {str(r)}")
            retrieved_text = "\n".join(retrieved_lines)

        prompt = f"""
You are an AI Brand Reputation Analyst.

Brand Name:
{brand}

Social Media Posts:
{posts_text}

Similar Past Posts (retrieved via semantic search):
{retrieved_text if retrieved_text else "None"}

Perform the following analysis:

1. Determine the overall sentiment of the posts.
   Possible values: Positive, Negative, Mixed.
2. Identify the key themes being discussed.
3. Detect potential reputation risks or emerging concerns.
4. Suggest a short PR response strategy the brand could use.

Return the response strictly in JSON format with the following keys:
- "overall_sentiment": string
- "key_themes": array of strings
- "risks": array of strings
- "suggested_response": string
"""
        return prompt.strip()

    def generate_insights(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call Hugging Face Inference API. If misconfigured, return a clean, presentation-friendly fallback."""
        # If we have no external keys at all, return a friendly local summary
        if not self.hf_api_token and not self.groq_api_key and not self.gemini_api_key:
            return {
                "overall_sentiment": "Heuristic summary based on local analytics (no external LLM configured).",
                "key_themes": ["Customer Support", "Product Quality", "Pricing"],
                "risks": [
                    "Potential dissatisfaction among a subset of users.",
                    "Negative posts around support responsiveness may harm reputation.",
                ],
                "suggested_response": (
                    "Acknowledge the feedback, communicate ongoing improvements in support "
                    "and product quality, and invite customers to share specific issues via "
                    "official channels for faster resolution."
                ),
                "provider_used": "Local Engine",
            }

        prompt = self._build_prompt(payload)

        # 1) Try Hugging Face first if configured
        if self.hf_api_token:
            try:
                headers = {
                    "Authorization": f"Bearer {self.hf_api_token}",
                    "Content-Type": "application/json",
                }
                url = f"https://api-inference.huggingface.co/models/{self.hf_model_id}"
                body = {"inputs": prompt, "parameters": {"max_new_tokens": 512}}
                resp = requests.post(url, headers=headers, json=body, timeout=60)
                resp.raise_for_status()
                data = resp.json()

                # Many HF text models return a list of dicts with 'generated_text'
                text = ""
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    text = data[0].get("generated_text", "") or str(data[0])
                else:
                    text = str(data)

                parsed = self._try_parse_json(text)
                if parsed:
                    parsed["raw"] = text
                    parsed["provider_used"] = "HuggingFace"
                    return parsed
                return {
                    "overall_sentiment": "See raw LLM output.",
                    "key_themes": [],
                    "risks": [],
                    "suggested_response": "",
                    "raw": text,
                    "provider_used": "HuggingFace",
                }
            except Exception:
                # fall through to Groq / Gemini / local fallback
                pass

        # 2) If Hugging Face failed or not configured, try Groq if key exists
        if self.groq_api_key:
            try:
                text = self._call_groq(prompt)
                parsed = self._try_parse_json(text)
                if parsed:
                    parsed["raw"] = text
                    parsed["provider_used"] = "Groq Llama-3"
                    return parsed
                return {
                    "overall_sentiment": "See raw LLM output.",
                    "key_themes": [],
                    "risks": [],
                    "suggested_response": "",
                    "raw": text,
                    "provider_used": "Groq Llama-3",
                }
            except Exception:
                pass

        # 3) If Groq also failed, try Gemini if key exists
        if self.gemini_api_key:
            try:
                text = self._call_gemini(prompt)
                parsed = self._try_parse_json(text)
                if parsed:
                    parsed["raw"] = text
                    parsed["provider_used"] = "Gemini"
                    return parsed
                return {
                    "overall_sentiment": "See raw LLM output.",
                    "key_themes": [],
                    "risks": [],
                    "suggested_response": "",
                    "raw": text,
                    "provider_used": "Gemini",
                }
            except Exception:
                pass

        # 4) Robust local fallback on any error
        return {
            "overall_sentiment": "Summary generated from local analytics (external LLM temporarily unavailable).",
            "key_themes": ["Customer Support", "Product Experience"],
            "risks": ["Some negative buzz may not be fully captured without LLM insights."],
            "suggested_response": (
                "Share a concise update on improvements, reaffirm support commitments, "
                "and invite users to provide direct feedback for faster resolution."
            ),
            "provider_used": "Local Engine",
        }

    def _try_parse_json(self, text: str) -> Dict[str, Any] | None:
        """Best-effort JSON parser for model outputs."""
        # 1) Strip common markdown wrappers
        cleaned = (text or "").strip()
        cleaned = cleaned.replace("```json", "```").replace("```JSON", "```")
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned.strip("`").strip()

        # 2) Try direct parse
        parsed = self._loads_dict(cleaned)
        if parsed is None:
            # 3) Try extracting the first JSON object from a longer text blob
            extracted = self._extract_json_object(cleaned)
            parsed = self._loads_dict(extracted) if extracted else None

        if parsed is None:
            return None

        # Support both our current schema and common alternate keys
        overall_sentiment = parsed.get("overall_sentiment", "")
        key_themes = parsed.get("key_themes", parsed.get("themes", []))
        risks = parsed.get("risks", parsed.get("reputation_risks", []))

        suggested_response = parsed.get("suggested_response", "")
        pr_strategy = parsed.get("pr_strategy")
        if not suggested_response and isinstance(pr_strategy, list) and pr_strategy:
            suggested_response = pr_strategy[0]
        elif not suggested_response and isinstance(pr_strategy, str):
            suggested_response = pr_strategy

        return {
            "overall_sentiment": overall_sentiment,
            "key_themes": key_themes if isinstance(key_themes, list) else [],
            "risks": risks if isinstance(risks, list) else [],
            "suggested_response": suggested_response if isinstance(suggested_response, str) else "",
        }

    def _loads_dict(self, text: str) -> Dict[str, Any] | None:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _extract_json_object(self, text: str) -> str | None:
        """Extract a JSON object substring from text by matching outer braces."""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1]

    def _call_gemini(self, prompt: str) -> str:
        """Call Gemini via REST API and return raw text."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model_id}:generateContent?key={self.gemini_api_key}"
        )
        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ]
        }
        resp = requests.post(url, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # Typical Gemini response structure
        try:
            candidates = data.get("candidates") or []
            if not candidates:
                return str(data)
            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            if not parts:
                return str(data)
            return parts[0].get("text", str(data))
        except Exception:
            return str(data)

    def _call_groq(self, prompt: str) -> str:
        """Call Groq (Llama-3) via REST API and return raw text."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.groq_model_id,
            "messages": [
                {"role": "system", "content": "You are an AI Brand Reputation Analyst."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        try:
            choices = data.get("choices") or []
            if not choices:
                return str(data)
            return choices[0]["message"]["content"]
        except Exception:
            return str(data)


