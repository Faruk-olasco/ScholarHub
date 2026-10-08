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
# Android 13+ notification permission (push + deadline reminders)
grep -q 'android.permission.POST_NOTIFICATIONS' "$MANIFEST" || sed -i 's#<application #<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>\n    <application #' "$MANIFEST"
[ -f android/app/google-services.json ] && echo "Firebase: google-services.json present" || echo "Firebase: no google-services.json (push disabled in this build)"
# Push notification status-bar icon (white mortarboard) – embedded so no binary upload is needed
mkdir -p android/app/src/main/res/drawable-mdpi && echo "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAcUlEQVR4nO2UMRLAIAgEj/z/z6TCIoCCSpEZrtFRvEVFgdbvxMyciacTYyJarl8GRDKegdyJ7FF4IDWwYzwDjc4NYwtUsgMxB4DHpAaqwzP9rlWA22qAkhSJtNcBcsmjjWYUMTXnopntfnZpVbz4Vq1eotMwHdHcxrsAAAAASUVORK5CYII=" | base64 -d > android/app/src/main/res/drawable-mdpi/ic_stat_push.png
mkdir -p android/app/src/main/res/drawable-hdpi && echo "iVBORw0KGgoAAAANSUhEUgAAACQAAAAkCAYAAADhAJiYAAAAr0lEQVR4nO2W0Q6AIAgAofX/v0xPboZWgIi2cU+VgjdMJkCSJD+BiMgjD84QQURzXnOgpCIWMXWAZWs0YqKJXv8HwLfc66CnSLPwg1j340yRRoCJ3V4iRThFbLsKHU+TRnqJRaRwSoIiT1m3QpZEXvFiodEqSePFQlGkEIdv5TKhWqR+Xl4hznZCqt4ycvR7fajkq8dMzU4jpm2opi2TLhJyheV4X/LdWHmXSpJEwwUXmVAo8P8v5wAAAABJRU5ErkJggg==" | base64 -d > android/app/src/main/res/drawable-hdpi/ic_stat_push.png
mkdir -p android/app/src/main/res/drawable-xhdpi && echo "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAA90lEQVR4nO2Yyw7DIAwEoer//zI9WaqWhIfZTaHy3EjAeAJxFFIKgiAIAiGllKKMn1WBrxLPOdPnowcceeJMEVogz1ZhiCwHYOzxFRH3QMXL6RGZHqCuKinNiQx3fCJxZESk2+EXiSMtkdsbOySOXIlUF3ZMHPkWOWoFUqpX4dXqqPj0e2jl8R4dvGsV6gpgsN2+A7dbiDWBOq5LwFaBJbKyui4BY1WEsS2XBIxZEeb7RBEweiKKQkAVMFBEWcEkAoYlvJp4a7xUgAEmj+3tBXqEgBqsaFXbG/jYn3rk2GMV5NiDLeTYo0XkqcNdObv+WwdBEAT/wQd1t4w5nSbu7QAAAABJRU5ErkJggg==" | base64 -d > android/app/src/main/res/drawable-xhdpi/ic_stat_push.png
mkdir -p android/app/src/main/res/drawable-xxhdpi && echo "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAABe0lEQVR4nO2b0ZKDIAwA9eb+/5e9p8x0clUChCTq7qMVSJcYGEu3DQAAAAAAAF7PcRxHdgyf7NkBCN/E7PueHl96AJaMyRSVNvDIo5QhKnxAjxoTKSpsoBXFN0LU8gEiVqWVopZ1nLFcrxDl3mGFfYynKLeOKojReIia7qCiGM2MqOGGdxCjGRHV3eCOYjQ9osw3PkGMxiKqecMTxWiuRJ1+8AYxmm+iyKDtOoN+LI0rvJfJoilIeJKonu/xO9r5HR+9kQnuFqQHu4OomcwfFqQHryjKoySYa5CFKjXKMw5XQZJFWaJWZLOrICFa1MrHfIkgYbWoiPq3VJDgLSpyYQgRJMyKylgxQwUJvaIytxIpgoSWqAp7rFRBghZVQYxQQpAgQiqIEUoJikJPwNWEvE7QmYyz668T1AuCGiCowesEtfZc/657B1Bhibbs0D/jHPpdbBbOBxnhhJkRziga4ZSrEc5JG+GkvZGq/9UoR4V9FAAAAAAAAEBp/gBqnNBZL5N7LgAAAABJRU5ErkJggg==" | base64 -d > android/app/src/main/res/drawable-xxhdpi/ic_stat_push.png
mkdir -p android/app/src/main/res/drawable-xxxhdpi && echo "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAACJUlEQVR4nO3c0XKDMAxEUej0/3+ZvlRTxqW1jWVrBfc8NgEULRBIlG4bAAAAAAAAAACAuOM4jugaRuzRBdx11fh939O9nnQFt+zxmYJIU+idU02GIOQL9DjHKwchW9iMN1fFIOQKWnFVoxSETCERl5MKQYQXoHAdHxlE2IYVGl+KCGL5BhUbX1oZxLINZWh8aUUQ0zeQsfGlmUFMW/ETGl+aEYT7Cp/Y+JJnEG4rekPjSx5BDK/gjY0vjQRxe0Ea/9udILoXoPF1PUE0P5HG92sJovoEGj/uvyA4AiZqOQI+elam8PHt0zQHYAjCV3cAhiB+jPTi02Pj2/bO9wiPHXA4APOmIDyPfLcAzJODmHHKdQ/APCmIme910wIwmYNYcZFx+yqolTU+01XTudbZO870I2DbrkNQPCLOO8iq+pYEYFSDiGi8WRqAUQkisvEmJAATFYRC401oAGZVEEqNNxIBmFlBKDbeSAVgvIJQbryRDMDcDSJD4410AKY1iEyNNykCMH8FkbHxJlUARuU+wkPKAEzWpp9N/zDuDY5vV3+vLUsAwQhgUG0vrz1OAMEIIBgBDKp9y1d7nACCpb4PUHF1M9j6/Te/E/7HiiECfil/YeX0Bv8r4iRibCZ8TkchiMh5pfAATPRURJTwAkqrpyKiyRRSmj0VoUKuoJL3VIQa2cJKo1MRquQLLPVORahLU2ipNhWBRRTuIwAAAAAAAAAAACDsC/5/QLZOnkZSAAAAAElFTkSuQmCC" | base64 -d > android/app/src/main/res/drawable-xxxhdpi/ic_stat_push.png
grep -q 'default_notification_icon' "$MANIFEST" || sed -i 's#</application>#    <meta-data android:name="com.google.firebase.messaging.default_notification_icon" android:resource="@drawable/ic_stat_push"/>\n    <meta-data android:name="firebase_analytics_collection_enabled" android:value="false"/>\n    </application>#' "$MANIFEST"
# Version: versionCode must increase for every Play Store upload. Uses the GitHub run number (always increasing),
# versionName is human-readable (from mobile/package.json "version").
GRADLE=android/app/build.gradle
VCODE="${VERSION_CODE:-1}"
VNAME="${VERSION_NAME:-1.0.0}"
sed -i "s/versionCode [0-9]*/versionCode $VCODE/; s/versionName \"[^\"]*\"/versionName \"$VNAME\"/" "$GRADLE"
echo "Version: $VNAME ($VCODE)"
# Google Play requires targetSdk 36 (Android 16) or higher
VARS=android/variables.gradle
sed -i 's/compileSdkVersion = [0-9]*/compileSdkVersion = 36/; s/targetSdkVersion = [0-9]*/targetSdkVersion = 36/' "$VARS"
grep -q suppressUnsupportedCompileSdk android/gradle.properties || echo "android.suppressUnsupportedCompileSdk=36" >> android/gradle.properties
echo "SDK: $(grep -E 'compileSdkVersion|targetSdkVersion' $VARS | tr -s ' ')"
grep -q 'android.permission.INTERNET' "$MANIFEST" || sed -i 's#<manifest #<manifest xmlns:tools="http://schemas.android.com/tools" #' "$MANIFEST"
echo "Done. Now: npx cap sync android && cd android && ./gradlew assembleDebug"
