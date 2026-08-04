package com.duxue.cam.data

import okhttp3.RequestBody
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Url

interface ApiService {
    @POST("devices/bind") suspend fun bind(@Body body: BindRequest): BindResponse
    @POST("frames/upload-url") suspend fun uploadUrl(@Header("Authorization") auth: String, @Body body: UploadRequest = UploadRequest()): UploadResponse
    @PUT suspend fun put(@Url url: String, @Header("Content-Type") contentType: String, @Body body: RequestBody)
    @POST("frames") suspend fun submitFrame(@Header("Authorization") auth: String, @Body body: FrameRequest)
    @POST("devices/heartbeat") suspend fun heartbeat(@Header("Authorization") auth: String): HeartbeatResponse
}
