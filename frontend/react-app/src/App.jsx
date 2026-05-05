import React, { useState } from "react";
import axios from "axios";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const EXAMPLE_POSTS = `zudio clothes are affordable but quality is low
battery performance improved
trial room queue always long
staff was helpful but billing line took forever`;

function App() {
  const [brand, setBrand] = useState("");
  const [rawKeywords, setRawKeywords] = useState("");
  const [autoIngest, setAutoIngest] = useState(true);
  const [sources, setSources] = useState([]);
  const [rawPosts, setRawPosts] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const SOURCE_OPTIONS = [
    { id: "youtube", label: "YouTube", hint: "Videos and comments (via search)" },
    { id: "reddit", label: "Reddit", hint: "Threads and posts" },
    { id: "twitter", label: "X/Twitter", hint: "Mentions (via search)" },
    { id: "reviews", label: "Reviews", hint: "Trustpilot, G2, Capterra, Sitejabber" },
    { id: "complaints", label: "Complaints", hint: "ComplaintsBoard complaint pages" },
    { id: "news", label: "News", hint: "News sites" },
    { id: "app_reviews", label: "App Reviews", hint: "Play Store / App Store" },
    { id: "web", label: "Web", hint: "General web" },
  ];

  const toggleSource = (id) => {
    setSources((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleAnalyze = async (e) => {
    e.preventDefault();
    setError("");
    setResult(null);

    const keywords = rawKeywords
      .split(/[,\n]/g)
      .map((k) => k.trim())
      .filter((k) => k.length > 0);

    if (!brand.trim()) {
      setError("Brand is required.");
      return;
    }

    let posts = [];
    if (!autoIngest) {
      posts = rawPosts
        .split("\n")
        .map((p) => p.trim())
        .filter((p) => p.length > 0);
      if (!posts.length) {
        setError("Please enter at least one post, or enable Auto-ingest.");
        return;
      }
    } else if (!keywords.length) {
      setError("Keywords are required for Auto-ingest.");
      return;
    }

    setLoading(true);
    try {
      const payload = autoIngest
        ? { brand, keywords, sources }
        : { brand, keywords, sources, posts };
      const resp = await axios.post("/api/analyze", payload);
      setResult(resp.data);
    } catch (err) {
      setError(err?.response?.data?.error || "Failed to analyze posts.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddExamplePosts = () => {
    if (!brand) setBrand("Zudio");
    if (!rawKeywords) setRawKeywords("delivery, customer service, pricing, quality");
    if (!sources.length) setSources(["web"]);
    setRawPosts(EXAMPLE_POSTS);
    setAutoIngest(false);
  };

  const handleClearResults = () => {
    setError("");
    setResult(null);
  };

  const handleLoadHistory = async () => {
    setHistoryLoading(true);
    try {
      const resp = await axios.get("/api/history", {
        params: brand ? { brand } : {},
      });
      setHistory(resp.data || []);
    } catch (err) {
      console.error("Failed to load history", err);
    } finally {
      setHistoryLoading(false);
    }
  };

  const safeSentiments = Array.isArray(result?.sentiments) ? result.sentiments : [];
  const postItems = Array.isArray(result?.post_items) ? result.post_items : [];

  const sentimentCounts =
    safeSentiments.reduce(
      (acc, s) => {
        const label = s?.label || "NEUTRAL";
        acc[label] = (acc[label] || 0) + 1;
        return acc;
      },
      { POSITIVE: 0, NEGATIVE: 0, NEUTRAL: 0 }
    ) || {};

  const themes = Array.isArray(result?.themes) ? result.themes : [];
  const risks = Array.isArray(result?.reputation_risks)
    ? result.reputation_risks
    : Array.isArray(result?.insights?.risks)
    ? result.insights.risks
    : [];
  const prStrategy = Array.isArray(result?.pr_strategy)
    ? result.pr_strategy
    : result?.insights?.suggested_response
    ? [result.insights.suggested_response]
    : [];

  const sentimentDistribution = result?.sentiment_distribution || {};
  const chartData = [
    {
      label: "Positive",
      value:
        typeof sentimentDistribution.positive === "number"
          ? sentimentDistribution.positive
          : sentimentCounts.POSITIVE,
      color: "#34d399",
    },
    {
      label: "Negative",
      value:
        typeof sentimentDistribution.negative === "number"
          ? sentimentDistribution.negative
          : sentimentCounts.NEGATIVE,
      color: "#fb7185",
    },
    {
      label: "Mixed",
      value:
        typeof sentimentDistribution.mixed === "number"
          ? sentimentDistribution.mixed
          : sentimentCounts.NEUTRAL,
      color: "#fbbf24",
    },
  ];

  const modelName = result?.model_used || result?.provider_used || "Groq Llama-3";
  const ingestion = result?.ingestion || {};
  const explanation = result?.explanation || {};
  const selectedSources =
    Array.isArray(result?.sources) && result.sources.length > 0
      ? result.sources
      : sources;
  const sourcePriority = new Map(
    (selectedSources || []).map((source, index) => [String(source).toLowerCase(), index])
  );
  const ingestionItems = Array.isArray(result?.ingestion?.items) ? result.ingestion.items : [];
  const postItemsHaveRealSources = postItems.some(
    (item) => item?.url || (item?.site_name && item.site_name !== "Manual") || (item?.domain && item.domain !== "manual")
  );
  const feedSourceItems = postItemsHaveRealSources
    ? postItems
    : ingestionItems.length > 0
    ? ingestionItems
    : postItems;
  const feedItems =
    feedSourceItems.length > 0
      ? feedSourceItems
          .map((item, idx) => ({
          ...item,
          url: normalizeUrl(item?.url || ""),
          domain: resolveDomain(item),
          site_name: resolveSiteName(item),
          title: item?.title || "",
          source: resolveSiteName(item),
          matched_on: item?.matched_on || item?.query || "brand",
          display_sentiment:
            item?.display_sentiment ||
            item?.sentiment ||
            safeSentiments[idx]?.label ||
            "NEUTRAL",
          source_type: resolveSourceType(item),
          provider: item?.provider || "manual",
          text: item?.text || "",
        }))
          .sort((a, b) => compareBySourcePriority(a, b, sourcePriority))
      : [];
  const feedHeaderSource =
    feedItems.find((item) => item?.url && (item?.site_name || (item?.domain && item.domain !== "manual"))) ||
    feedItems.find((item) => item?.url) ||
    null;
  const missingSourceMetadata = feedItems.length === 0 && safeSentiments.length > 0;
  const loadingMessage = autoIngest
    ? `Scraping from ${formatLoadingSources(sources)}`
    : "Analyzing pasted posts";
  const scrapingModelName = "Serper, Apify";
  const totalDisplaySentiments = chartData.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const netScore =
    totalDisplaySentiments > 0
      ? (
          (Number(chartData[0].value || 0) - Number(chartData[1].value || 0)) /
          totalDisplaySentiments
        ).toFixed(2)
      : "0.00";

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#020617] text-slate-100">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 -left-40 h-96 w-96 rounded-full bg-sky-500/20 blur-3xl" />
        <div className="absolute bottom-[-10rem] right-[-6rem] h-[26rem] w-[26rem] rounded-full bg-fuchsia-500/25 blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(148,163,184,0.12),_transparent_55%)]" />
      </div>

      <div className="relative z-10 mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-500/30 bg-sky-500/5 px-3 py-1 text-xs font-medium text-sky-200/90 backdrop-blur">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(34,197,94,0.35)]" />
              Real-time Brand Intelligence
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-slate-50 sm:text-3xl lg:text-4xl">
              AI Brand Intelligence Dashboard
            </h1>
            <p className="mt-1 text-sm text-slate-400 sm:text-base">
              Sentiment | Themes | Risk Detection
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-3 rounded-2xl border border-slate-700/70 bg-slate-900/70 px-4 py-3 shadow-[0_18px_45px_rgba(0,0,0,0.7)] backdrop-blur-2xl">
              <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-sky-500/15 ring-1 ring-sky-500/50">
                <span className="text-sm font-semibold text-sky-200">AI</span>
              </div>
              <div className="mr-1">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                  AI MODEL
                </p>
                <p className="text-sm font-medium text-slate-50">{modelName}</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-2xl border border-slate-700/70 bg-slate-900/70 px-4 py-3 shadow-[0_18px_45px_rgba(0,0,0,0.7)] backdrop-blur-2xl">
              <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-fuchsia-500/15 ring-1 ring-fuchsia-500/50">
                <span className="text-sm font-semibold text-fuchsia-200">SC</span>
              </div>
              <div className="mr-1">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                  SCRAPPING MODEL
                </p>
                <p className="text-sm font-medium text-slate-50">{scrapingModelName}</p>
              </div>
            </div>
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-3">
            <Card>
              <CardHeader title="Brand + Context" subtitle="Keyword-driven ingestion + analysis" />
              <form onSubmit={handleAnalyze} className="space-y-3">
                <div className="space-y-1.5 text-xs">
                  <label className="block text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
                    Brand / Company
                  </label>
                  <input
                    type="text"
                    value={brand}
                    onChange={(e) => setBrand(e.target.value)}
                    placeholder="e.g. Zudio - winter collection"
                    className="w-full rounded-xl border border-slate-700/70 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none ring-0 transition focus:border-sky-500/70 focus:ring-2 focus:ring-sky-500/40"
                  />
                </div>

                <div className="space-y-1.5 text-xs">
                  <label className="block text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
                    Keywords (comma / new line separated)
                  </label>
                  <textarea
                    rows={3}
                    value={rawKeywords}
                    onChange={(e) => setRawKeywords(e.target.value)}
                    placeholder="delivery, customer service, pricing, quality"
                    className="w-full rounded-xl border border-slate-700/70 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none ring-0 transition focus:border-sky-500/70 focus:ring-2 focus:ring-sky-500/40"
                  />
                </div>

                <div className="flex items-center justify-between gap-3 rounded-2xl border border-slate-700/70 bg-slate-900/50 px-3 py-2">
                  <div>
                    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
                      Data ingestion
                    </p>
                    <p className="text-xs text-slate-200">
                      {autoIngest ? "Auto (Serper + Web)" : "Manual posts"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAutoIngest((v) => !v)}
                    className={`relative inline-flex h-7 w-12 items-center rounded-full ring-1 transition ${
                      autoIngest
                        ? "bg-emerald-500/20 ring-emerald-400/50"
                        : "bg-slate-700/40 ring-slate-600/60"
                    }`}
                    aria-pressed={autoIngest}
                    aria-label="Toggle auto ingestion"
                  >
                    <span
                      className={`inline-block h-5 w-5 transform rounded-full bg-slate-100 shadow transition ${
                        autoIngest ? "translate-x-6" : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>

                {autoIngest && (
                  <div className="space-y-2">
                    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
                      Sources (optional)
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {SOURCE_OPTIONS.map((opt) => {
                        const active = sources.includes(opt.id);
                        return (
                          <button
                            key={opt.id}
                            type="button"
                            onClick={() => toggleSource(opt.id)}
                            className={`rounded-full px-3 py-1 text-[11px] font-medium ring-1 transition ${
                              active
                                ? "bg-sky-500/15 text-sky-100 ring-sky-400/50"
                                : "bg-slate-900/60 text-slate-300 ring-slate-700/70 hover:ring-slate-500/70"
                            }`}
                            title={opt.hint}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {!autoIngest && (
                  <div className="space-y-1.5 text-xs">
                    <label className="block text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
                      Posts (one per line)
                    </label>
                    <textarea
                      rows={6}
                      value={rawPosts}
                      onChange={(e) => setRawPosts(e.target.value)}
                      placeholder="Paste tweets, reviews, or feedback here..."
                      className="w-full rounded-xl border border-slate-700/70 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none ring-0 transition focus:border-sky-500/70 focus:ring-2 focus:ring-sky-500/40"
                    />
                  </div>
                )}

                <div className="flex flex-col gap-3 pt-1">
                  <button
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-sky-400 via-sky-500 to-indigo-500 px-4 py-2.5 text-sm font-medium text-slate-950 shadow-[0_0_40px_rgba(56,189,248,0.6)] transition hover:shadow-[0_0_55px_rgba(56,189,248,0.9)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
                    type="submit"
                    disabled={loading}
                  >
                    <span>{loading ? `${loadingMessage}...` : "Run Keyword-Driven Analysis"}</span>
                  </button>
                  <div className="flex gap-2">
                    <button
                      className="flex-1 rounded-xl border border-slate-700/70 bg-slate-900/80 px-3 py-2 text-xs font-medium text-slate-200 transition hover:border-slate-500/70 hover:bg-slate-900 disabled:opacity-60"
                      type="button"
                      onClick={handleAddExamplePosts}
                      disabled={loading}
                    >
                      Add Example (Manual)
                    </button>
                    <button
                      className="flex-1 rounded-xl border border-red-500/35 bg-red-500/10 px-3 py-2 text-xs font-medium text-red-200 transition hover:border-red-400/70 hover:bg-red-500/15 disabled:opacity-60"
                      type="button"
                      onClick={handleClearResults}
                      disabled={loading}
                    >
                      Clear Results
                    </button>
                  </div>
                  {error && <p className="text-[11px] text-amber-300/90">{error}</p>}
                </div>
              </form>
            </Card>
          </div>

          <div className="space-y-4 lg:col-span-4">
            <Card>
              <CardHeader title="Overall Sentiment" subtitle="How people feel right now" />
              <div className="mt-4 flex flex-col gap-5">
                <div className="flex flex-col items-center justify-center gap-4">
                  <div className="relative flex items-center justify-center">
                    <div className="h-32 w-32 rounded-full bg-slate-900/80 shadow-[0_20px_45px_rgba(15,23,42,0.9)] ring-1 ring-slate-700/70">
                      <div className="absolute inset-2 rotate-[24deg] rounded-full border-2 border-emerald-400/80 border-r-transparent border-b-transparent" />
                      <div className="absolute inset-5 -rotate-[30deg] rounded-full border-2 border-amber-300/75 border-l-transparent border-b-transparent" />
                      <div className="absolute inset-8 rotate-[58deg] rounded-full border-2 border-rose-400/80 border-l-transparent border-t-transparent" />
                    </div>
                    <div className="absolute flex flex-col items-center">
                      <span className="text-[10px] uppercase tracking-[0.22em] text-slate-400">NET</span>
                      <span className="text-2xl font-semibold text-slate-50">{netScore}</span>
                    </div>
                  </div>
                  <div className="grid w-full grid-cols-3 gap-2 text-[11px] text-slate-400">
                    <LegendDot color="bg-emerald-400" label={`Positive ${chartData[0].value}`} />
                    <LegendDot color="bg-amber-300" label={`Mixed ${chartData[2].value}`} />
                    <LegendDot color="bg-rose-400" label={`Negative ${chartData[1].value}`} />
                  </div>
                </div>

                <div className="rounded-3xl border border-slate-800/80 bg-slate-950/45 p-3">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">Sentiment Count</p>
                    <p className="text-[11px] text-slate-500">Positive vs Negative vs Mixed</p>
                  </div>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} barCategoryGap={18} margin={{ top: 16, right: 12, left: 0, bottom: 10 }}>
                        <CartesianGrid stroke="rgba(148,163,184,0.14)" vertical={false} />
                        <XAxis
                          dataKey="label"
                          interval={0}
                          axisLine={false}
                          tickLine={false}
                          tickMargin={10}
                          tick={{ fill: "#cbd5e1", fontSize: 12 }}
                        />
                        <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 12 }} />
                        <Tooltip
                          cursor={{ fill: "rgba(148,163,184,0.08)" }}
                          contentStyle={{
                            background: "rgba(2,6,23,0.96)",
                            border: "1px solid rgba(71,85,105,0.8)",
                            borderRadius: "16px",
                            color: "#e2e8f0",
                          }}
                        />
                        <Bar dataKey="value" barSize={44} maxBarSize={64} radius={[12, 12, 0, 0]}>
                          {chartData.map((entry) => (
                            <Cell key={entry.label} fill={entry.color} />
                          ))}
                          <LabelList dataKey="value" position="top" fill="#e2e8f0" fontSize={12} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </Card>
          </div>

          <div className="space-y-4 lg:col-span-5">
            <Card>
              <CardHeader
                title="Posts & Sentiment Feed"
                subtitle="Each result shows the website source used for analysis"
                meta={
                  feedHeaderSource ? (
                    <div className="flex min-w-0 flex-col gap-1 text-right">
                      <span className="text-[11px] uppercase tracking-[0.16em] text-slate-400">
                        {resolveSiteName(feedHeaderSource)}
                      </span>
                      <span className="truncate text-[11px] text-slate-300">
                        {feedHeaderSource.domain || resolveSiteName(feedHeaderSource)}
                      </span>
                      {feedHeaderSource.url ? (
                        <a
                          href={feedHeaderSource.url}
                          target="_blank"
                          rel="noreferrer"
                          className="truncate text-[11px] text-sky-300 transition hover:text-sky-200"
                          title={feedHeaderSource.url}
                        >
                          {feedHeaderSource.url}
                        </a>
                      ) : null}
                    </div>
                  ) : null
                }
              />
              <div className="mt-3 max-h-[calc(100vh-15rem)] space-y-2.5 overflow-y-auto pr-1">
                {feedItems.length === 0 && (
                  <p className="rounded-[28px] border border-slate-700/70 bg-slate-900/60 px-5 py-4 text-sm text-slate-400">
                    {missingSourceMetadata
                      ? "Analysis finished, but the backend did not return source metadata for the posts. Restart the backend and run the scan again."
                      : "No live source-backed posts found yet. Run a scan with different keywords or sources."}
                  </p>
                )}

                {feedItems.map((item, idx) => {
                  const label = String(item.display_sentiment || item.sentiment || "NEUTRAL").toUpperCase();
                  const tone =
                    label === "POSITIVE"
                      ? "positive"
                      : label === "NEGATIVE"
                      ? "negative"
                      : "mixed";

                  return (
                    <PostRow
                      key={`${idx}-${label}-${item.url || item.text}`}
                      text={item.text}
                      title={resolvePostTitle(item)}
                      matchedOn={item.matched_on || item.query || "brand"}
                      sentiment={label}
                      tone={tone}
                      sourceLabel={item.source || resolveSiteName(item)}
                      sourceDetail={formatSourceDetail(resolveSiteName(item), item.domain, item.text)}
                      url={item.url}
                    />
                  );
                })}
              </div>
            </Card>
          </div>
        </section>

        <section className="grid gap-5 lg:grid-cols-12">
          <div className="lg:col-span-12">
            <Card>
              <CardHeader
                title="Groq Insight Summary"
                subtitle="Key themes, reputation risks, and PR strategy generated from the analysis response"
                meta={
                  <div className="rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.16em] text-sky-200">
                    {modelName}
                  </div>
                }
              />
              <div className="mt-4 grid gap-4 lg:grid-cols-3">
                <InsightPanel
                  title="Key Themes Or Concerns"
                  subtitle="Main conversation clusters detected by the Groq analysis"
                  items={themes}
                  emptyText="Run an analysis to see key themes and concerns."
                  tone="sky"
                />
                <InsightPanel
                  title="Potential Reputation Risks"
                  subtitle="Risk signals that could affect trust, sentiment, or PR"
                  items={risks}
                  emptyText="No reputation risks detected yet."
                  tone="rose"
                />
                <InsightPanel
                  title="Suggested PR Response Strategy"
                  subtitle="Recommended communication and response direction"
                  items={prStrategy}
                  emptyText="No PR response strategy available yet."
                  tone="emerald"
                />
              </div>
            </Card>
          </div>
        </section>
      </div>
    </div>
  );
}

function Card({ children, className = "" }) {
  return (
    <div className={`rounded-3xl border border-slate-700/70 bg-white/5 bg-gradient-to-b from-white/5 via-white/3 to-slate-900/60 p-4 shadow-[0_25px_60px_rgba(0,0,0,0.75)] backdrop-blur-2xl sm:p-5 ${className}`}>
      {children}
    </div>
  );
}

function CardHeader({ title, subtitle, meta = null }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight text-slate-50 sm:text-base">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-slate-400 sm:text-[13px]">{subtitle}</p>}
      </div>
      {meta ? <div className="max-w-[55%] min-w-0 shrink-0">{meta}</div> : null}
    </div>
  );
}

function MetricRow({ label, value }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-800/80 bg-slate-950/40 px-3 py-2">
      <span className="text-slate-400">{label}</span>
      <span className="font-medium text-slate-100">{value}</span>
    </div>
  );
}

function LegendDot({ color, label }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function PostRow({ text, title, matchedOn, sentiment, tone, sourceLabel, sourceDetail, url }) {
  const toneMap = {
    positive:
      "border-emerald-400/40 bg-emerald-500/10 text-emerald-200 ring-emerald-400/40",
    negative:
      "border-rose-400/40 bg-rose-500/10 text-rose-200 ring-rose-400/40",
    mixed:
      "border-amber-400/40 bg-amber-500/10 text-amber-200 ring-amber-400/40",
  };

  return (
    <article className="rounded-[28px] border border-slate-700/70 bg-slate-900/60 px-5 py-4 text-sm shadow-[0_10px_30px_rgba(0,0,0,0.22)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium text-slate-400">
            {sourceDetail || `scraped from ${sourceLabel || "Website"}`}
          </div>
        </div>
        <div className="text-[11px] font-medium text-slate-400">
          {matchedOn && matchedOn !== "manual" ? matchedOn : sourceLabel || "Website"}
        </div>
      </div>

      <div className="mt-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-xl font-semibold leading-snug text-slate-50">
            {title || "Untitled mention"}
          </h3>
          <p className="mt-4 text-sm leading-8 text-slate-300">{text}</p>
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="mt-5 inline-block text-sm font-medium text-amber-300 underline decoration-amber-300/70 underline-offset-2 transition hover:text-amber-200"
              title={url}
            >
              {`Open source on ${sourceLabel || "Website"}`}
            </a>
          ) : null}
        </div>
        <span className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] ring-1 ${toneMap[tone]}`}>
          {sentiment}
        </span>
      </div>
    </article>
  );
}

function InsightPanel({ title, subtitle, items, emptyText, tone }) {
  const toneMap = {
    sky: "border-sky-500/20 bg-sky-500/5 text-sky-100",
    rose: "border-rose-500/20 bg-rose-500/5 text-rose-100",
    emerald: "border-emerald-500/20 bg-emerald-500/5 text-emerald-100",
  };

  return (
    <div className="rounded-[28px] border border-slate-700/70 bg-slate-900/55 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.22)]">
      <div className="mb-4">
        <h3 className="text-sm font-semibold tracking-tight text-slate-50 sm:text-base">{title}</h3>
        <p className="mt-1 text-xs text-slate-400">{subtitle}</p>
      </div>

      {Array.isArray(items) && items.length > 0 ? (
        <div className="space-y-2.5">
          {items.map((item, idx) => (
            <div
              key={`${title}-${idx}-${item}`}
              className={`rounded-2xl border px-3 py-2 text-sm leading-6 ${toneMap[tone] || toneMap.sky}`}
            >
              {item}
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-2xl border border-slate-700/70 bg-slate-950/40 px-3 py-3 text-sm text-slate-400">
          {emptyText}
        </p>
      )}
    </div>
  );
}

function formatSourceLabel(sourceType) {
  const labels = {
    youtube: "YouTube",
    reddit: "Reddit",
    twitter: "X / Twitter",
    reviews: "Reviews",
    complaints: "Complaints",
    news: "News",
    app_reviews: "App Reviews",
    web: "Web",
    manual: "Website",
  };
  return labels[sourceType] || "Web";
}

function formatSourceDetail(siteName, domain, text = "") {
  const inferredDomain = extractDomain(text);
  if (siteName && siteName !== "Website" && siteName !== "Manual") {
    return `scraped from ${siteName}${domain && domain !== "manual" ? ` | ${domain}` : inferredDomain ? ` | ${inferredDomain}` : ""}`;
  }
  if (domain && domain !== "manual") {
    return `scraped from ${domain}`;
  }
  if (inferredDomain) {
    return `scraped from ${inferredDomain}`;
  }
  return "";
}

function resolveSiteName(item) {
  const explicit = String(item?.site_name || item?.source || "").trim();
  if (
    explicit &&
    !["manual", "website", "web", "reviews", "news", "app reviews", "complaints"].includes(
      explicit.toLowerCase()
    )
  ) {
    return explicit;
  }

  const domain = resolveDomain(item).toLowerCase();
  const url = normalizeUrl(String(item?.url || "")).toLowerCase();
  const haystack = `${domain} ${url} ${item?.text || ""} ${item?.title || ""}`.toLowerCase();

  if (haystack.includes("reddit")) return "Reddit";
  if (haystack.includes("youtube") || haystack.includes("youtu.be")) return "YouTube";
  if (haystack.includes("instagram")) return "Instagram";
  if (haystack.includes("facebook")) return "Facebook";
  if (haystack.includes("twitter") || haystack.includes("x.com")) return "X / Twitter";
  if (haystack.includes("trustpilot")) return "Trustpilot";
  if (haystack.includes("sitejabber")) return "Sitejabber";
  if (haystack.includes("capterra")) return "Capterra";
  if (haystack.includes("g2.com") || haystack.includes(" g2 ")) return "G2";
  if (haystack.includes("complaintsboard")) return "ComplaintsBoard";
  if (haystack.includes("voxya")) return "Voxya";
  if (haystack.includes("consumercomplaints")) return "ConsumerComplaints";
  if (haystack.includes("reuters")) return "Reuters";
  if (haystack.includes("bloomberg")) return "Bloomberg";
  if (haystack.includes("bbc")) return "BBC";

  const extractedDomain = extractDomain(item?.text || "") || extractDomain(item?.title || "");
  if (extractedDomain) {
    return extractedDomain;
  }

  return formatSourceLabel(resolveSourceType(item));
}

function extractDomain(value) {
  const text = String(value || "").toLowerCase();
  const match = text.match(/\b([a-z0-9-]+\.(?:com|in|org|net|co|io|ai|app))\b/);
  return match ? match[1] : "";
}

function normalizeUrl(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (text.startsWith("//")) {
    return `https:${text}`;
  }
  if (/^https?:\/\//i.test(text)) {
    return text;
  }
  if (text.startsWith("/")) {
    return "";
  }
  if (text.includes(".") && !/\s/.test(text)) {
    return `https://${text}`;
  }
  return "";
}

function resolveDomain(item) {
  const explicitDomain = String(item?.domain || "").trim().toLowerCase();
  if (explicitDomain && explicitDomain !== "manual") {
    return explicitDomain;
  }
  const normalizedUrl = normalizeUrl(item?.url || "");
  if (normalizedUrl) {
    try {
      return new URL(normalizedUrl).hostname.replace(/^www\./, "").toLowerCase();
    } catch {
      return extractDomain(normalizedUrl);
    }
  }
  return extractDomain(item?.text || "") || extractDomain(item?.title || "") || "manual";
}

function resolveSourceType(item) {
  const explicit = String(item?.source_type || "").trim().toLowerCase();
  if (explicit && explicit !== "manual") {
    return explicit;
  }
  const domain = resolveDomain(item);
  if (domain.includes("reddit")) return "reddit";
  if (domain.includes("youtube") || domain.includes("youtu.be")) return "youtube";
  if (domain.includes("instagram")) return "instagram";
  if (domain.includes("facebook")) return "facebook";
  if (domain.includes("twitter") || domain.includes("x.com")) return "twitter";
  if (["trustpilot.com", "g2.com", "capterra.com", "sitejabber.com"].some((name) => domain.includes(name))) return "reviews";
  if (domain.includes("complaintsboard") || domain.includes("voxya") || domain.includes("consumercomplaints")) return "complaints";
  if (["reuters.com", "bloomberg.com", "bbc.com", "news.google.com"].some((name) => domain.includes(name))) return "news";
  if (domain.includes("play.google.com") || domain.includes("apps.apple.com")) return "app_reviews";
  if (domain !== "manual") return "web";
  return "manual";
}

function resolvePostTitle(item) {
  const explicitTitle = String(item?.title || "").trim();
  if (explicitTitle) {
    return explicitTitle;
  }

  const topic = String(item?.matched_on || item?.query || "").trim();
  const site = resolveSiteName(item);

  if (site && site !== "Manual" && site !== "Website" && topic && topic !== "manual") {
    return `${site} | ${topic}`;
  }
  if (site && site !== "Manual" && site !== "Website") {
    return site;
  }
  if (topic && topic !== "manual") {
    return topic;
  }

  const extractedDomain = extractDomain(item?.text || "") || extractDomain(item?.url || "");
  if (extractedDomain) {
    return extractedDomain;
  }

  return resolveDomain(item) !== "manual" ? resolveDomain(item) : "Website";
}

function formatLoadingSources(selectedSources) {
  if (!Array.isArray(selectedSources) || selectedSources.length === 0) {
    return "web sources";
  }
  return selectedSources.slice(0, 3).map((source) => formatSourceLabel(source)).join(", ");
}

function compareBySourcePriority(a, b, sourcePriority) {
  const aRank = getSourcePriority(a, sourcePriority);
  const bRank = getSourcePriority(b, sourcePriority);
  if (aRank !== bRank) {
    return aRank - bRank;
  }
  // Secondary ordering: group by site/domain so results from the same
  // website appear together, then fall back to original order via text.
  const aDomain = String(a?.domain || "").toLowerCase();
  const bDomain = String(b?.domain || "").toLowerCase();
  if (aDomain && bDomain && aDomain !== bDomain) {
    return aDomain.localeCompare(bDomain);
  }
  const aTitle = String(a?.title || a?.text || "");
  const bTitle = String(b?.title || b?.text || "");
  return aTitle.localeCompare(bTitle);
}

function getSourcePriority(item, sourcePriority) {
  if (!(sourcePriority instanceof Map) || sourcePriority.size === 0) {
    return Number.MAX_SAFE_INTEGER;
  }
  const sourceType = String(item?.source_type || "").toLowerCase();
  const normalized =
    sourceType === "x"
      ? "twitter"
      : sourceType;
  if (sourcePriority.has(normalized)) {
    return sourcePriority.get(normalized);
  }
  const siteName = String(item?.site_name || "").toLowerCase();
  if (siteName.includes("twitter") || siteName === "x / twitter") {
    return sourcePriority.has("twitter") ? sourcePriority.get("twitter") : Number.MAX_SAFE_INTEGER;
  }
  if (siteName.includes("youtube")) {
    return sourcePriority.has("youtube") ? sourcePriority.get("youtube") : Number.MAX_SAFE_INTEGER;
  }
  if (siteName.includes("reddit")) {
    return sourcePriority.has("reddit") ? sourcePriority.get("reddit") : Number.MAX_SAFE_INTEGER;
  }
  if (siteName.includes("instagram")) {
    return sourcePriority.has("instagram") ? sourcePriority.get("instagram") : Number.MAX_SAFE_INTEGER;
  }
  if (siteName.includes("facebook")) {
    return sourcePriority.has("facebook") ? sourcePriority.get("facebook") : Number.MAX_SAFE_INTEGER;
  }
  if (siteName.includes("complaints")) {
    return sourcePriority.has("complaints") ? sourcePriority.get("complaints") : Number.MAX_SAFE_INTEGER;
  }
  if (siteName.includes("review") || ["trustpilot", "g2", "capterra", "sitejabber"].some((name) => siteName.includes(name))) {
    return sourcePriority.has("reviews") ? sourcePriority.get("reviews") : Number.MAX_SAFE_INTEGER;
  }
  return Number.MAX_SAFE_INTEGER;
}

export default App;
