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
const FCM = Cap && Cap.Plugins && Cap.Plugins.FirebaseMessaging;      // "new scholarships" push (topic-based, no tokens stored by us)
const LocalNotif = Cap && Cap.Plugins && Cap.Plugins.LocalNotifications; // deadline reminders, scheduled on the phone
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
const state = { tab: "all", region: "", newOnly: 0, q: "", level: "", field: "", funding: "", tier: "", country: "", expired: 0, offset: 0, items: [], total: 0, detailOpens: 0 };
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
  if (item && !savedItems[item.id]) { savedItems[item.id] = item; scheduleDeadline(item); }
  savePlan();
}


// ---------- Notifications ----------
const notif = Object.assign({ daily: true, region: "", deadlines: true, asked: false }, JSON.parse(localStorage.getItem("notif") || "{}"));
const saveNotif = () => localStorage.setItem("notif", JSON.stringify(notif));
const topicOf = (r) => (r ? "r_" + r.toLowerCase().replace(/[^a-z]+/g, "_") : "all");
const nid = (str, k) => { let h = 0; for (const c of str) h = (h * 31 + c.charCodeAt(0)) | 0; return (Math.abs(h) % 10000000) * 100 + k; }; // stable int id per scholarship + days-left (0..14)
async function askPermission() {
  let ok = true;
  try { if (LocalNotif) { const r = await LocalNotif.requestPermissions(); ok = r.display === "granted"; } } catch (e) {}
  try { if (FCM) { const r = await FCM.requestPermissions(); ok = ok && r.receive === "granted"; } } catch (e) {}
  notif.asked = true; saveNotif(); return ok;
}
async function applyDailyPush() {
  if (!isNative || !FCM) return;
  try {
    try { await FCM.createChannel({ id: "scholarhub_daily", name: "New scholarships", description: "A notification after each crawl when new opportunities are added", importance: 3 }); } catch (e) {}
    const want = notif.daily ? topicOf(notif.region) : null;
    const topics = ["all"].concat(FILTERS.regions.map(topicOf));
    for (const t of topics) { if (t !== want) { try { await FCM.unsubscribeFromTopic({ topic: t }); } catch (e) {} } }
    if (want) await FCM.subscribeToTopic({ topic: want });
  } catch (e) { console.warn("push", e); }
}
async function scheduleDeadline(i) {
  if (!isNative || !LocalNotif || !notif.deadlines || !i.deadline) return;
  const dl = new Date(i.deadline + "T09:00:00"); const list = [];
  for (let d = 14; d >= 0; d--) { // one reminder every morning for the last 14 days, counting down
    const at = new Date(dl.getTime() - d * 864e5);
    if (at <= new Date()) continue;
    const title = d === 0 ? "⏰ Deadline is TODAY" : d === 1 ? "⏰ Deadline is tomorrow" : `⏰ ${d} days left`;
    list.push({ id: nid(i.id, d), title, body: i.title.slice(0, 90), schedule: { at, allowWhileIdle: true }, extra: { s: i.id }, smallIcon: "ic_stat_push", channelId: "scholarhub_deadlines" });
  }
  if (list.length) { try { await LocalNotif.schedule({ notifications: list }); } catch (e) { console.warn("schedule", e); } }
}
async function cancelDeadline(id) {
  if (!isNative || !LocalNotif) return;
  try { await LocalNotif.cancel({ notifications: Array.from({ length: 15 }, (_, k) => ({ id: nid(id, k) })) }); } catch (e) {}
}
async function rescheduleAllDeadlines() {
  if (!isNative || !LocalNotif) return;
  try { const p = await LocalNotif.getPending(); if (p.notifications.length) await LocalNotif.cancel(p); } catch (e) {}
  if (!notif.deadlines) return;
  try { await LocalNotif.createChannel({ id: "scholarhub_deadlines", name: "Deadline reminders", importance: 4 }); } catch (e) {}
  const seen = new Set();
  for (const i of Object.values(savedItems)) { if (!seen.has(i.id)) { seen.add(i.id); await scheduleDeadline(i); } }
}
function openNotifSheet() {
  $("#nDaily").checked = notif.daily; $("#nDeadlines").checked = notif.deadlines; $("#nRegion").value = notif.region;
  $("#nRegionWrap").style.display = notif.daily ? "" : "none";
  $("#nHint").textContent = isNative ? "Notifications are free and you can switch them off here any time. We never store your contact details." : "Install the Android app to receive notifications.";
  $("#alerts").classList.remove("hidden");
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
  if (state.newOnly) p.set("first_seen", "gte." + new Date(Date.now() - 36 * 3600e3).toISOString());
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
  $("#stats").textContent = `${state.total.toLocaleString()} ${state.newOnly ? "new " : ""}opportunities${state.region ? " · " + state.region : ""}${state.newOnly ? " · tap ↻ for all" : ""}`;
  api("/app_stats?select=last_run").then((r) => { const t = r.items[0] && r.items[0].last_run; if (t) $("#stats").textContent += ` · updated ${new Date(t).toLocaleString([], { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}`; }).catch(() => {});
}
let planView = localStorage.getItem("planView") || "todo", editingNote = null;
function renderPlan() {
  const list = $("#list"); $("#more").classList.add("hidden");
  const open = plan.filter((t) => !t.done), done = plan.filter((t) => t.done);
  const noteIds = Object.keys(notes).filter((k) => notes[k]);
  $("#stats").textContent = planView === "notes" ? `${noteIds.length} note${noteIds.length === 1 ? "" : "s"}` : `${open.length} to do · ${done.length} done`;
  const seg = `<div class="row" style="gap:8px;margin:4px 0 10px">
      <button class="${planView === "todo" ? "" : "ghost"}" data-pview="todo" style="flex:1">📋 Daily plan (To do)</button>
      <button class="${planView === "notes" ? "" : "ghost"}" data-pview="notes" style="flex:1">📝 Opportunity notes</button></div>`;
  const dueTxt = (d) => { if (!d) return ""; const days = Math.round((new Date(d) - new Date().setHours(0, 0, 0, 0)) / 864e5); return `<span class="${days < 0 ? "dl past" : days <= 3 ? "dl soon" : ""}">📅 ${d}${days < 0 ? " (overdue)" : days === 0 ? " (today)" : days > 0 && days <= 14 ? ` (${days}d)` : ""}</span>`; };
  const row = (t) => `<div class="task ${t.done ? "done" : ""}" data-task="${t.id}">
      <input type="checkbox" data-done="${t.id}" ${t.done ? "checked" : ""}>
      <div class="body"><div class="txt" data-edit="${t.id}" title="Tap to edit">${esc(t.text)}</div>
        <div class="sub">${dueTxt(t.due)}${t.sid ? `${t.due ? " · " : ""}🎓 <a href="#" data-goto="${esc(t.sid)}">${esc(t.stitle).slice(0, 60)}</a>` : ""}</div></div>
      <button class="del" data-edit="${t.id}" aria-label="Edit">✎</button><button class="del" data-del="${t.id}" aria-label="Delete">✕</button></div>`;
  const noteRow = (sid) => { const it = savedItems[sid] || {}; const title = it.title || "Scholarship"; const editing = editingNote === sid; return `<div class="card" data-notecard="${esc(sid)}" style="margin-bottom:10px">
      <h3 style="padding-right:0"><a href="#" data-goto="${esc(sid)}">${esc(title)}</a></h3>
      ${deadlineHtml(it.deadline)}
      ${editing
        ? `<textarea data-note="${esc(sid)}" aria-label="Note" style="width:100%;min-height:90px;margin-top:10px;padding:10px;border-radius:10px;border:1px solid #334155;background:#0f172a;color:inherit;font-size:14px;line-height:1.45;font-family:inherit;resize:vertical;box-sizing:border-box">${esc(notes[sid])}</textarea>
           <div class="row" style="justify-content:flex-end;gap:8px;margin-top:8px"><button class="ghost" data-ncancel="${esc(sid)}">Cancel</button><button data-nsave="${esc(sid)}">Save</button></div>`
        : `<div style="margin-top:10px;padding:10px 12px;border-left:3px solid var(--acc);background:#0f172a;border-radius:8px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word">${esc(notes[sid])}</div>
           <div class="row" style="justify-content:flex-end;gap:14px;margin-top:10px;font-size:13px">
             <a href="#" data-nedit="${esc(sid)}" style="color:#38bdf8;text-decoration:none">✎ Edit</a>
             <a href="#" data-goto="${esc(sid)}" style="color:#38bdf8;text-decoration:none">Open ↗</a>
             <a href="#" data-ndel="${esc(sid)}" style="color:var(--bad);text-decoration:none">✕ Delete</a></div>`}
    </div>`; };
  if (planView === "notes") {
    list.innerHTML = boostHtml() + seg + (noteIds.length ? noteIds.map(noteRow).join("") : '<div class="empty">No notes yet. Open any scholarship and tap "Add to opportunity note" – it will appear here.</div>');
  } else {
    list.innerHTML = boostHtml() + seg + `<div class="plan-add">
      <textarea id="tText" placeholder="What are you working on? e.g. Request transcript for DAAD application, write motivation letter…"></textarea>
      <div class="row"><input type="date" id="tDue" aria-label="Due date"><button id="tAdd">＋ Add</button></div></div>
    ${plan.length ? "" : '<div class="empty">Your plan is empty. Add tasks here, or open any scholarship and tap "Add to plan".</div>'}
    ${open.length ? '<div class="plan-h">To do</div>' + open.map(row).join("") : ""}
    ${done.length ? '<div class="plan-h">Done</div>' + done.map(row).join("") : ""}`;
    $("#tAdd").onclick = () => { addTask($("#tText").value, $("#tDue").value); renderPlan(); };
    $("#tText").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#tAdd").click(); } };
  }
  list.querySelectorAll("[data-pview]").forEach((b) => (b.onclick = () => { planView = b.dataset.pview; localStorage.setItem("planView", planView); renderPlan(); }));
  // notes: view → edit (Save/Cancel), delete, or jump to the scholarship
  list.querySelectorAll("[data-nedit]").forEach((el) => (el.onclick = (e) => { e.preventDefault(); editingNote = el.dataset.nedit; renderPlan(); const ta = list.querySelector("textarea[data-note]"); if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }));
  list.querySelectorAll("[data-ncancel]").forEach((el) => (el.onclick = () => { editingNote = null; renderPlan(); }));
  list.querySelectorAll("[data-nsave]").forEach((el) => (el.onclick = () => { const ta = list.querySelector(`textarea[data-note="${el.dataset.nsave}"]`); const v = ta ? ta.value.trim() : ""; if (v) notes[el.dataset.nsave] = v; else delete notes[el.dataset.nsave]; savePlan(); editingNote = null; renderPlan(); }));
  list.querySelectorAll("[data-ndel]").forEach((el) => (el.onclick = (e) => { e.preventDefault(); if (!confirm("Delete this note?")) return; delete notes[el.dataset.ndel]; savePlan(); editingNote = null; renderPlan(); }));
}
function openDetail(i) {
  maybeInterstitial();
  $("#detailBody").innerHTML = `<div class="detail">
    <h2>${esc(i.title)}</h2>${deadlineHtml(i.deadline)}${tags(i)}
    <p>${esc(i.summary)}</p>
    <div class="muted">Source: ${esc(i.source)}${i.tier === "official" ? " (provider's own website)" : ""}</div>
    <div class="muted" style="margin-top:6px;font-size:12px">ℹ️ Independent app – not affiliated with any government, university or provider. Verify all details and apply only on the official page below.</div>
    <div class="muted" style="word-break:break-all;margin-top:4px"><a href="${esc(i.url)}" data-open="${esc(i.url)}" style="color:#38bdf8">${esc(i.url)}</a></div>
    <div class="actions">
      <button class="ghost" id="dSave">${saved.has(i.id) ? "★ Saved" : "☆ Save"}</button>
      <button class="ghost" id="dShare">Share</button>
      <button id="dOpen">Apply / Details ↗</button>
    </div>
    <div id="dNoteWrap"></div></div>`;
  $("#detail").classList.remove("hidden");
  $("#detailBody").querySelectorAll("[data-open]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openUrl(a.dataset.open); }));
  $("#dOpen").onclick = () => openUrl(i.url);
  $("#dShare").onclick = () => shareItem(i);
  $("#dSave").onclick = () => { toggleSave(i); $("#dSave").textContent = saved.has(i.id) ? "★ Saved" : "☆ Save"; };
  const renderNoteBox = (editing) => {
    const cur = notes[i.id] || "";
    $("#dNoteWrap").innerHTML = editing
      ? `<div class="muted" style="margin-top:16px">📝 Opportunity note</div>
         <textarea class="note" id="dNote" placeholder="e.g. Need 2 reference letters, IELTS 6.5, submit before 15 March…">${esc(cur)}</textarea>
         <div class="row" style="justify-content:flex-end;gap:8px;margin-top:8px"><button class="ghost" id="dNoteCancel">Cancel</button><button id="dNoteSave">Save note</button></div>`
      : `${cur ? `<div class="muted" style="margin-top:16px">📝 Opportunity note</div><div style="margin-top:6px;padding:10px 12px;border-left:3px solid var(--acc);background:#0f172a;border-radius:8px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word">${esc(cur)}</div>` : ""}
         <div class="row" style="gap:8px;margin-top:14px"><button class="ghost" id="dPlan" style="flex:1">＋ Add to plan</button><button class="ghost" id="dNoteBtn" style="flex:1">${cur ? "✎ Edit opportunity note" : "📝 Add to opportunity note"}</button></div>
         <div class="muted" id="dNoteSaved" style="margin-top:6px;font-size:12px">${planCount(i.id)}</div>`;
    if (editing) {
      $("#dNote").focus();
      $("#dNoteCancel").onclick = () => renderNoteBox(false);
      $("#dNoteSave").onclick = () => { const v = $("#dNote").value.trim(); if (v) { notes[i.id] = v; if (!savedItems[i.id]) { savedItems[i.id] = i; saved.add(i.id); localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems)); $("#dSave").textContent = "★ Saved"; } } else delete notes[i.id]; savePlan(); renderNoteBox(false); $("#dNoteSaved").textContent = v ? "Note saved ✓ — see Plan → Opportunity notes" : planCount(i.id); };
    } else {
      $("#dNoteBtn").onclick = () => renderNoteBox(true);
      $("#dPlan").onclick = () => { const text = prompt("Task for “" + i.title.slice(0, 40) + "…”", "Apply: " + i.title.slice(0, 60)); if (text === null) return; addTask(text, i.deadline || "", i); $("#dNoteSaved").textContent = planCount(i.id) + " · added to Daily plan ✓"; };
    }
  };
  renderNoteBox(false);
}
function planCount(sid) { const n = plan.filter((t) => t.sid === sid && !t.done).length; return n ? `${n} open task${n > 1 ? "s" : ""} in plan` : ""; }
function toggleSave(i) {
  if (saved.has(i.id)) { saved.delete(i.id); delete savedItems[i.id]; } else { saved.add(i.id); savedItems[i.id] = i; }
  localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems));
  document.querySelectorAll(`[data-star="${i.id}"]`).forEach((b) => b.classList.toggle("on", saved.has(i.id)));
  if (saved.has(i.id)) scheduleDeadline(i); else cancelDeadline(i.id);
}

// ---------- events ----------
$("#list").addEventListener("click", (e) => {
  if (e.target.closest("[data-boost]")) { nextBoost(); return; }
  const dn = e.target.closest("[data-done]");
  if (dn) { const t = plan.find((x) => x.id === dn.dataset.done); if (t) { t.done = dn.checked; savePlan(); setTimeout(renderPlan, 250); } return; }
  const ed = e.target.closest("[data-edit]");
  if (ed) { const t = plan.find((x) => x.id === ed.dataset.edit); if (!t) return;
    const text = prompt("Edit task", t.text); if (text === null) return;
    const due = prompt("Due date (YYYY-MM-DD, leave empty for none)", t.due || ""); if (due === null) return;
    if (text.trim()) t.text = text.trim(); t.due = /^\d{4}-\d{2}-\d{2}$/.test(due.trim()) ? due.trim() : ""; savePlan(); renderPlan(); return; }
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
  state.newOnly = 0;
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
$("#alertsBtn").onclick = openNotifSheet;
$("#aCancel").onclick = () => $("#alerts").classList.add("hidden");
$("#nDaily").onchange = () => { $("#nRegionWrap").style.display = $("#nDaily").checked ? "" : "none"; };
$("#aSave").onclick = async () => {
  notif.daily = $("#nDaily").checked; notif.region = $("#nRegion").value; notif.deadlines = $("#nDeadlines").checked; saveNotif();
  if ((notif.daily || notif.deadlines) && isNative) {
    const ok = await askPermission();
    if (!ok) { alert("Notifications are blocked for ScholarHub. Allow them in your phone's Settings → Apps → ScholarHub → Notifications."); }
  }
  await applyDailyPush(); await rescheduleAllDeadlines();
  $("#alerts").classList.add("hidden");
  const on = [notif.daily && "new-scholarship updates" + (notif.region ? " for " + notif.region : ""), notif.deadlines && "deadline reminders"].filter(Boolean);
  if (on.length) alert("✅ You'll get " + on.join(" and ") + ".");
};
document.querySelectorAll(".sheet").forEach((s) => s.addEventListener("click", (e) => { if (e.target === s) s.classList.add("hidden"); }));

// ---------- admin (tap logo 7×, then PIN) ----------
let logoTaps = 0, logoTimer, adminPin = ""; // PIN is verified by the database policy, never stored in the app
document.querySelector(".brand").addEventListener("click", () => {
  logoTaps++; clearTimeout(logoTimer); logoTimer = setTimeout(() => (logoTaps = 0), 2500);
  if (logoTaps >= 7) { logoTaps = 0; const pin = prompt("Admin PIN"); if (pin && (!window.ADMIN_PIN || pin === window.ADMIN_PIN)) { adminPin = pin; openAdmin(); } }
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
    const r = await fetch(SB_URL + "/pull_requests", { method: "POST", headers: { ...SB_HEADERS, "Content-Type": "application/json" }, body: JSON.stringify({ url, save_as_source: $("#pSave").checked, deep: $("#pDeep").checked, ...(window.ADMIN_PIN ? {} : { pin: adminPin }) }) });
    if (r.status === 401 || r.status === 403) { alert("Wrong admin PIN."); $("#admin").classList.add("hidden"); return; }
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
    $("#nRegion").innerHTML += f.regions.map((r) => `<option>${esc(r)}</option>`).join("");
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
  // notifications: react to taps, keep subscriptions in sync
  function openFromNotif(data) {
    data = data || {};
    if (data.s) return openById(data.s);
    if (data.newOnly) { state.newOnly = 1; state.tab = "all"; state.q = ""; $("#q").value = ""; state.region = data.region || "";
      document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", (c.dataset.region || "") === state.region));
      document.querySelectorAll(".tabs [data-tab]").forEach((x) => x.classList.toggle("on", x.dataset.tab === "all")); load(); window.scrollTo(0, 0); }
  }
  if (FCM && FCM.addListener) {
    FCM.addListener("notificationActionPerformed", (ev) => openFromNotif(ev.notification && ev.notification.data));
    FCM.addListener("notificationReceived", (ev) => { const n = ev.notification || {}; if (n.title) { hideBoostToast(); const t = document.createElement("div"); t.className = "toast in"; t.id = "toast"; t.innerHTML = `<div class="toast-tag">🔔 ${esc(n.title)}</div><div class="toast-q">${esc(n.body || "")}</div><button class="toast-x">✕</button>`; document.body.appendChild(t); t.querySelector(".toast-x").onclick = hideBoostToast; t.onclick = () => { hideBoostToast(); openFromNotif(n.data); }; toastTimer = setTimeout(hideBoostToast, 10000); } });
    applyDailyPush();
  }
  if (LocalNotif && LocalNotif.addListener) LocalNotif.addListener("localNotificationActionPerformed", (ev) => openFromNotif(ev.notification && ev.notification.extra));
  // notifications are ON by default: ask Android's permission once, shortly after the first open
  if (isNative && !notif.asked) setTimeout(() => { askPermission().then(() => { applyDailyPush(); rescheduleAllDeadlines(); }); }, 3000);
  // motivation pop-ups: shortly after open, then every 5 minutes of use
  setTimeout(showBoostToast, 3000);
  setInterval(showBoostToast, 5 * 60 * 1000);
  // refresh when a new crawl has landed (twice a day) – check every 10 min while the app is open
  let lastRun = null;
  setInterval(async () => { try { const s = (await api("/app_stats?select=last_run")).items[0]; if (lastRun && s.last_run !== lastRun && state.tab === "all" && !state.q) load(); lastRun = s.last_run; } catch (e) {} }, 600000);
}
init();
