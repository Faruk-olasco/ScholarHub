# ScholarHub — Android scholarship app (100% free stack)

    GitHub Actions (cron, 2×/day) ──runs──▶ crawler/run.py ──writes──▶ Supabase (Postgres)
                                                                            ▲
                                             Android app (mobile/) ──reads──┘  + AdMob ads

| Folder | What |
|---|---|
| `app/`        | Scraping & extraction logic (sources, deadline parser, region/level tagging, web-search discovery) |
| `crawler/`    | One-shot job that runs the scraper and writes to Supabase (used by the cron workflow) |
| `supabase/`   | `schema.sql` – paste into Supabase SQL editor once |
| `mobile/`     | Capacitor Android app (reads Supabase directly, AdMob banner + interstitial) |
| `docs/`       | GitHub Pages site: privacy policy, app-ads.txt, "get the app" page |
| `.github/workflows/crawl.yml`   | crawls at 07:00 & 19:00 Lagos time (+ manual button) |
| `.github/workflows/android.yml` | builds the APK/AAB in the cloud |

Start with **SETUP.md**.
