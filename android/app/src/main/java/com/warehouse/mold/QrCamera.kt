package com.warehouse.mold

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.TorchState
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.background
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.Observer
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

@OptIn(ExperimentalGetImage::class)
@Composable
fun QrCamera(onCode: (String) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var granted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) { if (!granted) permission.launch(Manifest.permission.CAMERA) }
    if (!granted) {
        Column { Text("需要相机权限才能扫码；也可以手动输入编号。")
            Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text("允许相机") } }
        return
    }

    val previewView = remember { PreviewView(context) }
    var camera by remember { mutableStateOf<Camera?>(null) }
    var hasFlash by remember { mutableStateOf(false) }
    var torchEnabled by remember { mutableStateOf(false) }
    DisposableEffect(lifecycleOwner) {
        val executor = Executors.newSingleThreadExecutor()
        val processing = AtomicBoolean(false)
        val scanner = BarcodeScanning.getClient(BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var boundCamera: Camera? = null
        var disposed = false
        val torchObserver = Observer<Int> { torchEnabled = it == TorchState.ON }
        val lifecycleObserver = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) boundCamera?.cameraControl?.enableTorch(false)
        }
        lifecycleOwner.lifecycle.addObserver(lifecycleObserver)
        future.addListener({
            if (disposed) return@addListener
            try {
                provider = future.get()
                val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
                val analysis = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                analysis.setAnalyzer(executor) { proxy ->
                    val media = proxy.image
                    if (media == null || !processing.compareAndSet(false, true)) { proxy.close(); return@setAnalyzer }
                    val image = InputImage.fromMediaImage(media, proxy.imageInfo.rotationDegrees)
                    scanner.process(image).addOnSuccessListener { codes ->
                        codes.firstOrNull { !it.rawValue.isNullOrBlank() }?.rawValue?.let(onCode)
                    }.addOnCompleteListener { processing.set(false); proxy.close() }
                }
                provider?.unbindAll()
                boundCamera = provider?.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                camera = boundCamera
                hasFlash = boundCamera?.cameraInfo?.hasFlashUnit() == true
                boundCamera?.cameraInfo?.torchState?.observe(lifecycleOwner, torchObserver)
            } catch (_: Exception) { /* Manual input remains available. */ }
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            disposed = true
            boundCamera?.cameraControl?.enableTorch(false)
            boundCamera?.cameraInfo?.torchState?.removeObserver(torchObserver)
            lifecycleOwner.lifecycle.removeObserver(lifecycleObserver)
            camera = null
            hasFlash = false
            torchEnabled = false
            provider?.unbindAll()
            scanner.close()
            executor.shutdown()
        }
    }
    Box(Modifier.fillMaxWidth().height(250.dp)) {
        AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
        IconButton(
            onClick = { camera?.cameraControl?.enableTorch(!torchEnabled) },
            enabled = hasFlash,
            modifier = Modifier.align(Alignment.TopEnd).padding(10.dp).size(44.dp)
                .background(if (torchEnabled) Color(0xFFD8F267) else Color(0xE6172B25), RoundedCornerShape(8.dp))
        ) {
            Icon(painterResource(R.drawable.ic_flashlight),
                contentDescription = if (torchEnabled) "关闭手电筒" else "打开手电筒",
                tint = if (torchEnabled) Color(0xFF172B25) else Color.White)
        }
    }
}
