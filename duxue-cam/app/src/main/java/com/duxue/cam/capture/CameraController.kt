package com.duxue.cam.capture

import android.content.Context
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class CameraController(private val context: Context, private val owner: LifecycleOwner) {
    private val capture = ImageCapture.Builder().setJpegQuality(80).build()
    suspend fun bind() = suspendCancellableCoroutine { continuation ->
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            try {
                future.get().apply { unbindAll(); bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, capture) }
                continuation.resume(Unit)
            } catch (error: Exception) { continuation.resumeWithException(error) }
        }, ContextCompat.getMainExecutor(context))
    }
    suspend fun takePicture(file: File) = suspendCancellableCoroutine { continuation ->
        capture.takePicture(ImageCapture.OutputFileOptions.Builder(file).build(), ContextCompat.getMainExecutor(context), object : ImageCapture.OnImageSavedCallback {
            override fun onImageSaved(output: ImageCapture.OutputFileResults) = continuation.resume(Unit)
            override fun onError(error: ImageCaptureException) = continuation.resumeWithException(error)
        })
    }
}
