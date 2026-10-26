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
const PLAY_URL = "https://play.google.com/store/apps/details?id=com.scholarhub.app";
const FS = Cap && Cap.Plugins && Cap.Plugins.Filesystem; // used only to hand the card image to the share sheet
// Draw the scholarship card as an image (what the receiver sees in WhatsApp/Telegram), 1080px wide
// The card's own picture (or the institution logo) is drawn at the top, exactly like in the app.
const loadImg = (u) => new Promise((res) => { if (!u) return res(null); const im = new Image(); im.crossOrigin = "anonymous"; const t = setTimeout(() => res(null), 7000); im.onload = () => { clearTimeout(t); res(im); }; im.onerror = () => { clearTimeout(t); res(null); }; im.src = u; });
// Most picture hosts don't allow canvas use directly (CORS); the free images.weserv.nl mirror adds the needed header.
const loadImgAny = async (u) => (u ? (await loadImg(u)) || (await loadImg("https://images.weserv.nl/?url=" + encodeURIComponent(u.replace(/^https?:\/\//, "")) + "&w=1080&output=png")) : null);
async function cardImage(i) {
  const photo = await loadImgAny(i.image), logo = photo ? null : await loadImgAny(i.logo);
  try { return drawCard(i, photo, logo); } catch (e) { return drawCard(i, null, null); } // picture host without CORS → card without picture
}
function drawCard(i, photo, logo) {
  const sec = i._sec || ""; const isJob = sec === "jobs", isNews = sec === "news" || sec === "tech";
  const W = 1080, P = 56, c = document.createElement("canvas"), x = c.getContext("2d");
  const font = (px, w = 400) => (x.font = `${w} ${px}px system-ui, Roboto, "Noto Color Emoji", sans-serif`);
  const wrap = (txt, px, w, maxW, maxLines) => { font(px, w); const out = []; let line = ""; for (const word of String(txt || "").split(/\s+/)) { const t = line ? line + " " + word : word; if (x.measureText(t).width > maxW && line) { out.push(line); line = word; if (out.length === maxLines) break; } else line = t; } if (out.length < maxLines && line) out.push(line); if (out.length === maxLines && x.measureText(out[maxLines - 1]).width > maxW - 30) out[maxLines - 1] = out[maxLines - 1].replace(/\s?\S*$/, "") + "…"; return out; };
  const rr = (X, Y, w, h, r, fill, stroke) => { x.beginPath(); x.roundRect(X, Y, w, h, r); if (fill) { x.fillStyle = fill; x.fill(); } if (stroke) { x.strokeStyle = stroke; x.lineWidth = 2; x.stroke(); } };
  // measure first
  const titleLines = wrap(i.title, 50, 800, W - 2 * P, 4);
  const sumLines = wrap(i.summary, 32, 400, W - 2 * P, 4);
  const kindTxt = (KIND_PILL[i.kind] || [])[0];
  const tagList = sec ? [kindTxt, i.company, i.location, i.school].filter(Boolean) : [i.tier === "official" ? "🏛 official" : "", i.funding, ...(i.levels || "").split(", ").filter(Boolean).slice(0, 2), ...(i.countries || "").split(", ").filter(Boolean).slice(0, 2)].filter(Boolean);
  let days = null, dlTxt = isNews ? "" : isJob ? "🟢 Open — apply now" : "🟢 Open — apply now (no deadline stated)", dlCol = "#34d399";
  if (i.deadline) { days = Math.round((new Date(i.deadline) - new Date().setHours(0, 0, 0, 0)) / 864e5); dlTxt = `⏰ ${isJob ? "Closes" : "Deadline"} ${i.deadline} (${days < 0 ? "expired" : days === 0 ? "today!" : days === 1 ? "1 day left" : days + " days left"})`; dlCol = days < 0 ? "#f87171" : days <= 14 ? "#fbbf24" : "#34d399"; }
  const imgH = photo ? 460 : logo ? 240 : 0;
  const H = 150 + imgH + titleLines.length * 62 + 60 + sumLines.length * 44 + (tagList.length ? 80 : 20) + 60 + 232 + 150;
  c.width = W; c.height = H;
  x.fillStyle = "#0f172a"; x.fillRect(0, 0, W, H);
  // header
  font(40, 800); x.fillStyle = "#e2e8f0"; x.fillText("🎓 Scholar", P, 80); const sw = x.measureText("🎓 Scholar").width; x.fillStyle = "#38bdf8"; x.fillText("Hub", P + sw, 80);
  font(26, 700); x.fillStyle = "#34d399"; x.textAlign = "right"; x.fillText("● LIVE", W - P, 76); x.textAlign = "left";
  // card
  const cy = 120, cw = W - 2 * P + 40; rr(P - 20, cy, cw, H - cy - 130, 28, "#1e293b", "#273449");
  if (imgH) { // picture: full card width, cropped to fill; logo: large, centred on a light panel
    x.save(); x.beginPath(); x.roundRect(P - 20, cy, cw, imgH, [28, 28, 0, 0]); x.clip();
    if (photo) { const s = Math.max(cw / photo.naturalWidth, imgH / photo.naturalHeight), dw = photo.naturalWidth * s, dh = photo.naturalHeight * s; x.drawImage(photo, P - 20 + (cw - dw) / 2, cy + (imgH - dh) / 2, dw, dh); }
    else { x.fillStyle = "#f8fafc"; x.fillRect(P - 20, cy, cw, imgH); const s = Math.min((cw - 120) / logo.naturalWidth, (imgH - 60) / logo.naturalHeight), dw = logo.naturalWidth * s, dh = logo.naturalHeight * s; x.drawImage(logo, P - 20 + (cw - dw) / 2, cy + (imgH - dh) / 2, dw, dh); }
    x.restore();
  }
  let y = cy + imgH + 80; font(50, 800); x.fillStyle = "#f1f5f9"; for (const l of titleLines) { x.fillText(l, P + 10, y); y += 62; }
  if (dlTxt) { y += 6; font(30, 700); x.fillStyle = dlCol; x.fillText(dlTxt, P + 10, y); y += 54; } else y += 10;
  font(32, 400); x.fillStyle = "#94a3b8"; for (const l of sumLines) { x.fillText(l, P + 10, y); y += 44; }
  if (tagList.length) { y += 12; let tx = P + 10; font(26, 600); for (const t of tagList) { const w = x.measureText(t).width + 36; if (tx + w > W - P) break; rr(tx, y - 30, w, 46, 23, "#0f172a", "#334155"); x.fillStyle = t === i.funding ? "#34d399" : t.startsWith("🏛") ? "#c084fc" : "#94a3b8"; x.fillText(t, tx + 18, y + 2); tx += w + 12; } y += 60; }
  font(26, 400); x.fillStyle = "#64748b"; x.fillText(`via ${i.source || ""}`, P + 10, y + 10);
  // official link shown as plain text (proof of source; an image can't be tapped)
  font(24, 400); x.fillStyle = "#38bdf8"; let link = String(i.url || "").replace(/^https?:\/\//, ""); while (x.measureText(link).width > W - 2 * P - 20 && link.length > 10) link = link.slice(0, -2); if (link !== String(i.url || "").replace(/^https?:\/\//, "")) link += "…"; x.fillText("🔗 " + link, P + 10, y + 50);
  // action buttons, exactly like the detail screen (shows the tracking features)
  const btn = (X, Y, w, label, filled) => { rr(X, Y, w, 64, 16, filled ? "#38bdf8" : "#0f172a", filled ? null : "#334155"); font(26, 700); x.fillStyle = filled ? "#0f172a" : filled === false ? "#94a3b8" : "#94a3b8"; x.textAlign = "center"; x.fillText(label, X + w / 2, Y + 41); x.textAlign = "left"; };
  const bx = P + 10, bw = W - 2 * P - 20, g = 14; y += 90;
  const w3 = (bw - 2 * g) / 3; btn(bx, y, w3, "☆ Save", false); btn(bx + w3 + g, y, w3, "Share", false); btn(bx + 2 * (w3 + g), y, w3, isJob ? "Apply on site ↗" : isNews ? "Read on site ↗" : "Apply / Details ↗", true);
  y += 64 + g; const w2 = (bw - g) / 2; btn(bx, y, w2, "＋ Add to plan", false); btn(bx + w2 + g, y, w2, "📝 Add to opportunity note", false);
  // footer: Play Store call-to-action
  const fy = H - 100; rr(P, fy, W - 2 * P, 70, 18, "#38bdf8"); font(30, 800); x.fillStyle = "#0f172a"; x.textAlign = "center"; const lbl = "Get ScholarHub free on Google Play"; const lw = x.measureText(lbl).width; x.fillText(lbl, W / 2 + 22, fy + 46); x.textAlign = "left";
  // drawn down-arrow (not an emoji, so it shows on every device): points to the link under the picture
  const ax = W / 2 - lw / 2 - 20, ay = fy + 35; x.fillStyle = "#0f172a"; x.fillRect(ax - 6, ay - 20, 12, 24); x.beginPath(); x.moveTo(ax - 16, ay + 2); x.lineTo(ax + 16, ay + 2); x.lineTo(ax, ay + 20); x.closePath(); x.fill();
  return c.toDataURL("image/png");
}
function shareText(i) {
  const sec = i._sec || "";
  const who = i.school ? "\n" + i.school : i.company ? "\n" + i.company + (i.location ? " · " + i.location : "") : "";
  const when = i.deadline ? "\n⏰ " + (sec === "jobs" ? "Closes " : "Deadline: ") + i.deadline : "";
  const tail = sec ? "\n\n📲 Get ScholarHub free on Google Play – scholarships, school news, tech updates & jobs:\n" : "\n\n📲 Get ScholarHub free on Google Play – scholarships worldwide, updated twice a day:\n";
  return (sec === "news" ? "🏫 " : sec === "tech" ? "💻 " : sec === "jobs" ? "💼 " : "🎓 ") + i.title + who + when + tail + PLAY_URL;
}
let shareBusy = false;
async function shareItem(i) {
  if (shareBusy) return; shareBusy = true;
  const text = shareText(i), title = i.title, dialogTitle = "Share";
  try {
    let imgErr = "";
    // 1) native: draw the card, save it to the app cache and hand image + text to the share sheet (WhatsApp chats AND Status accept this)
    if (Share && Share.share && FS && FS.writeFile) {
      try {
        const data = (await cardImage(i)).split(",")[1];
        const f = await FS.writeFile({ path: "share-" + Date.now() + ".png", data, directory: "CACHE" });
        await Share.share({ title, text, files: [f.uri], dialogTitle }); return;
      } catch (e) { imgErr = (e && (e.message || e.code || String(e))) || "unknown"; if (/cancel/i.test(imgErr)) return; console.warn("image share failed", e); }
    }
    // 2) web: share the image file if the browser supports it
    try {
      if (navigator.share && navigator.canShare) {
        const blob = await (await fetch(await cardImage(i))).blob(); const file = new File([blob], "scholarhub.png", { type: "image/png" });
        if (navigator.canShare({ files: [file] })) { await navigator.share({ title, text, files: [file] }); return; }
      }
    } catch (e) { if (/abort/i.test(String(e))) return; }
    // 3) fallbacks: text only – and say why, so the problem can be reported
    if (imgErr) showToast("ℹ️ Shared as text", "Card picture could not be attached: " + imgErr.slice(0, 120));
    try { if (Share && Share.share) return await Share.share({ title, text, dialogTitle }); } catch (e) {}
    try { if (navigator.share) return await navigator.share({ title, text }); } catch (e) {}
    try { await navigator.clipboard.writeText(text); alert("Copied"); } catch (e) { prompt("Copy", text); }
  } finally { shareBusy = false; }
}
// Deep link: open a specific scholarship by id (from a shared link)
async function openById(id) {
  if (!id) return;
  let i = state.items.find((x) => x.id === id) || savedItems[id];
  if (!i) { try { i = (await api("/scholarships?select=id,title,url,source,summary,published,deadline,countries,regions,levels,fields,funding,tier,image,logo,org&id=eq." + encodeURIComponent(id))).items[0]; } catch (e) {} }
  if (i && i._sec) return openNewsDetail(i);
  if (i) openDetail(i); else alert("This scholarship is no longer listed.");
}
function idFromUrl(u) { try { return new URL(u).searchParams.get("s"); } catch (e) { return null; } }

const $ = (s) => document.querySelector(s);
const state = { tab: "all", region: "", newOnly: 0, q: "", level: "", field: "", funding: "", tier: "", country: "", added: 0, dlFrom: "", dlTo: "", expired: 0, offset: 0, items: [], total: 0, detailOpens: 0 };
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
    try { await FCM.createChannel({ id: "scholarhub_daily", name: "Daily picks", description: "Six short updates a day: scholarships, school news, jobs, tech and closing-soon deadlines", importance: 4 }); } catch (e) {}
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
  initNativeAds(); initAppOpen();
}
// ---- Native (in-feed) ads: real ad cards between scholarship cards, rendered by the Google SDK ----
let nativeFeed = null;
const AdMobJS = window.capacitorStripe || window.capacitorAdMob; // JS helpers bundled from the plugin (vendor/admob.js)
async function initNativeAds() {
  if (!isNative || !AdMobJS || !AdMobJS.NativeAdFeed || !(window.ADMOB.nativeId || window.ADMOB.testing)) return;
  try {
    nativeFeed = await AdMobJS.NativeAdFeed.create({
      feedId: "list", adId: window.ADMOB.nativeId, isTesting: window.ADMOB.testing, template: AdMobJS.NativeAdTemplate.Medium,
      style: { backgroundColor: "#ffffff", cornerRadius: 14, headlineColor: "#0f172a", bodyColor: "#334155", callToActionBackgroundColor: "#0284c7", callToActionTextColor: "#ffffff" },
    });
    // if an ad can't be filled, collapse its slot so there is no empty box in the list
    try { nativeFeed.addListener(AdMobJS.NativeAdPluginEvents.FailedToLoad, (ev) => { const el = document.querySelector(`capacitor-admob-native[slot-key="${ev.slotKey}"]`); if (el && el.parentElement) el.parentElement.style.display = "none"; }); } catch (e) {}
    // native ads float above the page – hide them whenever a sheet (detail/filters/alerts/admin) is open
    const sheets = document.querySelectorAll(".sheet");
    let paused = false;
    const sync = async () => { const open = [...sheets].some((x) => !x.classList.contains("hidden")); if (open && !paused) { paused = true; try { await nativeFeed.pause(); } catch (e) {} } else if (!open && paused) { paused = false; try { nativeFeed.resume(); } catch (e) {} } };
    new MutationObserver(sync).observe(document.body, { attributes: true, subtree: true, attributeFilter: ["class"] });
    document.addEventListener("visibilitychange", sync);
    if (state.items.length) { if (isNewsTab()) renderNews(); else render(); } // slots become live
  } catch (e) { console.warn("native ads", e); nativeFeed = null; }
}
const nativeSlot = (i) => (nativeFeed ? `<div class="card ad-slot"><capacitor-admob-native feed-id="list" slot-key="ad-${esc(i.id)}" style="display:block;height:300px"></capacitor-admob-native></div>` : "");
// ---- App Open ad: cold launch (behind a short branded loading screen) + when the user comes back to the app ----
function initAppOpen() {
  const load = AdMob && (AdMob.loadAppOpen || AdMob.prepareAppOpen); // plugin v8 = loadAppOpen
  if (!isNative || !AdMob || !load || !window.ADMOB.appOpenId || !CapApp) return;
  const opts = { adId: window.ADMOB.testing ? "ca-app-pub-3940256099942544/9257395921" : window.ADMOB.appOpenId };
  let ready = false, lastShown = 0;
  const prep = () => load.call(AdMob, opts).then(() => (ready = true)).catch(() => (ready = false));
  const show = async () => { ready = false; try { await AdMob.showAppOpen(); lastShown = Date.now(); } catch (e) {} prep(); };
  // cold launch: wait up to 4s for the ad behind the loading screen; if it isn't ready by then, start the app without it
  const boot = $("#boot");
  const hideBoot = () => { if (boot) { boot.classList.add("out"); setTimeout(() => boot.remove(), 350); } };
  let done = false;
  const finish = () => { if (!done) { done = true; hideBoot(); } };
  prep().then(() => { if (!done && ready) { done = true; show().finally(hideBoot); } else finish(); });
  setTimeout(finish, 4000);
  CapApp.addListener("appStateChange", async ({ isActive }) => {
    if (!isActive) return;
    if (ready && Date.now() - lastShown > 20 * 60000) await show(); else if (!ready) prep();
  });
}
// Interstitial: first scholarship opened / tab switch / 2nd+ "Load more" in this session, then at most one every M minutes (all triggers share the cap)
// (never on app launch itself – AdMob policy forbids interstitials on load)
let lastInterstitialAt = 0;
async function maybeInterstitial() {
  state.detailOpens++;
  if (!isNative || !AdMob) return;
  const gapMs = (window.ADMOB.interstitialMinGapMin || 10) * 60000;
  if (lastInterstitialAt && Date.now() - lastInterstitialAt < gapMs) return;
  try { await AdMob.showInterstitial(); lastInterstitialAt = Date.now(); await AdMob.prepareInterstitial({ adId: window.ADMOB.interstitialId, isTesting: window.ADMOB.testing }); } catch (e) {}
}

// ---------- data (Supabase PostgREST, read-only with the anon key) ----------
const today = () => new Date().toISOString().slice(0, 10);
const like = (v) => "ilike.*" + v.replace(/[%*,()]/g, " ").trim() + "*";
function buildQuery(offset) {
  const p = new URLSearchParams();
  p.set("select", "id,title,url,source,summary,published,deadline,countries,regions,levels,fields,funding,tier,image,logo,org");
  if (state.q) { const q = state.q.replace(/[%*,()."'\\:&|!<>]/g, " ").replace(/\s+/g, " ").trim(); if (q) p.set("and", `(or(title.wfts(english).${q},summary.wfts(english).${q}))`); }
  if (state.region) p.set("regions", like(state.region));
  if (state.newOnly) p.set("first_seen", "gte." + new Date(Date.now() - 36 * 3600e3).toISOString());
  if (state.level) p.set("levels", like(state.level));
  if (state.field) p.set("fields", like(state.field));
  if (state.funding) p.set("funding", like(state.funding));
  if (state.country) p.set("countries", like(state.country));
  if (state.tab === "official") p.set("tier", "eq.official"); else if (state.tier) p.set("tier", "eq." + state.tier);
  if (state.added) p.append("first_seen", "gte." + new Date(Date.now() - state.added * 864e5).toISOString());
  if (state.tab === "soon") { p.set("deadline", "gte." + today()); p.append("deadline", "lte." + new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10)); }
  else if (state.dlFrom || state.dlTo) { if (state.dlFrom) p.append("deadline", "gte." + state.dlFrom); if (state.dlTo) p.append("deadline", "lte." + state.dlTo); } // a date range only makes sense for dated listings
  else if (!state.expired) p.set("or", `(deadline.is.null,deadline.gte.${today()})`);
  // sort: cards with a real picture first (never in Closing soon), then dated & upcoming (soonest), then open-ended; newest first within
  p.set("order", (state.tab === "soon" ? "" : "has_img.desc,") + "deadline.asc.nullslast,published.desc");
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
  if (reset && state.tab === "all") loadAnnouncement();
  if (state.tab === "saved") { state.items = Object.values(savedItems); state.total = state.items.length; render(); return; }
  if (state.tab === "plan") { renderPlan(); return; }
  if (isNewsTab()) { await loadNews(seq); return; }
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
// ---------- School News (Nigerian universities) & Tech Updates ----------
// Standalone sections: they read ONLY the `school_news` / `tech_news` tables. The scholarship feeds never
// query these tables, so news can never appear under All / Closing soon / Official / regions / Saved.
const NEWS_TABS = {
  news: { table: "school_news", label: "School News · Nigeria", cols: "id,title,summary,url,source,tier,school_code,school,kind,published,image,logo" },
  tech: { table: "tech_news", label: "Tech Updates", cols: "id,title,summary,url,source,tier,published,image,logo" },
  jobs: { table: "jobs", label: "Jobs · Nigeria & remote", cols: "id,title,summary,url,source,tier,company,location,kind,deadline,published,image,logo", open: "Apply on site ↗" },
};
const isNewsTab = () => !!NEWS_TABS[state.tab];
const seenAt = {}; // when this tab was last opened (per session) -> items newer than that get a green dot
function newsQuery(offset) {
  const t = NEWS_TABS[state.tab]; const p = new URLSearchParams();
  p.set("select", t.cols);
  if (state.q) { const q = state.q.replace(/[%*,()."'\\:&|!<>]/g, " ").replace(/\s+/g, " ").trim(); if (q) p.set("or", `(title.wfts(english).${q},summary.wfts(english).${q}${state.tab === "news" ? `,school.ilike.*${q}*,school_code.ilike.*${q}*` : state.tab === "jobs" ? `,company.ilike.*${q}*,location.ilike.*${q}*` : ""})`); }
  if (state.tab === "jobs") { if (p.has("or")) { p.set("and", `(or${p.get("or")},or(deadline.is.null,deadline.gte.${today()}))`); p.delete("or"); } else p.set("or", `(deadline.is.null,deadline.gte.${today()})`); } // closed jobs disappear the day after the closing date
  p.set("order", "has_img.desc,published.desc"); p.set("limit", 30); p.set("offset", offset);
  return "/" + t.table + "?" + p.toString();
}
async function loadNews(seq) {
  if (seenAt[state.tab] === undefined) { seenAt[state.tab] = +localStorage.getItem("seen:" + state.tab) || 0; localStorage.setItem("seen:" + state.tab, String(Date.now())); }
  const key = "cache:" + newsQuery(0);
  try {
    const data = await api(newsQuery(state.offset), { Prefer: "count=exact" });
    if (seq !== loadSeq) return;
    state.items = state.items.concat(data.items); state.total = data.total; state.offset += data.items.length;
    localStorage.setItem(key, JSON.stringify({ items: state.items.slice(0, 60), total: data.total, t: Date.now() }));
    renderNews(); setOffline(false);
  } catch (e) {
    if (seq !== loadSeq) return;
    const c = JSON.parse(localStorage.getItem(key) || "null");
    if (c) { state.items = c.items; state.total = c.total; renderNews(); }
    else $("#list").innerHTML = '<div class="empty">Could not load updates. Check your internet connection and pull down to refresh.</div>';
    setOffline(true);
  }
}
const KIND_PILL = { admission: ["Admission", "adm"], scholarship: ["Scholarship", "sch"], fees: ["Fees", "fee"], calendar: ["Calendar", "cal"], notice: ["Notice", "urg"], convocation: ["Convocation", "cal"],
  graduate: ["Graduate", "adm"], internship: ["Internship", "cal"], ngo: ["NGO", "sch"], research: ["Research", "sch"], remote: ["Remote", "fee"], job: ["Job", "off"] };
const whoLine = (i) => i.school ? esc(i.school) + " · " : i.company ? esc(i.company) + (i.location ? " · " + esc(i.location) : "") + " · " : i.location ? esc(i.location) + " · " : "";
function ago(d) { const m = Math.max(0, Math.round((Date.now() - new Date(d)) / 60000)); if (m < 60) return m <= 1 ? "just now" : m + " min ago"; const h = Math.round(m / 60); if (h < 24) return h + " h ago"; const dd = Math.round(h / 24); if (dd < 7) return dd === 1 ? "yesterday" : dd + " days ago"; return new Date(d).toLocaleDateString([], { day: "numeric", month: "short" }); }
function spreadEmployers(items) { // in-place: when two neighbours share an employer, pull the next different employer forward
  const key = (i) => (i.company || i.source || "").toLowerCase().trim();
  for (let k = 1; k < items.length; k++) {
    if (key(items[k]) !== key(items[k - 1])) continue;
    const j = items.findIndex((x, idx) => idx > k && key(x) !== key(items[k - 1]) && (k + 1 >= items.length || key(x) !== key(items[k + 1])));
    if (j > k) { const [x] = items.splice(j, 1); items.splice(k, 0, x); }
  }
}
const SEC_LABEL = { news: "🏫 School News", tech: "💻 Tech", jobs: "💼 Job" };
const STAR_IMG = 'style="background:rgba(255,255,255,.88);border-radius:50%;width:34px;height:34px;line-height:26px;text-align:center;color:#475569;top:8px;right:8px"'; // over a picture: white circle like scholarship cards
function newsCardHtml(i, sec, isNew) { // one card for School News / Tech Updates / Jobs (also used inside Saved)
  const t = NEWS_TABS[sec] || NEWS_TABS.news;
  const img = hasMedia(i), pr = img ? 'style="right:50px"' : 'style="right:44px"'; // make room for the ★ at the top-right
  const pill = KIND_PILL[i.kind] ? `<span class="ntype ${KIND_PILL[i.kind][1]}" ${pr}>${KIND_PILL[i.kind][0]}</span>` : i.tier === "official" ? `<span class="ntype off" ${pr}>Official</span>` : "";
  const inSaved = state.tab === "saved";
  const star = `<button class="star ${saved.has(i.id) ? "on" : ""}" data-star="${esc(i.id)}" ${img ? STAR_IMG : ""}>★</button>`;
  return `<div class="ncard${pill ? " has-pill" : ""}${img ? " has-img" : ""}" data-id="${esc(i.id)}">${mediaHtml(i)}${pill}${star}
      <h3${img ? "" : pill ? ' style="padding-right:140px"' : ' style="padding-right:36px"'}>${isNew ? '<span class="ndot"></span>' : ""}${esc(i.title)}</h3>${sec === "jobs" ? (i.deadline ? deadlineHtml(i.deadline) : '<div class="dl ok">🟢 Open — apply now</div>') : ""}<p>${i.summary ? esc(i.summary) : "Tap to read the full update on " + esc(i.source) + "."}</p>
      <div class="nmeta"><span class="src">${inSaved ? SEC_LABEL[sec] + " · " : ""}${whoLine(i)}via ${esc(i.source)} · ${ago(i.published)}</span><span class="go">${t.open || "Read on site ↗"}</span></div>
    </div>`;
}
function renderNews() {
  const list = $("#list"), t = NEWS_TABS[state.tab];
  $("#stats").textContent = `${state.total.toLocaleString()} updates · ${t.label}${state.q ? " · “" + state.q + "”" : ""}`;
  if (!state.items.length) { list.innerHTML = `<div class="empty">${state.q ? "No updates match your search." : "No updates yet — pull down to refresh."}</div>`; $("#more").classList.add("hidden"); return; }
  const since = seenAt[state.tab] || 0;
  if (state.tab === "jobs") spreadEmployers(state.items); // never the same employer twice in a row
  list.innerHTML = state.items.map((i, idx) => `${idx > 0 && idx % 4 === 0 ? (isNative ? nativeSlot(i) : '<div class="ad-card">Advertisement</div>') : ""}${newsCardHtml(i, state.tab, new Date(i.published).getTime() > since)}`).join("");
  $("#more").classList.toggle("hidden", state.offset >= state.total);
}
function openNewsDetail(i) {
  const sec = i._sec || state.tab; // section the item belongs to (works from Saved too)
  maybeInterstitial(); // deliberate open = natural break point (same rule as scholarship cards)
  const pill = KIND_PILL[i.kind] ? `<span class="ntype ${KIND_PILL[i.kind][1]}" style="position:static;margin-left:8px">${KIND_PILL[i.kind][0]}</span>` : i.tier === "official" ? '<span class="ntype off" style="position:static;margin-left:8px">Official</span>' : "";
  const host = (() => { try { return new URL(i.url).hostname.replace(/^www\./, ""); } catch (e) { return ""; } })();
  $("#detailBody").innerHTML = `<div class="detail">${mediaHtml(i, true)}
    <h2>${esc(i.title)}</h2>
    <div class="muted" style="margin:4px 0 10px">${whoLine(i)}via ${esc(i.source)} · ${ago(i.published)}${pill}</div>
    ${sec === "jobs" ? (i.deadline ? deadlineHtml(i.deadline) : '<div class="dl ok">🟢 Open — apply now (no closing date stated)</div>') : ""}
    <p>${esc(i.summary || (sec === "jobs" ? "Open the listing for the full description and how to apply." : "Open the full article to read more."))}</p>
    <div class="muted" style="margin-top:6px;font-size:12px">${sec === "jobs" ? "ℹ️ Independent app – we list jobs from public job boards and never charge for applications. Beware of anyone asking for money to process a job. Apply only on the employer's or job board's page below." : `ℹ️ Summary collected automatically from ${esc(host || i.source)}. Read the full article on the source website.`}</div>
    <div class="muted" style="word-break:break-all;margin-top:4px"><a href="${esc(i.url)}" data-open="${esc(i.url)}" style="color:#0369a1">${esc(i.url)}</a></div>
    <div class="actions">
      <button class="ghost" id="nSave">${saved.has(i.id) ? "★ Saved" : "☆ Save"}</button>
      <button class="ghost" id="nShare">Share</button>
      <button id="nOpen">${NEWS_TABS[sec].open || "Read full article ↗"}</button>
    </div>
    <div id="dNoteWrap"></div></div>`;
  $("#detail").classList.remove("hidden");
  $("#detailBody").querySelectorAll("[data-open]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openUrl(a.dataset.open); }));
  $("#nOpen").onclick = () => openUrl(i.url);
  $("#nSave").onclick = () => { i._sec = sec; toggleSave(i); $("#nSave").textContent = saved.has(i.id) ? "★ Saved" : "☆ Save"; };
  i._sec = sec; attachNoteBox(i, "#nSave");
  $("#nShare").onclick = () => shareItem(i);
}
function setMode() {
  document.body.classList.toggle("mode-news", isNewsTab());
  document.querySelectorAll(".hubbtn").forEach((b) => b.classList.toggle("on", (state.tab === "news" && b.id === "newsBtn") || (state.tab === "tech" && b.id === "techBtn") || (state.tab === "jobs" && b.id === "jobsBtn") || (!isNewsTab() && b.id === "schBtn")));
  if (state.tab === "jobs") document.querySelectorAll(".tabs [data-tab]").forEach((x) => x.classList.remove("on")); // Jobs has no bottom tab
  const q = $("#q"); if (q) q.placeholder = state.tab === "news" ? "Search school news, e.g. UNILAG admission list…" : state.tab === "tech" ? "Search tech updates, e.g. AI, Starlink…" : state.tab === "jobs" ? "Search jobs, e.g. graduate trainee, Lagos, remote…" : "Search scholarships, e.g. PhD Canada…";
}

// ---------- Announcement (admin-managed: Supabase table `announcements`; RLS only exposes active rows in their date window) ----------
async function loadAnnouncement() {
  const box = $("#ann"); if (!box) return;
  try {
    const r = await api("/announcements?select=id,title,body,link_url,link_text,color&order=created_at.desc&limit=4");
    if (!r.items.length) { box.classList.add("hidden"); box.innerHTML = ""; annStop(); localStorage.removeItem("ann"); return; }
    localStorage.setItem("ann", JSON.stringify(r.items)); showAnnouncement(r.items);
  } catch (e) { const c = JSON.parse(localStorage.getItem("ann") || "null"); if (c) showAnnouncement(Array.isArray(c) ? c : [c]); } // offline: keep the last ones seen
}
// Up to 4 announcements in one banner: auto-advance every 5 s (pauses while touched / in background), swipe to move, dots show position.
let annIdx = 0, annTimer = null, annN = 0;
function annStop() { clearTimeout(annTimer); annTimer = null; const b = $("#ann .ann-bar"); if (b) b.classList.remove("run"); }
function annGo(k) {
  const track = $("#ann .ann-track"); if (!track || !annN) return;
  annIdx = ((k % annN) + annN) % annN; track.style.transition = ""; track.style.transform = `translateX(-${annIdx * 100}%)`;
  document.querySelectorAll("#ann .ann-dots i").forEach((d, j) => d.classList.toggle("on", j === annIdx));
  annStop(); if (annN < 2 || document.hidden) return;
  const b = $("#ann .ann-bar"); if (b) { void b.offsetWidth; b.classList.add("run"); }
  annTimer = setTimeout(() => annGo(annIdx + 1), 5000);
}
// Colour per announcement, set from Supabase (`color` column): a preset name (red, blue, green, purple, orange, pink, teal, dark) or any hex like #0f766e. Empty = red.
const ANN_COLORS = { red: ["#b91c1c", "#dc2626"], blue: ["#1d4ed8", "#2563eb"], green: ["#047857", "#059669"], purple: ["#6d28d9", "#7c3aed"], orange: ["#c2410c", "#ea580c"], pink: ["#be185d", "#db2777"], teal: ["#0f766e", "#0d9488"], dark: ["#0f172a", "#334155"] };
function annStyle(c) { c = String(c || "").trim().toLowerCase(); const p = ANN_COLORS[c] || (/^#[0-9a-f]{6}$/.test(c) ? [c, c] : ANN_COLORS.red); return `background:linear-gradient(135deg,${p[0]},${p[1]})`; }
function showAnnouncement(list) {
  const box = $("#ann"); annN = list.length; annIdx = 0;
  const slide = (a, k) => { const link = a.link_url && /^https?:\/\//i.test(a.link_url) ? `<div><button data-ann-link="${esc(a.link_url)}">${esc(a.link_text || "Open link →")}</button></div>` : "";
    return `<div class="ann-slide" style="${annStyle(a.color)}"><div class="ann-tag"><span>📣 Announcement</span>${annN > 1 ? `<small>${k + 1}/${annN}</small>` : ""}</div>${a.title ? `<b>${esc(a.title)}</b>` : ""}${a.body ? `<p>${esc(a.body)}</p>` : ""}${link}</div>`; };
  box.innerHTML = `<div class="ann-track">${list.map(slide).join("")}</div>${annN > 1 ? `<div class="ann-dots">${list.map((_, k) => `<i class="${k ? "" : "on"}"></i>`).join("")}</div><div class="ann-bar"></div>` : ""}`;
  box.classList.toggle("multi", annN > 1); box.classList.remove("hidden");
  annGo(0);
}
(() => { // swipe handling for the announcement banner (set up once)
  const box = document.getElementById("ann"); if (!box) return;
  let sx = 0, dx = 0, on = false;
  box.addEventListener("touchstart", (e) => { if (annN < 2) return; sx = e.touches[0].clientX; dx = 0; on = true; annStop(); const t = $("#ann .ann-track"); if (t) t.style.transition = "none"; }, { passive: true });
  box.addEventListener("touchmove", (e) => { if (!on) return; dx = e.touches[0].clientX - sx; const t = $("#ann .ann-track"); if (t) t.style.transform = `translateX(calc(-${annIdx * 100}% + ${dx}px))`; }, { passive: true });
  box.addEventListener("touchend", () => { if (!on) return; on = false; annGo(annIdx + (Math.abs(dx) > 40 ? (dx < 0 ? 1 : -1) : 0)); }, { passive: true });
  document.addEventListener("visibilitychange", () => { if (document.hidden) annStop(); else if (annN > 1 && !$("#ann").classList.contains("hidden")) annGo(annIdx); });
})();
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
function showToast(tag, msg, ms = 7000) {
  hideBoostToast();
  const t = document.createElement("div"); t.className = "toast"; t.id = "toast";
  t.innerHTML = `<div class="toast-tag">${esc(tag)}</div><div class="toast-q" style="font-style:normal">${esc(msg)}</div><button class="toast-x" aria-label="Dismiss">✕</button>`;
  document.body.appendChild(t); requestAnimationFrame(() => t.classList.add("in"));
  t.querySelector(".toast-x").onclick = hideBoostToast; toastTimer = setTimeout(hideBoostToast, ms);
}
function hideBoostToast() { clearTimeout(toastTimer); const t = $("#toast"); if (t) { t.classList.remove("in"); setTimeout(() => t.remove(), 300); } }

// ---------- render ----------
const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function deadlineHtml(d) {
  if (!d) return '<div class="dl ok">🟢 Open — apply now (no deadline stated)</div>';
  const days = Math.round((new Date(d) - new Date().setHours(0, 0, 0, 0)) / 864e5);
  const cls = days < 0 ? "past" : days <= 14 ? "soon" : "ok";
  const txt = days < 0 ? "expired" : days === 0 ? "today!" : days === 1 ? "1 day left" : days + " days left";
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
// ---------- pictures: real picture -> real institution / publisher logo -> no image area at all (never a fake tile) ----------
const mediaHtml = (i, hero) => {
  if (i.image) return `<div class="nimg${hero ? " hero" : ""}"><img src="${esc(i.image)}" alt="" loading="lazy" decoding="async" onerror="${i.logo ? `this.parentNode.innerHTML=logoHtml('${esc(i.logo).replace(/'/g, "%27")}')` : "var c=this.closest('.card,.ncard');if(c)c.classList.remove('has-img');this.parentNode.remove()"}"></div>`;
  if (i.logo) return `<div class="nimg${hero ? " hero" : ""}">${logoHtml(i.logo)}</div>`;
  return "";
};
const logoHtml = (u) => `<div class="nlogo"><img src="${esc(u)}" alt="" loading="lazy" decoding="async" onload="if(this.naturalHeight>this.naturalWidth*0.6)this.classList.add('tall')" onerror="var c=this.closest('.card,.ncard');if(c)c.classList.remove('has-img');this.closest('.nimg').remove()"></div>`;
const hasMedia = (i) => !!(i.image || i.logo);
function render() {
  const list = $("#list");
  if (!state.items.length) { list.innerHTML = `<div class="empty">${state.tab === "saved" ? "Nothing saved yet — tap ★ on any scholarship, job or update to keep it here." : "No opportunities match. Try clearing filters."}</div>`; $("#more").classList.add("hidden"); return; }
  list.innerHTML = state.items.map((i, idx) => `
    ${idx > 0 && idx % 4 === 0 ? (isNative ? nativeSlot(i) : '<div class="ad-card">Advertisement</div>') : ""}
    ${i._sec ? newsCardHtml(i, i._sec, false) : `<div class="card${hasMedia(i) ? " has-img" : ""}" data-id="${esc(i.id)}">
      ${mediaHtml(i)}
      <button class="star ${saved.has(i.id) ? "on" : ""}" data-star="${esc(i.id)}">★</button>
      <h3>${esc(i.title)}</h3>
      ${deadlineHtml(i.deadline)}
      <p>${esc(i.summary)}</p>
      ${tags(i)}
      <div class="meta">via ${esc(i.source)} · ${esc((i.published || "").slice(0, 10))}</div>
    </div>`}`).join("");
  $("#more").classList.toggle("hidden", state.tab === "saved" || state.offset >= state.total);
  $("#stats").textContent = `${state.total.toLocaleString()} ${state.newOnly ? "new " : ""}opportunities${state.region ? " · " + state.region : ""}${state.added ? ` · added in last ${state.added === 1 ? "24h" : state.added + " days"}` : ""}${state.dlFrom || state.dlTo ? ` · deadline ${state.dlFrom || "…"} → ${state.dlTo || "…"}` : ""}${state.newOnly ? " · tap ↻ for all" : ""}`;
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
        <div class="sub">${dueTxt(t.due)}${t.sid ? `${t.due ? " · " : ""}${savedItems[t.sid] && savedItems[t.sid]._sec ? (SEC_LABEL[savedItems[t.sid]._sec] || "").slice(0, 2) : "🎓"} <a href="#" data-goto="${esc(t.sid)}">${esc(t.stitle).slice(0, 60)}</a>` : ""}</div></div>
      <button class="del" data-edit="${t.id}" aria-label="Edit">✎</button><button class="del" data-del="${t.id}" aria-label="Delete">✕</button></div>`;
  const noteRow = (sid) => { const it = savedItems[sid] || {}; const title = it.title || "Scholarship"; const editing = editingNote === sid; const dl = it._sec && !it.deadline ? "" : deadlineHtml(it.deadline); return `<div class="card" data-notecard="${esc(sid)}" style="margin-bottom:10px">
      <h3 style="padding-right:0"><a href="#" data-goto="${esc(sid)}">${esc(title)}</a></h3>
      ${it._sec ? `<div class="muted" style="font-size:12px;margin:-2px 0 6px">${SEC_LABEL[it._sec] || ""}</div>` : ""}${dl}
      ${editing
        ? `<textarea data-note="${esc(sid)}" aria-label="Note" style="width:100%;min-height:90px;margin-top:10px;padding:10px;border-radius:10px;border:1px solid #cbd5e1;background:#f1f5f9;color:inherit;font-size:14px;line-height:1.45;font-family:inherit;resize:vertical;box-sizing:border-box">${esc(notes[sid])}</textarea>
           <div class="row" style="justify-content:flex-end;gap:8px;margin-top:8px"><button class="ghost" data-ncancel="${esc(sid)}">Cancel</button><button data-nsave="${esc(sid)}">Save</button></div>`
        : `<div style="margin-top:10px;padding:10px 12px;border-left:3px solid var(--acc);background:#f1f5f9;border-radius:8px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word">${esc(notes[sid])}</div>
           <div class="row" style="justify-content:flex-end;gap:14px;margin-top:10px;font-size:13px">
             <a href="#" data-nedit="${esc(sid)}" style="color:#0369a1;text-decoration:none">✎ Edit</a>
             <a href="#" data-goto="${esc(sid)}" style="color:#0369a1;text-decoration:none">Open ↗</a>
             <a href="#" data-ndel="${esc(sid)}" style="color:var(--bad);text-decoration:none">✕ Delete</a></div>`}
    </div>`; };
  if (planView === "notes") {
    list.innerHTML = boostHtml() + seg + (noteIds.length ? noteIds.map(noteRow).join("") : '<div class="empty">No notes yet. Open any scholarship, job or update and tap "Add to opportunity note" – it will appear here.</div>');
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
  $("#detailBody").innerHTML = `<div class="detail">${mediaHtml(i, true)}
    <h2>${esc(i.title)}</h2>${deadlineHtml(i.deadline)}${tags(i)}
    <p>${esc(i.summary)}</p>
    <div class="muted">Source: ${esc(i.source)}${i.tier === "official" ? " (provider's own website)" : ""}</div>
    <div class="muted" style="margin-top:6px;font-size:12px">ℹ️ Independent app – not affiliated with any government, university or provider. Verify all details and apply only on the official page below.</div>
    <div class="muted" style="word-break:break-all;margin-top:4px"><a href="${esc(i.url)}" data-open="${esc(i.url)}" style="color:#0369a1">${esc(i.url)}</a></div>
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
  attachNoteBox(i, "#dSave");
}
function attachNoteBox(i, saveSel) { // "Add to plan" + personal note, shared by scholarship and job/news sheets
  const renderNoteBox = (editing) => {
    const cur = notes[i.id] || "";
    $("#dNoteWrap").innerHTML = editing
      ? `<div class="muted" style="margin-top:16px">📝 Opportunity note</div>
         <textarea class="note" id="dNote" placeholder="e.g. Need 2 reference letters, IELTS 6.5, submit before 15 March…">${esc(cur)}</textarea>
         <div class="row" style="justify-content:flex-end;gap:8px;margin-top:8px"><button class="ghost" id="dNoteCancel">Cancel</button><button id="dNoteSave">Save note</button></div>`
      : `${cur ? `<div class="muted" style="margin-top:16px">📝 Opportunity note</div><div style="margin-top:6px;padding:10px 12px;border-left:3px solid var(--acc);background:#f1f5f9;border-radius:8px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word">${esc(cur)}</div>` : ""}
         <div class="row" style="gap:8px;margin-top:14px"><button class="ghost" id="dPlan" style="flex:1">＋ Add to plan</button><button class="ghost" id="dNoteBtn" style="flex:1">${cur ? "✎ Edit opportunity note" : "📝 Add to opportunity note"}</button></div>
         <div class="muted" id="dNoteSaved" style="margin-top:6px;font-size:12px">${planCount(i.id)}</div>`;
    if (editing) {
      $("#dNote").focus();
      $("#dNoteCancel").onclick = () => renderNoteBox(false);
      $("#dNoteSave").onclick = () => { const v = $("#dNote").value.trim(); if (v) { notes[i.id] = v; if (!savedItems[i.id]) { if (!i._sec && NEWS_TABS[state.tab]) i._sec = state.tab; savedItems[i.id] = i; saved.add(i.id); localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems)); $(saveSel).textContent = "★ Saved"; } } else delete notes[i.id]; savePlan(); renderNoteBox(false); $("#dNoteSaved").textContent = v ? "Note saved ✓ — see Plan → Opportunity notes" : planCount(i.id); };
    } else {
      $("#dNoteBtn").onclick = () => renderNoteBox(true);
      $("#dPlan").onclick = () => { const text = prompt("Task for “" + i.title.slice(0, 40) + "…”", "Apply: " + i.title.slice(0, 60)); if (text === null) return; addTask(text, i.deadline || "", i); $("#dNoteSaved").textContent = planCount(i.id) + " · added to Daily plan ✓"; };
    }
  };
  renderNoteBox(false);
}
function planCount(sid) { const n = plan.filter((t) => t.sid === sid && !t.done).length; return n ? `${n} open task${n > 1 ? "s" : ""} in plan` : ""; }
function toggleSave(i) {
  if (!i._sec && NEWS_TABS[state.tab]) i._sec = state.tab; // news / tech / jobs item → remember its section for the Saved tab
  if (saved.has(i.id)) { saved.delete(i.id); delete savedItems[i.id]; } else { saved.add(i.id); savedItems[i.id] = i; }
  localStorage.setItem("saved", JSON.stringify([...saved])); localStorage.setItem("savedItems", JSON.stringify(savedItems));
  document.querySelectorAll(`[data-star="${i.id}"]`).forEach((b) => b.classList.toggle("on", saved.has(i.id)));
  if (saved.has(i.id)) scheduleDeadline(i); else cancelDeadline(i.id);
}

// ---------- events ----------
$("#ann").addEventListener("click", (e) => { const b = e.target.closest("[data-ann-link]"); if (b) openUrl(b.dataset.annLink); });
$("#list").addEventListener("click", (e) => {
  if (e.target.closest("[data-boost]")) { nextBoost(); return; }
  const star0 = e.target.closest("[data-star]");
  if (star0) { const i = state.items.find((x) => x.id === star0.dataset.star); if (i) toggleSave(i); return; }
  const nc = e.target.closest(".ncard"); if (nc) { const i = state.items.find((x) => x.id === nc.dataset.id); if (i) openNewsDetail(i); return; }
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
let loadMoreTaps = 0;
$("#more").onclick = async () => { await load(false); if (++loadMoreTaps > 1) maybeInterstitial(); }; // natural break point: after the next page has loaded (never on the first "Load more")
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
document.querySelectorAll(".tabs [data-tab]").forEach((b) => (b.onclick = () => { document.querySelectorAll(".tabs [data-tab]").forEach((x) => x.classList.remove("on")); b.classList.add("on"); const wasNews = isNewsTab(); state.tab = b.dataset.tab; if (wasNews !== isNewsTab() && state.q) { state.q = ""; $("#q").value = ""; } setMode(); load(); window.scrollTo(0, 0); maybeInterstitial(); })); // tab switch = natural break point
if ($("#schBtn")) $("#schBtn").onclick = () => document.querySelector('.tabs [data-tab="all"]').click();
if ($("#newsBtn")) $("#newsBtn").onclick = () => document.querySelector('.tabs [data-tab="news"]').click();
if ($("#techBtn")) $("#techBtn").onclick = () => document.querySelector('.tabs [data-tab="tech"]').click();
if ($("#jobsBtn")) $("#jobsBtn").onclick = () => { if (state.tab === "jobs") return; if (state.q) { state.q = ""; $("#q").value = ""; } state.tab = "jobs"; setMode(); load(); window.scrollTo(0, 0); maybeInterstitial(); };
$("#filtersBtn").onclick = () => $("#sheet").classList.remove("hidden");
$("#apply").onclick = () => { state.level = $("#fLevel").value; state.funding = $("#fFunding").value; state.tier = $("#fTier").value; state.country = $("#fCountry").value.trim(); state.added = +($("#fAdded").value || 0); state.dlFrom = $("#fFrom").value; state.dlTo = $("#fTo").value; state.expired = $("#fExpired").checked ? 1 : 0; $("#sheet").classList.add("hidden"); load(); };
$("#clear").onclick = () => { ["fLevel", "fFunding", "fTier", "fAdded", "fFrom", "fTo"].forEach((id) => ($("#" + id).value = "")); $("#fCountry").value = ""; $("#fExpired").checked = false; };
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
  const on = [notif.daily && "daily picks" + (notif.region ? " for " + notif.region : ""), notif.deadlines && "deadline reminders"].filter(Boolean);
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
  const boot = $("#boot");
  if (boot && (!isNative || !AdMob || !(window.ADMOB && window.ADMOB.appOpenId))) boot.remove(); // no app-open ad possible → no loading screen
  setTimeout(() => { const b = $("#boot"); if (b) b.remove(); }, 7000); // hard fallback: never leave the loading screen stuck
  initAds();
  try {
    const f = FILTERS;
    const fill = (id, arr) => (document.getElementById(id).innerHTML += arr.map((v) => `<option>${esc(v)}</option>`).join(""));
    fill("fLevel", f.levels); fill("fFunding", f.funding);
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
  // notifications: react to taps, keep subscriptions in sync, offer once on the 2nd open
  async function openNewsById(ref) {
    const [table, id] = String(ref).split(":"); const tab = table === "tech_news" ? "tech" : table === "jobs" ? "jobs" : "news";
    if (!NEWS_TABS[tab] || !id) return;
    try {
      const r = await api("/" + table + "?select=" + NEWS_TABS[tab].cols + "&id=eq." + encodeURIComponent(id));
      const it = r.items[0]; if (!it) return;
      state.tab = tab; document.querySelectorAll(".tabs [data-tab]").forEach((x) => x.classList.toggle("on", x.dataset.tab === tab)); setMode(); load();
      openNewsDetail(it);
    } catch (e) {}
  }
  function openFromNotif(data) {
    data = data || {};
    if (data.s) return openById(data.s);
    if (data.n) return openNewsById(data.n);
    if (data.newOnly) { state.newOnly = 1; state.tab = "all"; state.q = ""; $("#q").value = ""; state.region = data.region || "";
      document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", (c.dataset.region || "") === state.region));
      document.querySelectorAll(".tabs [data-tab]").forEach((x) => x.classList.toggle("on", x.dataset.tab === "all")); setMode(); load(); window.scrollTo(0, 0); }
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
