plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
}

val apiBaseUrl = providers.gradleProperty("apiBaseUrl")
    .orElse(providers.environmentVariable("API_BASE_URL"))
    .getOrElse("http://10.0.2.2:8000")
    .trim()
    .let { if (it.endsWith('/')) it else "$it/" }

val releaseStoreFile = providers.gradleProperty("storeFile")
    .orElse(providers.environmentVariable("KEYSTORE_FILE"))
val releaseStorePassword = providers.gradleProperty("storePassword")
    .orElse(providers.environmentVariable("KEYSTORE_PASSWORD"))
val releaseKeyAlias = providers.gradleProperty("keyAlias")
    .orElse(providers.environmentVariable("KEY_ALIAS"))
val releaseKeyPassword = providers.gradleProperty("keyPassword")
    .orElse(providers.environmentVariable("KEY_PASSWORD"))
val releaseVersionCode = providers.gradleProperty("versionCode")
    .orElse(providers.environmentVariable("GITHUB_RUN_NUMBER"))
    .map(String::toInt)
    .getOrElse(1)
val releaseVersionName = providers.gradleProperty("versionName")
    .getOrElse("0.1.0")

android {
    namespace = "com.duxue.cam"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.duxue.cam"
        minSdk = 26
        targetSdk = 35
        versionCode = releaseVersionCode
        versionName = releaseVersionName
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
    }
    buildFeatures { compose = true; buildConfig = true }
    signingConfigs {
        create("release") {
            releaseStoreFile.orNull?.let { storeFile = file(it) }
            storePassword = releaseStorePassword.orNull
            keyAlias = releaseKeyAlias.orNull
            keyPassword = releaseKeyPassword.orNull
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    testImplementation("junit:junit:4.13.2")
}
