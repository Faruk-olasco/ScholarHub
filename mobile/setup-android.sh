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
grep -q 'android.permission.INTERNET' "$MANIFEST" || sed -i 's#<manifest #<manifest xmlns:tools="http://schemas.android.com/tools" #' "$MANIFEST"
echo "Done. Now: npx cap sync android && cd android && ./gradlew assembleDebug"
