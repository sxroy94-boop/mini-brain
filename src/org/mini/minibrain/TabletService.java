package org.mini.minibrain;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * Runs in the SAME process as the main mini Brain app (no android:process
 * attribute is set for this service, so it is not a separate process).
 * Its only job is to call startForeground() with a persistent notification,
 * which tells Android not to kill this process when the app is backgrounded
 * or the screen turns off. The Python HTTP server (started in main.py's
 * on_start) keeps running in that same process, unaffected by this service.
 */
public class TabletService extends Service {

    public static final String CHANNEL_ID = "mini_brain_service_channel";
    public static final int NOTIF_ID = 201;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createChannel();

        Notification notification = new Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("mini Brain")
                .setContentText("Server is running in the background")
                .setSmallIcon(android.R.drawable.ic_menu_manage)
                .setOngoing(true)
                .build();

        startForeground(NOTIF_ID, notification);
        return START_STICKY;
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager =
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (manager.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel channel = new NotificationChannel(
                        CHANNEL_ID,
                        "mini Brain background service",
                        NotificationManager.IMPORTANCE_LOW);
                manager.createNotificationChannel(channel);
            }
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
