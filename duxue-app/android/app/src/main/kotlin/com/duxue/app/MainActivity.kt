package com.duxue.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.media.AudioAttributes
import android.net.Uri
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val notifications = getSystemService(NotificationManager::class.java)
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
        for ((prompt, label) in mapOf("offer_help" to "询问是否需要帮助", "invite_return" to "邀请回到学习")) {
            val channel = NotificationChannel("support_$prompt", label, NotificationManager.IMPORTANCE_DEFAULT)
            channel.setSound(Uri.parse("android.resource://$packageName/raw/$prompt"), attributes)
            notifications.createNotificationChannel(channel)
        }
    }
}
