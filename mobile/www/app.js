/* ScholarHub mobile – vanilla JS, talks to Supabase, AdMob via Capacitor plugin. */
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
const CapApp = Cap && Cap.Plugins && Cap.Plugins.App;
const SHARE_BASE = (window.SHARE_URL || "").replace(/\/$/, "");
const shareLink = (i) => (SHARE_BASE ? SHARE_BASE + "/?s=" + encodeURIComponent(i.id) : i.url);

async function openUrl(url) {
  if (!url) return;
  try { if (Browser && Browser.open) { await Browser.open({ url, presentationStyle: "popover" }); return; } } catch (e) { console.warn("Browser plugin failed", e); }
  // Fallbacks: real anchor click (works in WebView) then window.open / location
  try {
    const a = document.createElement("a"); a.href = url; a.target = "_blank"; a.rel = "noopener"; document.body.appendChild(a); a.click(); a.remove(); return;
  } catch (e) {}
  const w = window.open(url, "_blank"); if (!w) location.href = url;
}
async function shareItem(i) {
  const link = shareLink(i);
  // Scholarship page first (chat apps preview the FIRST link → shows the real site's title/image), then our app link
  const text = "🎓 " + i.title + (i.deadline ? "\n⏰ Deadline: " + i.deadline : "") + (i.url && i.url !== link ? "\n" + i.url : "") + "\n\n📲 Open in ScholarHub (more scholarships, deadline tracking): " + link;
  // link is already inside `text`; passing it as `url` too makes Android show it twice
  try { if (Share && Share.share) return await Share.share({ title: i.title, text, dialogTitle: "Share scholarship" }); } catch (e) {}
  try { if (navigator.share) return await navigator.share({ title: i.title, text }); } catch (e) {}
  try { await navigator.clipboard.writeText(text); alert("Link copied"); } catch (e) { prompt("Copy link", link); }
}
// Deep link: open a specific scholarship by id (from a shared link)
async function openById(id) {
  if (!id) return;
  let i = state.items.find((x) => x.id === id) || savedItems[id];
  if (!i) { try { i = (await api("/scholarships?select=id,title,url,source,summary,published,deadline,countries,regions,levels,fields,funding,tier&id=eq." + encodeURIComponent(id))).items[0]; } catch (e) {} }
  if (i) openDetail(i); else alert("This scholarship is no longer listed.");
}
function idFromUrl(u) { try { return new URL(u).searchParams.get("s"); } catch (e) { return null; } }

const $ = (s) => document.querySelector(s);
const state = { tab: "all", region: "", q: "", level: "", field: "", funding: "", tier: "", country: "", expired: 0, offset: 0, items: [], total: 0, detailOpens: 0 };
const saved = new Set(JSON.parse(localStorage.getItem("saved") || "[]"));
const savedItems = JSON.parse(localStorage.getItem("savedItems") || "{}");
// My Plan: personal to-do list + per-scholarship notes (stored on the phone only)
const plan = JSON.parse(localStorage.getItem("plan") || "[]");
const notes = JSON.parse(localStorage.getItem("notes") || "{}");
const savePlan = () => { localStorage.setItem("plan", JSON.stringify(plan)); localStorage.setItem("notes", JSON.stringify(notes)); };
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
function addTask(text, due, item) {
  text = (text || "").trim(); if (!text) return;
  plan.unshift({ id: uid(), text, due: due || "", done: false, sid: item ? item.id : "", stitle: item ? item.title : "", created: Date.now() });
  if (item && !savedItems[item.id]) savedItems[item.id] = item;
  savePlan();
}

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
    // Reserve space for the banner BEFORE it appears so it never covers the tab bar; refine when the real size arrives
    const setAdH = (h) => document.documentElement.style.setProperty("--ad-h", Math.round(h) + "px");
    setAdH(62);
    const onSize = (s) => { let h = s && s.height ? s.height : 0; if (h > 130) h = h / (window.devicePixelRatio || 1); if (h > 0) setAdH(h + 2); };
    AdMob.addListener("bannerAdSizeChanged", onSize);
    AdMob.addListener("bannerAdLoaded", () => {});
    AdMob.addListener("bannerAdFailedToLoad", () => setAdH(0));
    await AdMob.showBanner({ adId: window.ADMOB.bannerId, adSize: "ADAPTIVE_BANNER", position: "BOTTOM_CENTER", margin: 0, isTesting: window.ADMOB.testing });
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
  if (state.q) { const q = state.q.replace(/[%*,()."'\\:&|!<>]/g, " ").replace(/\s+/g, " ").trim(); if (q) p.set("and", `(or(title.wfts(english).${q},summary.wfts(english).${q}))`); }
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
let loadSeq = 0;
async function load(reset = true) {
  const seq = ++loadSeq; // ignore responses from older requests (fixes unrelated results while typing)
  if (reset) { state.offset = 0; state.items = []; $("#list").innerHTML = '<div class="loading">Loading opportunities…</div>'; }
  if (state.tab === "saved") { state.items = Object.values(savedItems); state.total = state.items.length; render(); return; }
  if (state.tab === "plan") { renderPlan(); return; }
  try {
    const data = await api(buildQuery(state.offset), { Prefer: "count=exact" });
    if (seq !== loadSeq) return;
    const items = data.items;
    state.items = state.items.concat(items); state.total = data.total; state.offset += data.items.length;
    localStorage.setItem("cache:" + buildQuery(0), JSON.stringify({ items: state.items.slice(0, 60), total: data.total, t: Date.now() }));
    render(); setOffline(false);
  } catch (e) {
    if (seq !== loadSeq) return;
    const c = JSON.parse(localStorage.getItem("cache:" + buildQuery(0)) || "null");
    if (c) { state.items = c.items; state.total = c.total; render(); }
    else $("#list").innerHTML = '<div class="empty">Could not reach the server. Check your internet connection.</div>';
    setOffline(true);
  }
}
function setOffline(on) {
  let b = $(".offline");
  if (on && !b) { b = document.createElement("div"); b.className = "offline"; b.textContent = "Offline – showing saved results"; $("#top").after(b); }
  if (!on && b) b.remove();
}

// ---------- Daily boost (motivation for applicants; rotates daily, tap ↻ for another) ----------
const BOOSTS = [
  ["Every application you send is a seed. Not all will grow, but none grow if you never plant.", "Keep showing up"],
  ["Rejection is redirection, not a verdict on your worth.", "Never lose hope"],
  ["The scholar who got the award applied. That is the only real difference.", "Apply anyway"],
  ["You don't need to be the best candidate in the world — only the best version of yourself on paper today.", "Focus on your story"],
  ["One 'no' costs you nothing. One 'yes' can change your family's story.", "Keep applying"],
  ["Deadlines don't wait for perfect. Submit good, then improve the next one.", "Done beats perfect"],
  ["Most scholarships are not won by geniuses. They are won by people who finished the form.", "Finish the form"],
  ["Your background is not a weakness in your essay — it is the reason your story matters.", "Own your story"],
  ["Ten applications with tailored essays beat fifty copy-pasted ones.", "Quality over quantity"],
  ["Ask for recommendation letters early — give your referees at least 3 weeks and a summary of your achievements.", "Tip"],
  ["Read the eligibility twice. Half of all rejections happen before anyone reads the essay.", "Tip"],
  ["Answer the actual question in the essay prompt. Reviewers notice when you don't.", "Tip"],
  ["Start your motivation letter with a specific moment, not with 'I am writing to apply…'", "Tip"],
  ["Keep a folder with your CV, transcripts, passport scan and a 500-word bio. Each new application becomes 10× faster.", "Tip"],
  ["The people who got funded last year felt exactly as unsure as you feel now.", "You belong here"],
  ["Slow progress is still progress. Open one application today, even if you only fill in your name.", "Small steps"],
  ["Nobody is coming to apply for you. And that's good — it means it's in your hands.", "It's in your hands"],
  ["A funded degree is not a miracle; it is a numbers game played with patience.", "Be patient, be persistent"],
  ["When you get tired, rest. Don't quit.", "Rest, don't quit"],
  ["Your 'someday' starts with what you submit this week.", "Start now"],
  ["You are not behind. You are on your own timeline, and it is still running.", "Your timeline"],
  ["The essay you're afraid to write is usually the one that gets you in.", "Be brave on paper"],
  ["Waitlists turn into offers every year. Keep your email checked and your hope alive.", "Hope is a strategy"],
  ["Show them impact: numbers, names, results. 'I led a team of 12 that raised ₦2m' beats 'I am a leader'.", "Tip"],
  ["Proofread out loud. Your ear will catch what your eye skips.", "Tip"],
  ["Every expert applicant was once a confused beginner reading the requirements for the first time.", "You'll learn"],
  ["Don't compare your chapter 2 to someone else's chapter 10.", "Run your race"],
  ["A referee who knows you well beats a famous one who barely does.", "Tip"],
  ["If you never hear back, you did not fail — you learned the process for free. Reuse everything.", "Nothing is wasted"],
  ["Faith, focus and follow-through. Show up again tomorrow.", "See you tomorrow"],
];
let boostIdx = Math.floor((Date.now() / 864e5)) % BOOSTS.length;
function boostHtml() { const [q, tag] = BOOSTS[boostIdx]; return `<div class="boost" id="boost"><div class="boost-tag">✨ ${esc(tag)}</div><div class="boost-q">${esc(q)}</div><button class="boost-next" data-boost="1" aria-label="Another one">↻</button></div>`; }
function nextBoost() { boostIdx = (boostIdx + 1) % BOOSTS.length; const b = $("#boost"); if (b) b.outerHTML = boostHtml(); }
// Gentle pop-up: 3s after open, then every 5 min. Sits above tab bar + ad, auto-hides after 8s, tap ✕ or swipe to clear.
let toastTimer;
function showBoostToast() {
  if (document.querySelector(".sheet:not(.hidden)") || document.hidden) return; // never over a sheet or when app is in background
  hideBoostToast();
  const [q, tag] = BOOSTS[boostIdx]; boostIdx = (boostIdx + 1) % BOOSTS.length;
  const t = document.createElement("div"); t.className = "toast"; t.id = "toast";
  t.innerHTML = `<div class="toast-tag">✨ ${esc(tag)}</div><div class="toast-q">${esc(q)}</div><button class="toast-x" aria-label="Dismiss">✕</button>`;
  document.body.appendChild(t); requestAnimationFrame(() => t.classList.add("in"));
  t.querySelector(".toast-x").onclick = hideBoostToast;
  let sx = 0; t.addEventListener("touchstart", (e) => (sx = e.touches[0].clientX), { passive: true });
  t.addEventListener("touchend", (e) => { if (Math.abs(e.changedTouches[0].clientX - sx) > 60) hideBoostToast(); }, { passive: true });
  toastTimer = setTimeout(hideBoostToast, 8000);
}
function hideBoostToast() { clearTimeout(toastTimer); const t = $("#toast"); if (t) { t.classList.remove("in"); setTimeout(() => t.remove(), 300); } }

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
function renderPlan() {
  const list = $("#list"); $("#more").classList.add("hidden");
  const open = plan.filter((t) => !t.done), done = plan.filter((t) => t.done);
  $("#stats").textContent = `${open.length} to do · ${done.length} done`;
  const dueTxt = (d) => { if (!d) return ""; const days = Math.round((new Date(d) - new Date().setHours(0, 0, 0, 0)) / 864e5); return `<span class="${days < 0 ? "dl past" : days <= 3 ? "dl soon" : ""}">📅 ${d}${days < 0 ? " (overdue)" : days === 0 ? " (today)" : days > 0 && days <= 14 ? ` (${days}d)` : ""}</span>`; };
  const row = (t) => `<div class="task ${t.done ? "done" : ""}" data-task="${t.id}">
      <input type="checkbox" data-done="${t.id}" ${t.done ? "checked" : ""}>
      <div class="body"><div class="txt">${esc(t.text)}</div>
        <div class="sub">${dueTxt(t.due)}${t.sid ? `${t.due ? " · " : ""}🎓 <a href="#" data-goto="${esc(t.sid)}">${esc(t.stitle).slice(0, 60)}</a>` : ""}</div></div>
      <button class="del" data-del="${t.id}" aria-label="Delete">✕</button></div>`;
  list.innerHTML = boostHtml() + `<div class="plan-add">
      <textarea id="tText" placeholder="What are you working on? e.g. Request transcript for DAAD application, write motivation letter…"></textarea>
      <div class="row"><input type="date" id="tDue" aria-label="Due date"><button id="tAdd">＋ Add</button></div></div>
    ${plan.length ? "" : '<div class="empty">Your plan is empty. Add tasks here, or open any scholarship and tap "Add to plan".</div>'}
    ${open.length ? '<div class="plan-h">To do</div>' + open.map(row).join("") : ""}
    ${done.length ? '<div class="plan-h">Done</div>' + done.map(row).join("") : ""}`;
  $("#tAdd").onclick = () => { addTask($("#tText").value, $("#tDue").value); renderPlan(); };
  $("#tText").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#tAdd").click(); } };
}
function openDetail(i) {
  maybeInterstitial();
  $("#detailBody").innerHTML = `<div class="detail">
    <h2>${esc(i.title)}</h2>${deadlineHtml(i.deadline)}${tags(i)}
    <p>${esc(i.summary)}</p>
    <div class="muted">Source: ${esc(i.source)}</div>
    <div class="muted" style="word-break:break-all;margin-top:4px"><a href="${esc(i.url)}" data-open="${esc(i.url)}" style="color:#38bdf8">${esc(i.url)}</a></div>
    <div class="actions">
      <button class="ghost" id="dSave">${saved.has(i.id) ? "★ Saved" : "☆ Save"}</button>
      <button class="ghost" id="dShare">Share</button>
      <button id="dOpen">Apply / Details ↗</button>
    </div>
    <div class="muted" style="margin-top:16px">📝 My notes for this scholarship</div>
    <textarea class="note" id="dNote" placeholder="e.g. Need 2 reference letters, IELTS 6.5, submit before 15 March…">${esc(notes[i.id] || "")}</textarea>
    <div class="row" style="justify-content:space-between;margin-top:6px"><span class="muted" id="dNoteSaved">${planCount(i.id)}</span><button class="ghost" id="dPlan">＋ Add to plan</button></div></div>`;
  $("#detail").classList.remove("hidden");
  $("#detailBody").querySelectorAll("[data-open]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openUrl(a.dataset.open); }));
  $("#dOpen").onclick = () => openUrl(i.url);
  $("#dShare").onclick = () => shareItem(i);
  $("#dSave").onclick = () => { toggleSave(i); $("#dSave").textContent = saved.has(i.id) ? "★ Saved" : "☆ Save"; };
  let nt; $("#dNote").oninput = (e) => { clearTimeout(nt); nt = setTimeout(() => { const v = e.target.value.trim(); if (v) notes[i.id] = v; else delete notes[i.id]; if (v && !savedItems[i.id]) { savedItems[i.id] = i; saved.add(i.id); localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems)); } savePlan(); $("#dNoteSaved").textContent = "Saved ✓"; }, 500); };
  $("#dPlan").onclick = () => { const text = prompt("Task for “" + i.title.slice(0, 40) + "…”", "Apply: " + i.title.slice(0, 60)); if (text === null) return; addTask(text, i.deadline || "", i); $("#dNoteSaved").textContent = planCount(i.id) + " · added ✓"; };
}
function planCount(sid) { const n = plan.filter((t) => t.sid === sid && !t.done).length; return n ? `${n} open task${n > 1 ? "s" : ""} in plan` : "Notes save automatically"; }
function toggleSave(i) {
  if (saved.has(i.id)) { saved.delete(i.id); delete savedItems[i.id]; } else { saved.add(i.id); savedItems[i.id] = i; }
  localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems));
  document.querySelectorAll(`[data-star="${i.id}"]`).forEach((b) => b.classList.toggle("on", saved.has(i.id)));
}

// ---------- events ----------
$("#list").addEventListener("click", (e) => {
  if (e.target.closest("[data-boost]")) { nextBoost(); return; }
  const dn = e.target.closest("[data-done]");
  if (dn) { const t = plan.find((x) => x.id === dn.dataset.done); if (t) { t.done = dn.checked; savePlan(); setTimeout(renderPlan, 250); } return; }
  const del = e.target.closest("[data-del]");
  if (del) { const k = plan.findIndex((x) => x.id === del.dataset.del); if (k > -1 && confirm("Delete this task?")) { plan.splice(k, 1); savePlan(); renderPlan(); } return; }
  const go = e.target.closest("[data-goto]");
  if (go) { e.preventDefault(); openById(go.dataset.goto); return; }
  const open = e.target.closest("[data-open]");
  if (open) { e.preventDefault(); openUrl(open.dataset.open); return; }
  const star = e.target.closest("[data-star]");
  if (star) { const i = state.items.find((x) => x.id === star.dataset.star); if (i) toggleSave(i); return; }
  const card = e.target.closest(".card"); if (!card) return;
  const i = state.items.find((x) => x.id === card.dataset.id); if (i) openDetail(i);
});
$("#more").onclick = () => load(false);
function doSearch(closeKeyboard) {
  const q = $("#q").value.trim();
  if (q !== state.q) { state.q = q; load(true); }
  if (closeKeyboard) $("#q").blur();
}
let t; $("#q").oninput = () => { clearTimeout(t); t = setTimeout(() => doSearch(false), 900); };
$("#q").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(t); doSearch(true); } };
if ($("#searchBtn")) $("#searchBtn").onclick = () => { clearTimeout(t); doSearch(true); };
async function refresh() {
  const b = $("#refreshBtn"); if (b) b.classList.add("spin");
  Object.keys(localStorage).filter((k) => k.startsWith("cache:")).forEach((k) => localStorage.removeItem(k));
  await load(); if (b) b.classList.remove("spin"); window.scrollTo(0, 0);
}
if ($("#refreshBtn")) $("#refreshBtn").onclick = refresh;
// pull-to-refresh (only when scrolled to the top)
let ptrY = 0, ptrOn = false;
document.addEventListener("touchstart", (e) => { ptrY = e.touches[0].clientY; ptrOn = window.scrollY <= 0; }, { passive: true });
document.addEventListener("touchmove", (e) => { if (!ptrOn) return; const d = e.touches[0].clientY - ptrY; if ($("#ptr")) $("#ptr").style.height = Math.min(Math.max(d / 2, 0), 60) + "px"; }, { passive: true });
document.addEventListener("touchend", (e) => { const d = e.changedTouches[0].clientY - ptrY; if ($("#ptr")) $("#ptr").style.height = "0px"; if (ptrOn && d > 110) refresh(); ptrOn = false; }, { passive: true });
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
    $("#pList").innerHTML = pulls.length ? pulls.map((p) => `<div style="margin:4px 0">${p.status === "done" ? "✅" : p.status === "error" ? "❌" : "⏳"} ${esc(p.url).slice(0, 60)} <small>${p.status}${p.found != null ? ` · found ${p.found}, new ${p.new_items}` : ""}${p.error ? " · " + esc(p.error).slice(0, 80) : ""}</small></div>`).join("") : "No pulls yet";
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
  // deep links: app opened from a shared link (native) or web URL with ?s=<id>
  const startId = idFromUrl(location.href);
  if (startId) setTimeout(() => openById(startId), 300);
  if (CapApp && CapApp.addListener) {
    CapApp.addListener("appUrlOpen", (ev) => { const id = idFromUrl(ev.url); if (id) openById(id); });
    try { CapApp.getLaunchUrl().then((r) => { const id = r && r.url && idFromUrl(r.url); if (id) openById(id); }).catch(() => {}); } catch (e) {}
  }
  // motivation pop-ups: shortly after open, then every 5 minutes of use
  setTimeout(showBoostToast, 3000);
  setInterval(showBoostToast, 5 * 60 * 1000);
  // refresh when a new crawl has landed (twice a day) – check every 10 min while the app is open
  let lastRun = null;
  setInterval(async () => { try { const s = (await api("/app_stats?select=last_run")).items[0]; if (lastRun && s.last_run !== lastRun && state.tab === "all" && !state.q) load(); lastRun = s.last_run; } catch (e) {} }, 600000);
}
init();
