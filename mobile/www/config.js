// ====== ScholarHub mobile configuration ======

// 1) SUPABASE. From your Supabase project: Settings → API.
//    Use the "anon public" key here (it is safe to ship in the app; Row Level Security limits it to read-only).
//    NEVER put the service_role key in the app.
window.SUPABASE_URL = "https://bmoicxrcyxbssgkfzahu.supabase.co";
window.SUPABASE_ANON_KEY = "sb_publishable_qI60qVcNwEW6DUN4Bdztjw_lJaeuijY";

// 2) ADMOB. Your real ad unit IDs from https://apps.admob.com
//    (The AdMob *App ID* goes in setup-android.sh / the ADMOB_APP_ID GitHub secret, not here.)
window.ADMOB = {
  bannerId: "ca-app-pub-5520099370989885/9429046228",        // banner ad unit
  interstitialId: "ca-app-pub-5520099370989885/3405643484",  // interstitial ad unit
  testing: false,
  nativeId: "ca-app-pub-5520099370989885/2573475753",        // native (in-feed) ad unit; empty = off
  appOpenId: "ca-app-pub-5520099370989885/7829582579",       // app open ad unit (on return to foreground); empty = off
  interstitialMinGapMin: 10,  // full-screen ad on the first scholarship opened each session, then at most one every 10 minutes
};

// 3) Links shown in the app
window.SHARE_URL = "https://faruk-olasco.github.io/ScholarHub";
window.PRIVACY_URL = "https://faruk-olasco.github.io/ScholarHub/privacy.html";

// 4) ADMIN. Tap the ScholarHub logo 7 times and enter this PIN to open the admin screen
//    (pull scholarships from a link, see crawl status). Change it!
window.ADMIN_PIN = "2468";
