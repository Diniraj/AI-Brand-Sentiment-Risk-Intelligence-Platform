def build_explanation(negative_ratio, trend_increase, dominant_theme, keywords):
    return {
        "negative_sentiment": f"{round(negative_ratio, 1)}%",
        "trend_growth": f"+{trend_increase}%",
        "dominant_theme": dominant_theme,
        "keywords": keywords,
    }

