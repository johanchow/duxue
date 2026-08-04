package com.duxue.cam.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class DeviceStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context, "device", MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )
    var token: String?
        get() = prefs.getString("token", null)
        set(value) { prefs.edit().putString("token", value).apply() }
    var wardName: String?
        get() = prefs.getString("ward_name", null)
        set(value) { prefs.edit().putString("ward_name", value).apply() }
    var intervalSeconds: Int
        get() = prefs.getInt("interval", 15)
        set(value) { prefs.edit().putInt("interval", value).apply() }
    fun clear() = prefs.edit().clear().apply()
}
