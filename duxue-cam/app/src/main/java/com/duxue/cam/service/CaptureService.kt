package com.duxue.cam.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.duxue.cam.DuxueCamApp
import com.duxue.cam.MainActivity
import com.duxue.cam.capture.CameraController
import com.duxue.cam.upload.PendingFrame
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File
import java.time.Instant

class CaptureService : LifecycleService() {
    private lateinit var app: DuxueCamApp
    private var captureJob: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onCreate() {
        super.onCreate(); app = application as DuxueCamApp
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "监控状态", NotificationManager.IMPORTANCE_LOW))
        val intent = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        startForeground(ONGOING_ID, NotificationCompat.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_camera).setContentTitle("读学Eye 正在监控").setContentText(app.store.wardName ?: "已连接").setContentIntent(intent).setOngoing(true).build())
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DuxueCam:CaptureLock").apply { acquire() }
        wifiLock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager).createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "DuxueCam:WifiLock").apply { acquire() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == ACTION_STOP) { stopSelf(); return Service.START_NOT_STICKY }
        if (captureJob == null && app.store.token != null) startLoops()
        return Service.START_STICKY
    }

    private fun startLoops() {
        captureJob = lifecycleScope.launch {
            val camera = CameraController(this@CaptureService, this@CaptureService)
            camera.bind()
            launch { while (isActive) { runCatching { app.uploader.drain() }; delay(2_000) } }
            launch { while (isActive) {
                runCatching {
                    val heartbeat = app.api.heartbeat("Bearer ${app.store.token}")
                    app.store.intervalSeconds = heartbeat.intervalSeconds
                }
                delay(60_000)
            } }
            while (isActive) {
                val file = File(filesDir, "frames/${System.currentTimeMillis()}.jpg").apply { parentFile?.mkdirs() }
                runCatching {
                    camera.takePicture(file)
                    app.queue.enqueue(PendingFrame(filePath = file.path, capturedAt = Instant.now().toString(), elapsedRealtime = SystemClock.elapsedRealtime(), sizeBytes = file.length()))
                }.onFailure { file.delete() }
                delay(app.store.intervalSeconds * 1_000L)
            }
        }
    }

    override fun onDestroy() {
        captureJob?.cancel(); captureJob = null
        wakeLock?.takeIf { it.isHeld }?.release(); wifiLock?.takeIf { it.isHeld }?.release()
        super.onDestroy()
    }

    companion object { const val CHANNEL = "capture"; const val ONGOING_ID = 1001; const val ACTION_STOP = "com.duxue.cam.STOP" }
}
