package com.duxue.cam.upload

import com.duxue.cam.data.ApiService
import com.duxue.cam.data.DeviceStore
import com.duxue.cam.data.FrameRequest
import com.duxue.cam.data.UploadRequest
import kotlinx.coroutines.delay
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File

class FrameUploader(private val api: ApiService, private val store: DeviceStore, private val queue: UploadQueue) {
    suspend fun drain() {
        var backoff = 1_000L
        while (true) {
            val frame = queue.peek() ?: return
            try {
                val auth = "Bearer ${store.token ?: return}"
                val signed = api.uploadUrl(auth, UploadRequest())
                api.put(signed.uploadUrl, "image/jpeg", File(frame.filePath).asRequestBody("image/jpeg".toMediaType()))
                api.submitFrame(auth, FrameRequest(signed.objectKey, frame.capturedAt, frame.elapsedRealtime))
                queue.remove(frame); backoff = 1_000
            } catch (_: Exception) {
                delay(backoff); backoff = (backoff * 2).coerceAtMost(300_000)
            }
        }
    }
}
