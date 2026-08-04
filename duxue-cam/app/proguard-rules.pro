# Gson uses runtime type metadata for Retrofit request and response DTOs.
-keep class com.duxue.cam.data.** { *; }

# Room generates an implementation at compile time but reads entity metadata at runtime.
-keep class com.duxue.cam.upload.** { *; }
