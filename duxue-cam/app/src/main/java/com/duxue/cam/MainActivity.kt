package com.duxue.cam

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.duxue.cam.data.BindRequest
import com.duxue.cam.service.CaptureService
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import retrofit2.HttpException
import java.io.IOException

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as DuxueCamApp
        setContent { MaterialTheme { CamScreen(app) } }
    }

    @Composable private fun CamScreen(app: DuxueCamApp) {
        var token by remember { mutableStateOf(app.store.token) }
        var code by remember { mutableStateOf("") }
        var running by remember { mutableStateOf(false) }
        var message by remember { mutableStateOf("") }
        var backlog by remember { mutableIntStateOf(0) }
        LaunchedEffect(token) { while (token != null) { backlog = app.queue.size(); delay(2_000) } }
        val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                ContextCompat.startForegroundService(
                    this@MainActivity,
                    Intent(this@MainActivity, CaptureService::class.java),
                )
                running = true
            }
        }
        Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("读学Eye", style = MaterialTheme.typography.headlineLarge)
            if (token == null) {
                OutlinedTextField(code, { code = it.uppercase().take(6) }, label = { Text("6 位邀请码") })
                Button(enabled = code.length == 6, onClick = {
                    lifecycleScope.launch { runCatching { app.api.bind(BindRequest(code, SystemClock.elapsedRealtime())) }.onSuccess {
                        app.store.token = it.token; app.store.wardName = it.wardName; app.store.intervalSeconds = it.intervalSeconds; token = it.token; message = "已绑定 ${it.wardName}"
                    }.onFailure {
                        Log.e(TAG, "Device binding failed", it)
                        message = bindFailureMessage(it)
                    } }
                }) { Text("绑定设备") }
            } else {
                Text("已绑定：${app.store.wardName}")
                Text(if (running) "运行中 · 每 ${app.store.intervalSeconds} 秒抓拍" else "已停止")
                Text("待补传：$backlog 张")
                Button(onClick = {
                    if (running) {
                        stopService(
                            Intent(this@MainActivity, CaptureService::class.java)
                                .setAction(CaptureService.ACTION_STOP),
                        )
                        running = false
                    }
                    else permission.launch(Manifest.permission.CAMERA)
                }) { Text(if (running) "停止监控" else "开始监控") }
                Button(onClick = { app.store.clear(); token = null; running = false }) { Text("解除本机绑定") }
            }
            if (message.isNotBlank()) Text(message)
        }
    }

    private fun bindFailureMessage(error: Throwable): String = when (error) {
        is HttpException -> when (error.code()) {
            400 -> "邀请码无效或已过期，请重新获取后再试"
            429 -> "请求过于频繁，请稍后再试"
            in 500..599 -> "测试服务器暂时异常，请稍后再试"
            else -> "绑定失败（服务器返回 ${error.code()}）"
        }
        is IOException -> when {
            error.message?.contains("reset", ignoreCase = true) == true ->
                "网络连接被服务器重置，请检查网络后重试"
            else -> "无法连接测试服务器，请检查网络后重试"
        }
        else -> "绑定失败，请稍后再试"
    }

    companion object { private const val TAG = "DuxueCam" }
}
