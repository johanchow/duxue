package com.duxue.cam.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.duxue.cam.DuxueCamApp
import com.duxue.cam.MainActivity

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext as DuxueCamApp
        if (intent.action != Intent.ACTION_BOOT_COMPLETED || app.store.token == null) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("resume", "恢复监控", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, 1, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(1002, NotificationCompat.Builder(context, "resume").setSmallIcon(android.R.drawable.ic_menu_camera).setContentTitle("读学Eye 已就绪").setContentText("点击恢复监控").setContentIntent(open).setAutoCancel(true).build())
    }
}
