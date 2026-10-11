package org.mini;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

public class MiniBrainService extends Service {

    private static final String CHANNEL_ID = "mini_brain_channel";
    private static final int NOTIF_ID = 1001;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification notif = buildNotification();
        startForeground(NOTIF_ID, notif);
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "mini Brain Service",
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Keeps mini Brain running in the background");
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
    }

    private Notification buildNotification() {
        Intent openApp = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent pi = null;
        if (openApp != null) {
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                flags |= PendingIntent.FLAG_IMMUTABLE;
            }
            pi = PendingIntent.getActivity(this, 0, openApp, flags);
        }

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }

        builder.setContentTitle("mini Brain is running")
               .setContentText("Server is active on port 5000")
               .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
               .setOngoing(true);

        if (pi != null) {
            builder.setContentIntent(pi);
        }
        return builder.build();
    }
}
