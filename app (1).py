import re, time, json, collections
from urllib.parse import urljoin, urlparse
import requests, pandas as pd, streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="SEO Intel Pro", page_icon="🚀", layout="wide")
UA = {"User-Agent": "Mozilla/5.0 (SEO-Intel-Pro)"}
GEOS = {"USA": ("US", 2840), "India": ("IN", 2356), "Austria": ("AT", 2040), "UK": ("GB", 2826)}

# ---------------- Sidebar ----------------
st.sidebar.header("⚙️ Settings")
max_pages = st.sidebar.slider("Max pages to crawl", 5, 100, 25)
st.sidebar.subheader("Country Tiers (editable)")
tiers = {"USA": 1, "UK": 1, "Austria": 2, "India": 3}
for c in GEOS:
    tiers[c] = st.sidebar.selectbox(c, [1, 2, 3], index=tiers[c] - 1, key=c)
st.sidebar.subheader("Optional Pro APIs")
dfs_login = st.sidebar.text_input("DataForSEO login")
dfs_pass = st.sidebar.text_input("DataForSEO password", type="password")
claude_key = st.sidebar.text_input("Anthropic API key", type="password")
st.sidebar.caption("Bina keys ke: Google Trends index + rule-based analysis. Keys ke saath: exact volume + AI strategy.")

# ---------------- Crawler ----------------
def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=12)
        return r.text if r.ok else ""
    except Exception:
        return ""

def discover(domain, limit):
    base = f"https://{domain}"
    urls = []
    sm = get(base + "/sitemap.xml")
    urls += re.findall(r"<loc>(.*?)</loc>", sm)
    urls = [u for u in urls if not u.endswith(".xml")][:limit]
    if not urls:
        html = get(base)
        soup = BeautifulSoup(html, "html.parser")
        urls = [base] + list({urljoin(base, a["href"]).split("#")[0] for a in soup.find_all("a", href=True)
                              if urlparse(urljoin(base, a["href"])).netloc.endswith(domain)})[:limit]
    return urls[:limit]

def parse(url):
    soup = BeautifulSoup(get(url), "html.parser")
    ld = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "{}")
            for x in (d if isinstance(d, list) else [d]):
                t = x.get("@type")
                ld += t if isinstance(t, list) else [t]
        except Exception:
            pass
    for t in soup(["script", "style", "nav", "footer"]):
        t.decompose()
    md = soup.find("meta", attrs={"name": "description"})
    return {"url": url, "title": soup.title.get_text(strip=True) if soup.title else "",
            "meta": md.get("content", "") if md else "",
            "h": [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])],
            "text": soup.get_text(" ", strip=True), "schema": [x for x in ld if x]}

# ---------------- Analysis ----------------
STOP = set("the a an and or of to in for on with is are be by at from as it this that your you we our can will how what why more all not".split())

def keywords(pages, top=40):
    try:
        import yake
        ex = yake.KeywordExtractor(lan="en", n=3, top=top)
        blob = " ".join(f"{p['title']}. {p['meta']}. {' . '.join(p['h'])}. {p['text'][:3000]}" for p in pages)
        kws = [k for k, _ in ex.extract_keywords(blob)]
    except Exception:
        words = [w for p in pages for w in re.findall(r"[a-zA-Z]{3,}", (p["title"] + " " + " ".join(p["h"])).lower()) if w not in STOP]
        kws = [w for w, _ in collections.Counter(words).most_common(top)]
    seen, out = set(), []
    for k in kws:
        if k.lower() not in seen:
            seen.add(k.lower()); out.append(k)
    return out

def entities(pages):
    text = " ".join(p["text"][:5000] for p in pages)
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        doc = nlp(text[:200000])
        c = collections.Counter((e.text.strip(), e.label_) for e in doc.ents if e.label_ in {"ORG", "PERSON", "GPE", "PRODUCT", "LOC"})
    except Exception:
        c = collections.Counter((m, "ENTITY") for m in re.findall(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)+\b", text))
    return pd.DataFrame([(e, l, n) for (e, l), n in c.most_common(40)], columns=["Entity", "Type", "Mentions"])

def intent(k):
    k = k.lower()
    if re.search(r"\b(buy|price|cost|cheap|order|hire|service|quote|pricing)\b", k): return "Transactional"
    if re.search(r"\b(best|top|vs|review|compare|alternative)\b", k): return "Commercial"
    if re.search(r"\b(how|what|why|guide|tips|tutorial|learn)\b", k): return "Informational"
    if re.search(r"\b(near me|in [a-z]+)\b", k): return "Local"
    return "Informational/Brand"

def strategy_report(pages, kws):
    n = len(pages)
    avg_words = sum(len(p["text"].split()) for p in pages) // max(n, 1)
    schema = collections.Counter(s for p in pages for s in p["schema"])
    intents = collections.Counter(intent(k) for k in kws)
    lt = sum(1 for k in kws if len(k.split()) >= 3)
    return {"Pages analysed": n, "Avg words/page": avg_words,
            "Pages with meta description": f"{sum(1 for p in pages if p['meta'])}/{n}",
            "Avg headings/page": round(sum(len(p['h']) for p in pages) / max(n, 1), 1),
            "Long-tail keyword share": f"{round(100 * lt / max(len(kws), 1))}%",
            "Search intent mix": dict(intents), "Schema types used": dict(schema) or "None found"}

def claude_strategy(domain, kws, ents, rep):
    prompt = (f"You are a senior SEO strategist. Domain: {domain}\nKeywords: {kws[:30]}\nEntities: {ents[:20]}\n"
              f"Signals: {rep}\nExplain: main topic, SEO strategy used (topic clusters, intent targeting, local, schema), "
              "content gaps and 5 concrete opportunities. Be specific.")
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": claude_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": "claude-sonnet-5-5", "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}, timeout=90)
    return r.json()["content"][0]["text"]

# ---------------- Volume ----------------
def dfs_volume(kws):
    res = {}
    for name, (_, code) in GEOS.items():
        r = requests.post("https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live", auth=(dfs_login, dfs_pass),
                          json=[{"keywords": kws[:1000], "location_code": code, "language_code": "en"}], timeout=90).json()
        items = (r.get("tasks") or [{}])[0].get("result") or []
        res[name] = {i["keyword"]: i.get("search_volume") for i in items}
    return res

def trends_index(kws):
    from pytrends.request import TrendReq
    out = {c: {} for c in GEOS}
    py = TrendReq(hl="en-US", tz=0)
    for c, (geo, _) in GEOS.items():
        for i in range(0, len(kws), 5):
            batch = kws[i:i + 5]
            try:
                py.build_payload(batch, geo=geo, timeframe="today 12-m")
                df = py.interest_over_time()
                for k in batch:
                    out[c][k] = int(df[k].mean()) if k in df else 0
            except Exception:
                for k in batch: out[c][k] = None
            time.sleep(1.5)
    return out

# ---------------- UI ----------------
st.title("🚀 SEO Intel Pro")
st.caption("Domain daalo → Keywords, Entities, Strategy, Country-wise Volume & Tier")
domain = st.text_input("Website domain", placeholder="example.com").replace("https://", "").replace("http://", "").strip("/")

comp = st.text_input("Competitor domain (optional, keyword gap ke liye)", placeholder="competitor.com").replace("https://", "").replace("http://", "").strip("/")

def gap_analysis(mine, theirs):
    toks = lambda k: {w for w in re.findall(r"[a-z]{3,}", k.lower()) if w not in STOP}
    mine_t = [toks(k) for k in mine]
    their_t = [toks(k) for k in theirs]
    covered = lambda t, pool: any(t and len(t & p) / len(t) >= 0.5 for p in pool)
    gap = [k for k, t in zip(theirs, their_t) if not covered(t, mine_t)]
    shared = [k for k, t in zip(theirs, their_t) if covered(t, mine_t)]
    unique = [k for k, t in zip(mine, mine_t) if not covered(t, their_t)]
    return gap, shared, unique

if st.button("Analyse", type="primary") and domain:
    with st.status("Crawling & analysing...", expanded=True) as s:
        urls = discover(domain, max_pages); st.write(f"{len(urls)} pages mile")
        pages = [p for p in (parse(u) for u in urls) if p["text"]]
        kws = keywords(pages); ents = entities(pages); rep = strategy_report(pages, kws)
        top = kws[:20]
        comp_kws = []
        if comp:
            st.write(f"Competitor crawl: {comp}")
            cpages = [p for p in (parse(u) for u in discover(comp, max_pages)) if p["text"]]
            comp_kws = keywords(cpages)
        if dfs_login and dfs_pass:
            st.write("DataForSEO se exact volume..."); vol = dfs_volume(top); mode = "Monthly searches (DataForSEO)"
        else:
            st.write("Google Trends se country interest..."); vol = trends_index(top[:10]); mode = "Interest index 0-100 (Google Trends, relative)"
        s.update(label="Done ✅", state="complete")

    t1, t2, t3, t4, t5, t6 = st.tabs(["🔑 Keywords", "🧠 Strategy", "🏷️ Entities", "🌍 Volume & Tiers", "📄 Pages", "⚔️ Competitor Gap"])
    with t6:
        if not comp:
            st.info("Upar competitor domain daalo, phir dobara Analyse dabao.")
        else:
            gap, shared, unique = gap_analysis(kws, comp_kws)
            c1, c2, c3 = st.columns(3)
            c1.metric("Gap (competitor pe hai, aap pe nahi)", len(gap))
            c2.metric("Shared topics", len(shared))
            c3.metric("Aapke unique", len(unique))
            st.subheader("🎯 Opportunity keywords (content banao)")
            st.dataframe(pd.DataFrame({"Keyword": gap, "Intent": [intent(k) for k in gap]}), use_container_width=True)
            with st.expander("Shared keywords"): st.write(shared)
            with st.expander("Sirf aapke keywords"): st.write(unique)
    with t1:
        kdf = pd.DataFrame({"Keyword": kws, "Intent": [intent(k) for k in kws], "Words": [len(k.split()) for k in kws]})
        st.dataframe(kdf, use_container_width=True); st.download_button("CSV", kdf.to_csv(index=False), "keywords.csv")
    with t2:
        st.json(rep)
        if claude_key:
            with st.spinner("Claude analysis..."):
                try: st.markdown(claude_strategy(domain, kws, ents["Entity"].tolist(), rep))
                except Exception as e: st.error(f"Claude error: {e}")
        else:
            st.info("Deep AI strategy ke liye sidebar mein Anthropic API key daalo.")
    with t3:
        st.dataframe(ents, use_container_width=True)
    with t4:
        st.caption(mode)
        rows = [{"Keyword": k, **{c: vol[c].get(k) for c in GEOS}} for k in vol["USA"]]
        vdf = pd.DataFrame(rows); st.dataframe(vdf, use_container_width=True)
        tot = {c: sum(v or 0 for v in vol[c].values()) for c in GEOS}
        tdf = pd.DataFrame([{"Country": c, "Tier": f"Tier {tiers[c]}", "Total": tot[c]} for c in GEOS]).sort_values("Tier")
        st.subheader("Tier summary"); st.dataframe(tdf, use_container_width=True)
        st.bar_chart(tdf.set_index("Country")["Total"])
    with t5:
        st.dataframe(pd.DataFrame([{"URL": p["url"], "Title": p["title"], "Words": len(p["text"].split()), "H-tags": len(p["h"])} for p in pages]), use_container_width=True)
