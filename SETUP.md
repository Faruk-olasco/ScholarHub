# ScholarHub setup — GitHub + Supabase only (no money, no card)

Total time ≈ 40 minutes. Everything below is free.

## 1. GitHub (holds the code, runs the crawler, builds the APK)
1. Create an account at https://github.com/signup.
2. **+ → New repository** → name `scholarhub` → **Public** (public repos get unlimited free Actions minutes) → Create.
3. **Add file → Upload files** → drag in everything inside this `scholarhub` folder → **Commit changes**.
   Check that `.github/workflows/crawl.yml` and `android.yml` were uploaded (hidden folder on some PCs).

## 2. Supabase (free database the app reads from)
1. https://supabase.com → **Start your project** → sign in with GitHub → **New project**
   (name: scholarhub, choose a strong DB password – save it, region: closest e.g. Frankfurt/London).
2. Wait ~2 min. Left menu → **SQL Editor → New query** → paste the whole content of `supabase/schema.sql` → **Run**.
   You should see "Success".
3. Left menu → **Project Settings → API**. Copy three things:
   - **Project URL** (https://xxxx.supabase.co)
   - **anon public** key  (safe – goes in the app)
   - **service_role** key (secret – goes ONLY in GitHub secrets)

## 3. Connect the crawler
1. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `SUPABASE_URL` = Project URL
   - `SUPABASE_SERVICE_KEY` = service_role key
2. GitHub → **Actions** tab → enable workflows if asked → **Crawl scholarships → Run workflow**.
3. Watch it run (~5–10 min). In Supabase → **Table Editor → scholarships** you'll see rows appear.
   From now on it runs automatically at **07:00 and 19:00 Lagos time** every day.
   (Change the times in `.github/workflows/crawl.yml` → `cron:` if you like.)

## 4. Point the app at your database
1. GitHub → `mobile/www/config.js` → pencil ✏️ → set `SUPABASE_URL` and `SUPABASE_ANON_KEY` → Commit.
2. (Optional) also set `PRIVACY_URL` to your Pages URL from step 6.

## 5. Build & install the APK
1. GitHub → **Actions → Build Android APK → Run workflow** (~7 min).
2. Open the finished run → **Artifacts → scholarhub-android** → download → unzip → `app-debug.apk`.
3. Send it to your phone (WhatsApp/Telegram to yourself) → tap → allow install → open ScholarHub. 🎉

## 6. Free website for privacy policy / app-ads.txt / download page (GitHub Pages)
1. Edit `docs/privacy.html` (put your email) and `docs/index.html` (APK link once you have one).
2. Repo → **Settings → Pages → Source: Deploy from branch → Branch: main, folder: /docs → Save**.
3. Your site appears at `https://<your-username>.github.io/scholarhub/` in ~1 min. Share that link.
   To offer the APK for download: repo → **Releases → Draft new release** → attach `app-debug.apk` → publish →
   copy the file link into `docs/index.html`.

## 7. AdMob (free) – see `mobile/APK-GUIDE.md` Part 4 onwards
Test ads work immediately. Real earnings require the app on Google Play (**$25 one-time**, whenever you can).

## Manual refresh any time
GitHub → Actions → Crawl scholarships → Run workflow.

## Adding sources
Supabase → Table Editor → `sources` → Insert row (name, url, kind = `rss` or `html`, tier = `official`).
Or edit `DEFAULT_SOURCES` in `app/scraper.py`. The crawler also auto-discovers university/government
domains it finds linked from articles.

## Free-tier limits (you are far below them)
- GitHub Actions: unlimited on public repos (crawl ≈ 10 min × 2/day).
- Supabase free: 500 MB database (each scholarship ≈ 1 KB → room for ~300,000), 5 GB bandwidth/month,
  project pauses after **7 days with no activity** – the twice-daily crawl counts as activity, so it never pauses.

## Pull from a link manually (when you think something is missing)
**From GitHub (instant):** Actions → **Pull from a link** → Run workflow → paste one or more links (a university
scholarship page, a ministry page, an RSS feed…) → tick *Save as permanent source* if you want it crawled every
day from now on → Run. Results appear in Supabase / the app within a minute or two.

**From the app:** tap the ScholarHub logo 7 times → enter your admin PIN (set in `mobile/www/config.js`,
default `2468`) → paste the link → **Queue link**. It's pulled on the next crawl, or immediately if you then
run *Pull from a link* on GitHub. The same screen shows recent pulls and the last crawls.

Tip: *Deep pull* follows links one level down — useful for big directory pages like "All scholarships A–Z".
