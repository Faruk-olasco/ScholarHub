# ScholarHub Android app (APK) with Google AdMob — step-by-step

The app in this folder is a Capacitor Android app. It shows the same live data as the website by calling your
server's API, and it displays AdMob banner + interstitial ads. **Set up Supabase + the crawler first** (see `../SETUP.md`) — the app reads scholarships from Supabase.

---

## Part 1 — Costs (one-time / recurring)
| Item | Cost |
|---|---|
| Building the APK | **Free** (GitHub Actions builds it in the cloud) |
| AdMob account | **Free** |
| Google Play developer account (to publish on the Play Store) | **$25 one-time** |
| Supabase database + GitHub crawler | **Free** |

You can also share the APK file directly (WhatsApp, website download) without the Play Store — but AdMob only
pays out reliably for apps listed on a store, so plan to publish on Google Play.

---

## Part 2 — Configure
1. Open `www/config.js` and set `SUPABASE_URL` and `SUPABASE_ANON_KEY` (Supabase → Settings → API).
2. Leave the AdMob **test IDs** in place for now (they show "Test Ad" banners; using real IDs while testing can get
   your AdMob account banned).

## Part 3 — Build the APK (no Android Studio needed)
1. Put the whole `scholarhub` folder in a GitHub repository (the workflow file is at `.github/workflows/android.yml`).
2. On GitHub: **Actions → "Build Android APK" → Run workflow**.
3. After ~6–8 minutes, open the run → **Artifacts → scholarhub-android** → download. Inside is
   `app-debug.apk`. Copy it to your phone, tap it, allow "install from unknown sources". Done — that is your app.

## Part 4 — Set up AdMob (real ads)
1. Go to https://apps.admob.com → sign in with Google → **Apps → Add app → Android → "No, it's not listed yet"** →
   name it ScholarHub. Copy the **App ID** (looks like `ca-app-pub-1234567890123456~1234567890`).
2. In that app, **Ad units → Add ad unit**: create one **Banner** and one **Interstitial**. Copy both unit IDs
   (look like `ca-app-pub-…/…`).
3. Put the two unit IDs into `www/config.js` and set `testing: false`.
4. Put the App ID in GitHub: repo **Settings → Secrets and variables → Actions → New secret**
   `ADMOB_APP_ID` = your App ID.
5. Add `app-ads.txt`: AdMob asks you to host a file at `https://<your-github-pages-site>/app-ads.txt`.
   Edit `docs/app-ads.txt` in the repo and paste the line AdMob shows you (e.g.
   `google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0`). Set that Pages URL as the app's website in Play Console.
6. **Payments**: AdMob → Payments → add your address and bank details. Nigeria is supported (wire transfer).
   Payout threshold is $100.

## Part 5 — Sign & publish on Google Play
1. Create a signing key once (keep it forever — losing it means you can never update the app):
       keytool -genkey -v -keystore scholarhub.keystore -alias scholarhub -keyalg RSA -keysize 2048 -validity 10000
2. Convert to text and add as GitHub secrets: `KEYSTORE_BASE64` (`base64 -w0 scholarhub.keystore`),
   `KEYSTORE_PASSWORD`, `KEY_ALIAS` (=scholarhub), `KEY_PASSWORD`.
3. Re-run the workflow → the artifact now also contains `app-release.aab` (this is what Google Play wants).
4. https://play.google.com/console → pay $25 → **Create app** → upload the `.aab` under Production (or Internal
   testing first). Fill in store listing (icon in `resources/icon.png`, screenshots from your phone), content
   rating questionnaire, privacy policy URL (your GitHub Pages `privacy.html`), and the **Data safety** form
   (declare: "Device or other IDs – collected – for advertising" because of AdMob).
5. Review takes 1–7 days. After approval, go back to AdMob → your app → link it to the Play listing.

## Part 6 — Updating the app later
Change files in `www/`, push to GitHub → workflow builds a new APK/AAB → upload the new `.aab` in Play Console
with a higher `versionCode`. (Crawler changes — new sources, better extraction — need **no** app update; the app just reads Supabase.)

---

## Policy notes (to keep your AdMob account safe)
- Never click your own ads; don't ask users to click ads.
- Don't place ads where they can be tapped by accident (the app shows one banner at the bottom and one
  interstitial every 6 detail opens — this is within policy).
- The app requests GDPR consent via Google UMP automatically (required for EU users).
- Keep the privacy policy page live and mention AdMob/advertising IDs.

## Local build (optional, if you have Android Studio)
    cd mobile && npm install && npx cap add android && ./setup-android.sh && npx cap sync android && npx cap open android
