package com.scholarhub.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.view.View;
import android.widget.RemoteViews;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Map;

/**
 * ScholarHub push cards. The server sends DATA messages (title, body, image, is_logo, chip, link) and this
 * service draws the card itself, so the picture is visible the moment the banner drops from the top of the
 * screen (standard Firebase notifications only show a small thumbnail until the user expands the shade).
 * Tapping opens the app on the item through the scholarhub:// deep link (handled by app.js / appUrlOpen).
 */
public class PushService extends FirebaseMessagingService {
    static final String CHANNEL = "scholarhub_daily";

    @Override
    public void onMessageReceived(RemoteMessage m) {
        Map<String, String> d = m.getData();
        String title = val(d, "title"), body = val(d, "body");
        RemoteMessage.Notification n = m.getNotification();
        if (title.isEmpty() && n != null) { title = n.getTitle() == null ? "" : n.getTitle(); body = n.getBody() == null ? "" : n.getBody(); }
        if (title.isEmpty()) return;
        String image = val(d, "image");
        if (image.isEmpty() && n != null && n.getImageUrl() != null) image = n.getImageUrl().toString();
        boolean isLogo = "1".equals(val(d, "is_logo"));
        String chip = val(d, "chip");
        String link = val(d, "link");
        if (link.isEmpty()) {
            if (!val(d, "s").isEmpty()) link = "scholarhub://open?s=" + Uri.encode(val(d, "s"));
            else if (!val(d, "n").isEmpty()) link = "scholarhub://open?n=" + Uri.encode(val(d, "n"));
            else link = "scholarhub://open";
        }
        Bitmap bmp = image.isEmpty() ? null : fetch(image);
        show(this, title, body, chip, bmp, isLogo, link);
    }

    static String val(Map<String, String> d, String k) { String v = d.get(k); return v == null ? "" : v.trim(); }

    static Bitmap fetch(String url) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(6000); c.setReadTimeout(8000); c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 13) ScholarHub");
            try (InputStream in = c.getInputStream()) {
                BitmapFactory.Options o = new BitmapFactory.Options(); o.inPreferredConfig = Bitmap.Config.RGB_565;
                Bitmap b = BitmapFactory.decodeStream(in, null, o);
                if (b == null) return null;
                if (b.getWidth() > 1080) b = Bitmap.createScaledBitmap(b, 1080, Math.max(1, b.getHeight() * 1080 / b.getWidth()), true);
                return b;
            }
        } catch (Throwable t) { return null; }
    }

    static void show(Context ctx, String title, String body, String chip, Bitmap bmp, boolean isLogo, String link) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Daily picks", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Scholarships, school news, jobs, tech and closing-soon deadlines");
            nm.createNotificationChannel(ch);
        }
        String pkg = ctx.getPackageName();
        int smallIcon = ctx.getResources().getIdentifier("ic_stat_push", "drawable", pkg);
        if (smallIcon == 0) smallIcon = ctx.getApplicationInfo().icon;

        // big card (used for the heads-up banner AND the expanded card in the shade)
        RemoteViews big = new RemoteViews(pkg, R.layout.push_banner);
        big.setTextViewText(R.id.push_title, title);
        big.setTextViewText(R.id.push_body, body);
        if (chip.isEmpty()) big.setViewVisibility(R.id.push_chip, View.GONE); else big.setTextViewText(R.id.push_chip, chip);
        if (bmp != null && !isLogo) { big.setImageViewBitmap(R.id.push_img, bmp); big.setViewVisibility(R.id.push_logo_wrap, View.GONE); }
        else if (bmp != null) { big.setImageViewBitmap(R.id.push_logo, bmp); big.setViewVisibility(R.id.push_img, View.GONE); }
        else { big.setViewVisibility(R.id.push_img, View.GONE); big.setViewVisibility(R.id.push_logo_wrap, View.GONE); }

        // compact row (collapsed card in the shade)
        RemoteViews small = new RemoteViews(pkg, R.layout.push_small);
        small.setTextViewText(R.id.push_title, title);
        small.setTextViewText(R.id.push_body, body);
        if (bmp != null) small.setImageViewBitmap(R.id.push_thumb, bmp); else small.setViewVisibility(R.id.push_thumb, View.GONE);

        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(link));
        i.setClassName(pkg, pkg + ".MainActivity");
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int req = (int) (System.currentTimeMillis() & 0x7fffffff);
        PendingIntent pi = PendingIntent.getActivity(ctx, req, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder b = new NotificationCompat.Builder(ctx, CHANNEL)
                .setSmallIcon(smallIcon)
                .setColor(0xFF0284C7)
                .setContentTitle(title).setContentText(body)
                .setStyle(new NotificationCompat.DecoratedCustomViewStyle())
                .setCustomContentView(small)
                .setCustomBigContentView(big)
                .setCustomHeadsUpContentView(big)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)
                .setDefaults(NotificationCompat.DEFAULT_ALL)
                .setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION))
                .setAutoCancel(true)
                .setContentIntent(pi);
        if (bmp != null) b.setLargeIcon(bmp);
        try { NotificationManagerCompat.from(ctx).notify(req, b.build()); } catch (SecurityException ignored) { /* permission not granted yet */ }
    }

    @Override
    public void onNewToken(String token) { /* topic subscriptions are refreshed by the app on every launch */ }
}
