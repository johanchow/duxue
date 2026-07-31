package com.duxue.cam.upload

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.duxue.cam.DuxueCamApp

class BackfillWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = try {
        (applicationContext as DuxueCamApp).uploader.drain(); Result.success()
    } catch (_: Exception) { Result.retry() }
}
