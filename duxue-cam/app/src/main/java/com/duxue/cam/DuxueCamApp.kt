package com.duxue.cam

import android.app.Application
import com.duxue.cam.data.ApiService
import com.duxue.cam.data.DeviceStore
import com.duxue.cam.upload.FrameUploader
import com.duxue.cam.upload.QueueDatabase
import com.duxue.cam.upload.UploadQueue
import okhttp3.OkHttpClient
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.duxue.cam.upload.BackfillWorker
import java.util.concurrent.TimeUnit
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

class DuxueCamApp : Application() {
    lateinit var store: DeviceStore
    lateinit var queue: UploadQueue
    lateinit var api: ApiService
    lateinit var uploader: FrameUploader
    override fun onCreate() {
        super.onCreate()
        store = DeviceStore(this)
        queue = UploadQueue(QueueDatabase.open(this).frames())
        api = Retrofit.Builder().baseUrl(BuildConfig.API_BASE_URL).client(OkHttpClient()).addConverterFactory(GsonConverterFactory.create()).build().create(ApiService::class.java)
        uploader = FrameUploader(api, store, queue)
        val request = PeriodicWorkRequestBuilder<BackfillWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork("frame-backfill", ExistingPeriodicWorkPolicy.KEEP, request)
    }
}
