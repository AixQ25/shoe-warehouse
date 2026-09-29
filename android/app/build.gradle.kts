plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.warehouse.mold"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.warehouse.mold"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
        buildConfigField("String", "SERVER_URL", "\"${providers.gradleProperty("warehouseServerUrl").orElse("").get()}\"")
    }
    buildTypes {
        debug {
            buildConfigField("boolean", "CAN_EDIT_SERVER", "true")
        }
        release {
            isMinifyEnabled = false
            buildConfigField("boolean", "CAN_EDIT_SERVER", "false")
        }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.camera:camera-core:1.6.2")
    implementation("androidx.camera:camera-camera2:1.6.2")
    implementation("androidx.camera:camera-lifecycle:1.6.2")
    implementation("androidx.camera:camera-view:1.6.2")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
}
