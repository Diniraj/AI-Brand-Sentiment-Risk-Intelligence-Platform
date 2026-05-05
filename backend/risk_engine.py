def calculate_risk(sentiments, complaint_freq=0, trend_increase=0):
    """
    Risk Score = 
    (negative_sentiment_ratio * 0.6) +
    (complaint_frequency * 0.3) +
    (trend_velocity * 0.1)
    
    classification:
    0-30   Low Risk
    31-60  Medium Risk
    61-100 High Risk
    """
    total = len(sentiments)
    if total == 0:
        return 0.0, "Low Risk", 0.0
        
    negatives = sum(1 for s in sentiments if s.get("label") == "NEGATIVE")
    negative_ratio = (negatives / total) * 100
    
    # Simple bounds 0-100
    complaint_freq = min(complaint_freq, 100)
    trend_increase_bound = min(trend_increase, 100)
    
    risk_score = (negative_ratio * 0.6) + (complaint_freq * 0.3) + (trend_increase_bound * 0.1)
    risk_score = min(max(round(risk_score, 1), 0.0), 100.0)
    
    # Classification
    if risk_score <= 30:
        level = "Low Risk"
    elif risk_score <= 60:
        level = "Medium Risk"
    else:
        level = "High Risk"
        
    return risk_score, level, negative_ratio

