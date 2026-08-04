package com.duxue.cam.upload

object QueuePolicy {
    const val maxItems = 2_000
    const val maxBytes = 500L * 1024 * 1024
    fun isOverCapacity(items: Int, bytes: Long) = items > maxItems || bytes > maxBytes
}
