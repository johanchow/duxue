package com.duxue.cam.data

import com.google.gson.annotations.SerializedName

data class BindRequest(@SerializedName("invite_code") val inviteCode: String, @SerializedName("elapsed_realtime") val elapsedRealtime: Long)
data class BindResponse(@SerializedName("device_token") val token: String, @SerializedName("ward_name") val wardName: String, @SerializedName("capture_interval_seconds") val intervalSeconds: Int)
data class UploadRequest(@SerializedName("content_type") val contentType: String = "image/jpeg", val extension: String = "jpg")
data class UploadResponse(@SerializedName("upload_url") val uploadUrl: String, @SerializedName("oss_key") val objectKey: String, val headers: Map<String, String>)
data class FrameRequest(@SerializedName("oss_key") val objectKey: String, @SerializedName("captured_at") val capturedAt: String, @SerializedName("elapsed_realtime") val elapsedRealtime: Long)
data class HeartbeatResponse(val status: String, @SerializedName("capture_interval_seconds") val intervalSeconds: Int)
