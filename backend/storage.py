import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "sentiment.db")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            posts TEXT,
            overall_sentiment TEXT,
            themes TEXT,
            risk_score REAL,
            risk_level TEXT,
            provider_used TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            explanation TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_analysis(data: dict) -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    posts = data.get("posts", [])
    themes = data.get("themes", [])
    explanation = data.get("explanation", {})

    cursor.execute(
        """
        INSERT INTO analysis_results (
            brand, posts, overall_sentiment, themes,
            risk_score, risk_level, provider_used, explanation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("brand", "Unknown"),
            json.dumps(posts),
            data.get("overall_sentiment", "Neutral"),
            json.dumps(themes),
            data.get("risk_score", 0),
            data.get("risk_level", "Low Risk"),
            data.get("provider_used", "Unknown"),
            json.dumps(explanation),
        ),
    )
    conn.commit()
    conn.close()


def get_history(brand: str | None = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if brand:
        cursor.execute(
            "SELECT * FROM analysis_results WHERE brand = ? ORDER BY timestamp DESC",
            (brand,),
        )
    else:
        cursor.execute("SELECT * FROM analysis_results ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    results: list[dict] = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "brand": row["brand"],
                "posts": json.loads(row["posts"]) if row["posts"] else [],
                "overall_sentiment": row["overall_sentiment"],
                "themes": json.loads(row["themes"]) if row["themes"] else [],
                "risk_score": row["risk_score"],
                "risk_level": row["risk_level"],
                "provider_used": row["provider_used"],
                "timestamp": row["timestamp"],
                "explanation": json.loads(row["explanation"])
                if row["explanation"]
                else {},
            }
        )
    return results

