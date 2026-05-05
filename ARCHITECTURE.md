# AI Brand Sentiment & Risk Insight Tool — System Architecture

## 1. High-Level Architecture

```
┌─────────────────────────────┐
│        React Frontend       │
│                             │
│ • Brand Input Form          │
│ • Social Post Input         │
│ • Sentiment Visualization   │
│ • Provider Status Panel     │
│ • Risk Dashboard            │
│ • History / Saved Results   │
└───────────────┬─────────────┘
                │ REST API
                ▼
┌─────────────────────────────┐
│        Flask Backend        │
│        API Gateway          │
└───────────────┬─────────────┘
                │
                ▼
      Input Processing Layer
      (clean & split posts)
                │
                ▼
        Sentiment Analysis
      (HF sentiment model)
                │
                ▼
        Embedding Generator
     (SentenceTransformers)
                │
                ▼
          Vector Database
              FAISS
                │
                ▼
        Theme Clustering
   (semantic grouping of posts)
                │
                ▼
         Risk Score Engine
  (sentiment + frequency + trend)
                │
                ▼
          LLM Orchestrator
                │
 ┌──────────────┼───────────────┬───────────────┐
 ▼              ▼               ▼               ▼
HuggingFace   Groq API        Gemini API     Local
LLM           (Llama-3)       (Backup)       Analyzer
Primary       Fallback        Backup         Final
                │
                ▼
       Insight Generation
 (themes, risks, PR strategy)
                │
                ▼
        Explainable AI Layer
 (why the system detected risk)
                │
                ▼
      Result Formatter (JSON)
                │
                ▼
       Data Storage (SQLite)
                │
                ▼
         Response to React UI
```

## 2. Backend Processing Pipeline

```
User submits brand + posts
        │
        ▼
Input Processor
(clean text & split posts)
        │
        ▼
Sentiment Analyzer
(label each post)
        │
        ▼
Embedding Generator
(posts → vectors)
        │
        ▼
FAISS Vector Database
(store embeddings)
        │
        ▼
Semantic Clustering
(group similar posts)
        │
        ▼
Risk Score Engine
(calculate brand risk)
        │
        ▼
LLM Orchestrator
(HF → Groq → Gemini → Local)
        │
        ▼
Generate Insights
(themes, risks, PR strategy)
        │
        ▼
Explainable AI Output
        │
        ▼
Save Analysis in Database
        │
        ▼
Return result to frontend
```

## 3. Multi-LLM Fallback Logic

```
1. Try HuggingFace LLM
2. If failed → use Groq (Llama-3)
3. If failed → use Gemini API
4. If failed → run Local Analyzer
```

Example response returned:

```
provider_used: Groq Llama-3
status: success
```

## 4. Sentiment Visualization Flow

```
Posts
  │
  ▼
Sentiment Analysis
  │
  ▼
Count Sentiment Types
  │
  ▼
Return Data to React
  │
  ▼
Pie Chart Visualization
```

Example chart data:

```
Positive: 4
Negative: 3
Neutral: 2
```

## 5. Risk Scoring Engine

Example formula:

```
Risk Score =
(negative_sentiment_ratio × 0.6)
+ (complaint_frequency × 0.3)
+ (trend_growth × 0.1)
```

Risk Levels:

```
0–30   Low
31–60  Medium
61–100 High
```

## 6. Explainable AI Layer

The system explains why risk was detected.

Example output:

```
Risk Explanation

• 65% posts negative
• dominant theme: customer service complaints
• trend increase: +210%
• keywords detected: terrible, slow support
```

## 7. Data Storage Layer

Database: **SQLite**

Table:

```
analysis_results

id
brand
posts
overall_sentiment
themes
risk_score
provider_used
timestamp
```

Purpose:

* save previous analyses
* show history in dashboard
* track trends

## 8. React Frontend Dashboard

Main UI components:

```
Brand Input Form
Social Posts Input
Analyze Button
```

Dashboard panels:

### Sentiment Visualization

```
Pie Chart

Positive
Negative
Neutral
```

### Risk Score Panel

```
Risk Score: 72
Risk Level: High
```

### Key Themes Panel

```
Customer service complaints
Software bugs
Battery performance praise
```

### AI Provider Status Panel

```
HuggingFace   ❌ Failed
Groq Llama-3  ✅ Active
Gemini        Standby
Local Engine  Ready
```

### Explainability Panel

```
Why risk detected

65% negative sentiment
service complaints increased by 210%
```

### Saved Results Page

```
Brand    Sentiment    Risk    Provider    Date
Tesla    Mixed        72      Groq        Mar 18
Nike     Positive     25      HF          Mar 17
```

## 9. Project Folder Structure

```
brand-sentiment-ai
│
├── backend
│   ├── app.py
│   ├── llm_router.py
│   ├── sentiment_engine.py
│   ├── embeddings.py
│   ├── vector_store.py
│   ├── clustering.py
│   ├── risk_engine.py
│   ├── explanation_engine.py
│   ├── local_analyzer.py
│   └── storage.py
│
├── frontend
│   └── react-app
│
└── requirements.txt
```

## 10. Example API Response

```
{
 "brand": "Tesla",
 "overall_sentiment": "Mixed",
 "themes": [
   "Customer service complaints",
   "Software bugs",
   "Battery performance praise"
 ],
 "risk_score": 72,
 "risk_level": "High",
 "provider_used": "Groq Llama-3",
 "explanation": {
   "negative_sentiment": "65%",
   "trend_growth": "+210%",
   "keywords": ["terrible", "slow service"]
 }
}
```

## 11. Key Strengths of This Architecture

This project demonstrates:

```
AI system design
vector search
LLM orchestration
fallback reliability
risk detection
explainable AI
data persistence
visual analytics
```

This level of architecture is **well above a normal technical assignment** and resembles a **real AI monitoring product**.

