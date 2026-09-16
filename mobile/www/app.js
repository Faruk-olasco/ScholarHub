/* ScholarHub mobile – vanilla JS, talks to the FastAPI server, AdMob via Capacitor plugin. */
const SB_URL = (window.SUPABASE_URL || "").replace(/\/$/, "") + "/rest/v1";
const SB_HEADERS = { apikey: window.SUPABASE_ANON_KEY, Authorization: "Bearer " + window.SUPABASE_ANON_KEY, Accept: "application/json" };
const FILTERS = {
  levels: ["phd", "masters", "undergraduate", "postdoc", "fellowship", "research", "short course"],
  fields: ["STEM", "Health", "Business", "Arts & Humanities", "Social Sciences", "Environment"],
  regions: ["Africa", "Europe", "North America", "Asia", "Middle East", "Oceania", "Latin America"],
  funding: ["fully funded", "partially funded"],
};
const Cap = window.Capacitor;
const isNative = !!(Cap && Cap.isNativePlatform && Cap.isNativePlatform());
const AdMob = Cap && Cap.Plugins && Cap.Plugins.AdMob;
const Browser = Cap && Cap.Plugins && Cap.Plugins.Browser;
const Share = Cap && Cap.Plugins && Cap.Plugins.Share;

const $ = (s) => document.querySelector(s);
const state = { tab: "all", region: "", q: "", level: "", field: "", funding: "", tier: "", country: "", expired: 0, offset: 0, items: [], total: 0, detailOpens: 0 };
const saved = new Set(JSON.parse(localStorage.getItem("saved") || "[]"));
const savedItems = JSON.parse(localStorage.getItem("savedItems") || "{}");

// ---------- AdMob ----------
async function initAds() {
  if (!isNative || !AdMob) return;
  try {
    await AdMob.initialize({ initializeForTesting: window.ADMOB.testing });
    // Consent (GDPR/UMP) – required by Google for EEA users
    try {
      const consent = await AdMob.requestConsentInfo();
      if (consent.isConsentFormAvailable && consent.status === "REQUIRED") await AdMob.showConsentForm();
    } catch (e) { console.warn("consent", e); }
    await AdMob.showBanner({ adId: window.ADMOB.bannerId, adSize: "ADAPTIVE_BANNER", position: "BOTTOM_CENTER", margin: 0, isTesting: window.ADMOB.testing });
    AdMob.addListener("bannerAdSizeChanged", (s) => document.documentElement.style.setProperty("--ad-h", (s.height || 0) + "px"));
    await AdMob.prepareInterstitial({ adId: window.ADMOB.interstitialId, isTesting: window.ADMOB.testing });
  } catch (e) { console.warn("AdMob init failed", e); }
}
async function maybeInterstitial() {
  state.detailOpens++;
  if (!isNative || !AdMob || state.detailOpens % window.ADMOB.interstitialEvery !== 0) return;
  try { await AdMob.showInterstitial(); await AdMob.prepareInterstitial({ adId: window.ADMOB.interstitialId, isTesting: window.ADMOB.testing }); } catch (e) {}
}

// ---------- data (Supabase PostgREST, read-only with the anon key) ----------
const today = () => new Date().toISOString().slice(0, 10);
const like = (v) => "ilike.*" + v.replace(/[%*,()]/g, " ").trim() + "*";
function buildQuery(offset) {
  const p = new URLSearchParams();
  p.set("select", "id,title,url,source,summary,published,deadline,countries,regions,levels,fields,funding,tier");
  if (state.q) { const q = state.q.replace(/[%*,()]/g, " ").trim(); p.set("and", `(or(title.ilike.*${q}*,summary.ilike.*${q}*))`); }
  if (state.region) p.set("regions", like(state.region));
  if (state.level) p.set("levels", like(state.level));
  if (state.field) p.set("fields", like(state.field));
  if (state.funding) p.set("funding", like(state.funding));
  if (state.country) p.set("countries", like(state.country));
  if (state.tab === "official") p.set("tier", "eq.official"); else if (state.tier) p.set("tier", "eq." + state.tier);
  if (state.tab === "soon") { p.set("deadline", "gte." + today()); p.append("deadline", "lte." + new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10)); }
  else if (!state.expired) p.set("or", `(deadline.is.null,deadline.gte.${today()})`);
  // sort: dated & upcoming first (soonest), then open-ended; newest first within
  p.set("order", "deadline.asc.nullslast,published.desc");
  p.set("limit", 30); p.set("offset", offset);
  return "/scholarships?" + p.toString();
}
async function api(path, extraHeaders = {}) {
  const r = await fetch(SB_URL + path, { headers: { ...SB_HEADERS, ...extraHeaders } });
  if (!r.ok) throw new Error(r.status);
  const total = (r.headers.get("content-range") || "").split("/")[1];
  const data = await r.json();
  return { items: data, total: total && total !== "*" ? +total : data.length };
}
async function load(reset = true) {
  if (reset) { state.offset = 0; state.items = []; $("#list").innerHTML = '<div class="loading">Loading opportunities…</div>'; }
  if (state.tab === "saved") { state.items = Object.values(savedItems); state.total = state.items.length; render(); return; }
  try {
    const data = await api(buildQuery(state.offset), { Prefer: "count=exact" });
    const items = data.items;
    state.items = state.items.concat(items); state.total = data.total; state.offset += data.items.length;
    localStorage.setItem("cache:" + buildQuery(0), JSON.stringify({ items: state.items.slice(0, 60), total: data.total, t: Date.now() }));
    render(); setOffline(false);
  } catch (e) {
    const c = JSON.parse(localStorage.getItem("cache:" + buildQuery(0)) || "null");
    if (c) { state.items = c.items; state.total = c.total; render(); }
    else $("#list").innerHTML = '<div class="empty">Could not reach the server.<br>Check your internet connection.</div>';
    setOffline(true);
  }
}
function setOffline(on) {
  let b = $(".offline");
  if (on && !b) { b = document.createElement("div"); b.className = "offline"; b.textContent = "Offline – showing saved results"; $("#top").after(b); }
  if (!on && b) b.remove();
}

// ---------- render ----------
const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function deadlineHtml(d) {
  if (!d) return '<div class="dl ok">🟢 Open — apply now (no deadline stated)</div>';
  const days = Math.round((new Date(d) - new Date().setHours(0, 0, 0, 0)) / 864e5);
  const cls = days < 0 ? "past" : days <= 14 ? "soon" : "ok";
  const txt = days < 0 ? "expired" : days === 0 ? "today!" : days + " days left";
  return `<div class="dl ${cls}">⏰ Deadline ${d} (${txt})</div>`;
}
function tags(i) {
  let h = "";
  if (i.tier === "official") h += '<span class="tag off">🏛 official</span>';
  if (i.funding) h += `<span class="tag fund">${esc(i.funding)}</span>`;
  (i.levels || "").split(", ").filter(Boolean).forEach((l) => (h += `<span class="tag lvl">${esc(l)}</span>`));
  (i.regions || "").split(", ").filter(Boolean).forEach((r) => (h += `<span class="tag">🌍 ${esc(r)}</span>`));
  (i.countries || "").split(", ").filter(Boolean).slice(0, 3).forEach((c) => (h += `<span class="tag">📍 ${esc(c)}</span>`));
  return `<div class="tags">${h}</div>`;
}
function render() {
  const list = $("#list");
  if (!state.items.length) { list.innerHTML = '<div class="empty">No opportunities match. Try clearing filters.</div>'; $("#more").classList.add("hidden"); return; }
  list.innerHTML = state.items.map((i, idx) => `
    ${idx > 0 && idx % 8 === 0 && !isNative ? '<div class="ad-card">Advertisement</div>' : ""}
    <div class="card" data-id="${esc(i.id)}">
      <button class="star ${saved.has(i.id) ? "on" : ""}" data-star="${esc(i.id)}">★</button>
      <h3>${esc(i.title)}</h3>
      ${deadlineHtml(i.deadline)}
      <p>${esc(i.summary)}</p>
      ${tags(i)}
      <div class="meta">via ${esc(i.source)} · ${esc((i.published || "").slice(0, 10))}</div>
    </div>`).join("");
  $("#more").classList.toggle("hidden", state.tab === "saved" || state.offset >= state.total);
  $("#stats").textContent = `${state.total.toLocaleString()} opportunities${state.region ? " · " + state.region : ""}`;
  api("/app_stats?select=last_run").then((r) => { const t = r.items[0] && r.items[0].last_run; if (t) $("#stats").textContent += ` · updated ${new Date(t).toLocaleString([], { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}`; }).catch(() => {});
}
function openDetail(i) {
  maybeInterstitial();
  $("#detailBody").innerHTML = `<div class="detail">
    <h2>${esc(i.title)}</h2>${deadlineHtml(i.deadline)}${tags(i)}
    <p>${esc(i.summary)}</p>
    <div class="muted">Source: ${esc(i.source)}</div>
    <div class="actions">
      <button class="ghost" id="dSave">${saved.has(i.id) ? "★ Saved" : "☆ Save"}</button>
      <button class="ghost" id="dShare">Share</button>
      <button id="dOpen">Apply / Details ↗</button>
    </div></div>`;
  $("#detail").classList.remove("hidden");
  $("#dOpen").onclick = () => (Browser ? Browser.open({ url: i.url }) : window.open(i.url, "_blank"));
  $("#dShare").onclick = () => (Share ? Share.share({ title: i.title, text: i.title + (i.deadline ? " · Deadline " + i.deadline : ""), url: i.url }) : navigator.share && navigator.share({ title: i.title, url: i.url }));
  $("#dSave").onclick = () => { toggleSave(i); $("#dSave").textContent = saved.has(i.id) ? "★ Saved" : "☆ Save"; };
}
function toggleSave(i) {
  if (saved.has(i.id)) { saved.delete(i.id); delete savedItems[i.id]; } else { saved.add(i.id); savedItems[i.id] = i; }
  localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems));
  document.querySelectorAll(`[data-star="${i.id}"]`).forEach((b) => b.classList.toggle("on", saved.has(i.id)));
}

// ---------- events ----------
$("#list").addEventListener("click", (e) => {
  const star = e.target.closest("[data-star]");
  if (star) { const i = state.items.find((x) => x.id === star.dataset.star); if (i) toggleSave(i); return; }
  const card = e.target.closest(".card"); if (!card) return;
  const i = state.items.find((x) => x.id === card.dataset.id); if (i) openDetail(i);
});
$("#more").onclick = () => load(false);
let t; $("#q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); load(); }, 400); };
document.querySelectorAll(".tabs [data-tab]").forEach((b) => (b.onclick = () => { document.querySelectorAll(".tabs [data-tab]").forEach((x) => x.classList.remove("on")); b.classList.add("on"); state.tab = b.dataset.tab; load(); window.scrollTo(0, 0); }));
$("#filtersBtn").onclick = () => $("#sheet").classList.remove("hidden");
$("#apply").onclick = () => { state.level = $("#fLevel").value; state.field = $("#fField").value; state.funding = $("#fFunding").value; state.tier = $("#fTier").value; state.country = $("#fCountry").value.trim(); state.expired = $("#fExpired").checked ? 1 : 0; $("#sheet").classList.add("hidden"); load(); };
$("#clear").onclick = () => { ["fLevel", "fField", "fFunding", "fTier"].forEach((id) => ($("#" + id).value = "")); $("#fCountry").value = ""; $("#fExpired").checked = false; };
$("#alertsBtn").onclick = () => $("#alerts").classList.remove("hidden");
$("#aCancel").onclick = () => $("#alerts").classList.add("hidden");
$("#aSave").onclick = async () => {
  const fd = new URLSearchParams({ channel: $("#aChannel").value, address: $("#aAddress").value.trim(), keywords: $("#aKeywords").value.trim(), level: "", country: $("#aCountry").value.trim() });
  if (!fd.get("address")) return alert("Enter an email or Telegram chat ID");
  try {
    const r = await fetch(SB_URL + "/subscribers", { method: "POST", headers: { ...SB_HEADERS, "Content-Type": "application/json", Prefer: "resolution=merge-duplicates" }, body: JSON.stringify(Object.fromEntries(fd)) });
    if (!r.ok) throw new Error(r.status);
    alert("Subscribed! You'll be alerted about new matching scholarships."); $("#alerts").classList.add("hidden");
  } catch (e) { alert("Could not subscribe – check your connection."); }
};
document.querySelectorAll(".sheet").forEach((s) => s.addEventListener("click", (e) => { if (e.target === s) s.classList.add("hidden"); }));

// ---------- admin (tap logo 7×, then PIN) ----------
let logoTaps = 0, logoTimer;
document.querySelector(".brand").addEventListener("click", () => {
  logoTaps++; clearTimeout(logoTimer); logoTimer = setTimeout(() => (logoTaps = 0), 2500);
  if (logoTaps >= 7) { logoTaps = 0; const pin = prompt("Admin PIN"); if (pin === window.ADMIN_PIN) openAdmin(); }
});
async function openAdmin() {
  $("#admin").classList.remove("hidden"); refreshAdmin();
}
async function refreshAdmin() {
  try {
    const pulls = (await api("/pull_requests?select=url,status,found,new_items,error,created&order=created.desc&limit=8")).items;
    $("#pList").innerHTML = pulls.length ? pulls.map((p) => `<div style="margin:4px 0">${p.status === "done" ? "✅" : p.status === "error" ? "❌" : "⏳"} ${esc(p.url).slice(0, 60)}<br><small>${p.status}${p.found != null ? ` · found ${p.found}, new ${p.new_items}` : ""}${p.error ? " · " + esc(p.error).slice(0, 80) : ""}</small></div>`).join("") : "No pulls yet";
    const runs = (await api("/runs?select=started,finished,new_items,total_items&order=started.desc&limit=5")).items;
    $("#pRuns").innerHTML = runs.map((r) => `<div>${new Date(r.started).toLocaleString()} · +${r.new_items} new · ${r.total_items} total</div>`).join("") || "No crawls yet";
  } catch (e) { $("#pList").textContent = "Could not load (run supabase/schema.sql again to add the pull_requests table)"; }
}
$("#pCancel").onclick = () => $("#admin").classList.add("hidden");
$("#pQueue").onclick = async () => {
  const url = $("#pUrl").value.trim();
  if (!/^https?:\/\//.test(url)) return alert("Enter a full link starting with https://");
  try {
    const r = await fetch(SB_URL + "/pull_requests", { method: "POST", headers: { ...SB_HEADERS, "Content-Type": "application/json" }, body: JSON.stringify({ url, save_as_source: $("#pSave").checked, deep: $("#pDeep").checked }) });
    if (!r.ok) throw new Error(r.status);
    $("#pUrl").value = ""; alert("Queued. It will be pulled on the next crawl — or run “Pull from a link” on GitHub now."); refreshAdmin();
  } catch (e) { alert("Could not queue: " + e.message); }
};

// ---------- init ----------
async function init() {
  initAds();
  try {
    const f = FILTERS;
    const fill = (id, arr) => (document.getElementById(id).innerHTML += arr.map((v) => `<option>${esc(v)}</option>`).join(""));
    fill("fLevel", f.levels); fill("fField", f.fields); fill("fFunding", f.funding);
    $("#regionChips").innerHTML = ['<button class="chip on" data-region="">🌍 All</button>'].concat(f.regions.map((r) => `<button class="chip" data-region="${esc(r)}">${esc(r)}</button>`)).join("");
    document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { document.querySelectorAll(".chip").forEach((x) => x.classList.remove("on")); c.classList.add("on"); state.region = c.dataset.region; load(); }));
  } catch (e) {}
  load();
  // refresh when a new crawl has landed (twice a day) – check every 10 min while the app is open
  let lastRun = null;
  setInterval(async () => { try { const s = (await api("/app_stats?select=last_run")).items[0]; if (lastRun && s.last_run !== lastRun && state.tab === "all" && !state.q) load(); lastRun = s.last_run; } catch (e) {} }, 600000);
}
init();
