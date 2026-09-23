#!/usr/bin/env bash
# Run once after `npm install && npx cap add android`. Injects the AdMob App ID and app name into the Android project.
set -e
ADMOB_APP_ID="${ADMOB_APP_ID:-ca-app-pub-3940256099942544~3347511713}"   # Google's TEST App ID; replace with yours
MANIFEST=android/app/src/main/AndroidManifest.xml
if ! grep -q APPLICATION_ID "$MANIFEST"; then
  sed -i 's#</application>#    <meta-data android:name="com.google.android.gms.ads.APPLICATION_ID" android:value="'"$ADMOB_APP_ID"'"/>\n    </application>#' "$MANIFEST"
  echo "AdMob App ID injected: $ADMOB_APP_ID"
fi
# Android 11+ needs <queries> to open http links in an external browser
if ! grep -q '<queries>' "$MANIFEST"; then
  sed -i 's#</manifest>#    <queries>\n        <intent><action android:name="android.intent.action.VIEW"/><data android:scheme="https"/></intent>\n        <intent><action android:name="android.support.customtabs.action.CustomTabsService"/></intent>\n    </queries>\n</manifest>#' "$MANIFEST"
fi
# Deep links: open https://<SHARE_HOST>/ScholarHub/?s=<id> in the app (SHARE_HOST = your GitHub Pages host, e.g. username.github.io)
SHARE_HOST="${SHARE_HOST:-}"
if [ -n "$SHARE_HOST" ] && ! grep -q 'android:host="'"$SHARE_HOST"'"' "$MANIFEST"; then
  python3 - "$MANIFEST" "$SHARE_HOST" <<'PY'
import re,sys
p,host=sys.argv[1],sys.argv[2]; s=open(p).read()
f=f"""
            <intent-filter android:autoVerify="false">
                <action android:name="android.intent.action.VIEW"/>
                <category android:name="android.intent.category.DEFAULT"/>
                <category android:name="android.intent.category.BROWSABLE"/>
                <data android:scheme="https" android:host="{host}" android:pathPrefix="/ScholarHub"/>
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.VIEW"/>
                <category android:name="android.intent.category.DEFAULT"/>
                <category android:name="android.intent.category.BROWSABLE"/>
                <data android:scheme="scholarhub"/>
            </intent-filter>
        </activity>"""
s=re.sub(r"(<activity[^>]*MainActivity[\s\S]*?)</activity>", lambda m:m.group(1)+f, s, count=1)
open(p,"w").write(s); print("deep-link intent filters added for", host)
PY
fi
# Version: versionCode must increase for every Play Store upload. Uses the GitHub run number (always increasing),
# versionName is human-readable (from mobile/package.json "version").
GRADLE=android/app/build.gradle
VCODE="${VERSION_CODE:-1}"
VNAME="${VERSION_NAME:-1.0.0}"
sed -i "s/versionCode [0-9]*/versionCode $VCODE/; s/versionName \"[^\"]*\"/versionName \"$VNAME\"/" "$GRADLE"
echo "Version: $VNAME ($VCODE)"
grep -q 'android.permission.INTERNET' "$MANIFEST" || sed -i 's#<manifest #<manifest xmlns:tools="http://schemas.android.com/tools" #' "$MANIFEST"
echo "Done. Now: npx cap sync android && cd android && ./gradlew assembleDebug"
