package com.warehouse.mold

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.media.AudioManager
import android.media.ToneGenerator
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.RoundedCornerShape
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

private val ink = Color(0xFF172B25)
private val lime = Color(0xFFD8F267)
private val paper = Color(0xFFF7F7F0)
private val muted = Color(0xFF637469)
private val warehouseColors = lightColorScheme(primary = ink, onPrimary = Color.White, background = paper, surface = Color.White)

class MainActivity : ComponentActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var scanTone: ToneGenerator? = null
    private lateinit var api: WarehouseApi
    private lateinit var state: ScreenState

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = android.graphics.Color.rgb(23, 43, 37)
        window.navigationBarColor = android.graphics.Color.rgb(23, 43, 37)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = 0
        api = WarehouseApi(this)
        state = ScreenState()
        restoreDraft()
        setContent { MaterialTheme(colorScheme = warehouseColors) { Screen() } }
        if (api.baseUrl.isNotBlank()) restoreSession()
    }

    override fun onDestroy() { scanTone?.release(); worker.shutdown(); super.onDestroy() }

    private fun playScanTone() {
        if (scanTone == null) scanTone = runCatching { ToneGenerator(AudioManager.STREAM_MUSIC, 80) }.getOrNull()
        scanTone?.startTone(ToneGenerator.TONE_PROP_BEEP, 140)
    }

    private fun job(action: () -> Unit) {
        if (state.busy) return
        state.busy = true
        state.error = ""
        worker.execute {
            try { action() }
            catch (error: ApiFailure) {
                main.post {
                    if (error.status == 401) state.user = null
                    state.error = if (error.status == 401) "登录已过期，请重新登录；作业清单仍保留" else error.message ?: "请求失败"
                }
            }
            catch (error: Exception) { main.post {
                state.error = if (error is java.net.ConnectException || error is java.net.UnknownHostException || error is java.net.SocketTimeoutException)
                    "连接不到仓库电脑，请检查服务器地址和手机网络"
                else error.message ?: "操作失败"
            } }
            finally { main.post { state.busy = false } }
        }
    }

    private fun restoreSession() = job {
        val user = try { api.me() } catch (error: ApiFailure) {
            if (error.status == 401) { main.post { state.user = null }; return@job }
            throw error
        }
        main.post { state.user = user }
        val places = api.locations()
        val device = api.device()
        main.post { state.locations.clear(); state.locations.addAll(places); state.device = device }
    }

    private fun connect() = job {
        val proposed = state.serverInput.trim().trimEnd('/')
        // Check the new endpoint before replacing the saved address or its cookies.
        require(proposed.startsWith("http://") || proposed.startsWith("https://")) { "请输入 http(s)://电脑IP:端口" }
        val url = java.net.URL("$proposed/api/health")
        val connection = url.openConnection() as java.net.HttpURLConnection
        connection.connectTimeout = 4_000
        connection.readTimeout = 4_000
        val ok = try {
            connection.responseCode == 200 && JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).optString("status") == "ok"
        } finally { connection.disconnect() }
        check(ok) { "新地址没有连接到仓库服务" }
        main.post {
            api.setServer(proposed)
            state.serverInput = api.baseUrl
            state.user = null
            state.device = null
            state.results.clear()
            state.message = "已连接新地址。请重新登录并核对设备授权；未确认的单据仍保留。"
        }
    }

    private fun login() = job {
        val user = api.login(state.username.trim(), state.password)
        main.post { state.user = user; state.password = ""; state.message = "登录成功" }
        val places = api.locations()
        val device = api.device()
        main.post {
            state.locations.clear(); state.locations.addAll(places)
            state.device = device
        }
    }

    private fun refreshData() = job {
        val places = api.locations()
        val device = api.device()
        main.post { state.locations.clear(); state.locations.addAll(places); state.device = device; state.message = "作业资料已刷新" }
    }

    private fun logout() = job {
        api.logout()
        main.post { state.user = null; state.device = null; state.message = "已退出" }
    }

    private fun refreshDevice() = job { val device = api.device(); main.post { state.device = device } }
    private fun registerDevice() = job {
        require(state.deviceLabel.isNotBlank()) { "请填写手机名称" }
        api.registerDevice(state.deviceLabel.trim())
        val device = api.device()
        main.post { state.device = device; state.message = "手机已登记，请在电脑端系统管理授权，再点刷新状态。" }
    }

    private fun scanOrSearch(raw: String, fromCamera: Boolean = false) = job {
        val value = raw.trim()
        require(value.isNotBlank()) { "请输入编号或扫码" }
        if (value.startsWith("MOLD:", true) || value.startsWith("LOC:", true)) {
            val result = api.scan(value)
            main.post { if (processScan(result) && fromCamera) playScanTone() }
        } else if (state.mode == "RETURN" && state.targetId == null) {
            main.post {
                val location = state.locations.firstOrNull { it.active && it.type == "SHELF" && it.code.equals(value, true) }
                if (location == null) state.error = "没有找到这个库位，请扫描库位码或输入准确编号"
                else if (selectReturnShelf(location.id, location.code) && fromCamera) playScanTone()
            }
        } else {
            val found = api.findMolds(value)
            main.post {
                state.results.clear(); state.results.addAll(found)
                val exact = found.firstOrNull { it.code.equals(value, true) }
                val added = exact?.let { addMold(it) } == true
                if (added && fromCamera) playScanTone()
                if (exact == null) state.message = if (found.isEmpty()) "没有找到模具" else "找到 ${found.size} 件，点选加入清单"
            }
        }
    }

    private fun processScan(result: JSONObject): Boolean =
        when (result.optString("kind")) {
            "MOLD" -> addMold(Mold.from(result.getJSONObject("mold")))
            "LOCATION" -> {
                if (state.pending) { state.error = "请先确认上次提交结果，目标位置不能更改"; false }
                else {
                val location = result.getJSONObject("location")
                if (state.mode == "RETURN" && location.getString("type") == "SHELF")
                    selectReturnShelf(location.getInt("id"), location.getString("code"))
                else { state.error = if (state.mode == "ISSUE") "领取时请扫描模具，产线在完成扫码后选择" else "请先扫描货架库位码"; false }
                }
            }
            else -> { state.error = "无法识别这个二维码"; false }
        }

    private fun selectReturnShelf(id: Int, code: String): Boolean {
        if (state.targetId != null && state.targetId != id) {
            state.error = "已选库位。要更换库位，请先清空本次清单"
            return false
        }
        if (state.targetId == id) return false
        state.targetId = id
        state.message = "归还库位：$code。现在扫描模具"
        state.query = ""
        saveDraft()
        return true
    }

    private fun addMold(mold: Mold): Boolean {
        if (draftRestricted()) { state.error = "保存的清单属于其他账号，请用原账号处理"; return false }
        if (state.pending) { state.error = "请先确认上次提交结果"; return false }
        if (state.mode == "RETURN" && state.targetId == null) { state.error = "请先扫描实际归还库位"; return false }
        val required = if (state.mode == "ISSUE") "READY" else "IN_USE"
        if (mold.status != required) { state.error = "${mold.code} 当前状态不适合${if (state.mode == "ISSUE") "领用" else "归还"}"; return false }
        if (state.cart.any { it.id == mold.id }) { state.message = "${mold.code} 已在清单中"; return false }
        if (state.cart.isEmpty()) state.draftOwnerId = state.user?.optInt("id")
        state.cart.add(mold)
        state.message = "已加入清单：${mold.code}（尚未登记库存）"
        saveDraft()
        return true
    }

    private fun changeMode(mode: String) {
        if (state.pending) {
            if (mode != state.mode) { state.error = "请先确认上次提交结果"; return }
            state.workOpen = true; state.confirmVisible = true; state.cameraVisible = false
            return
        }
        if (state.cart.isNotEmpty() && state.mode != mode) { state.error = "请先完成或清空当前清单"; return }
        if (state.mode != mode || state.cart.isEmpty() && state.targetId == null) {
            state.mode = mode; state.cart.clear(); state.targetId = null; state.requestId = newRequestId(); saveDraft()
        }
        state.workOpen = true
        state.confirmVisible = false
        state.cameraVisible = true
        state.results.clear()
        state.lastScan = ""
        state.lastScanAt = 0L
        state.settingsOpen = false
        state.error = ""
        state.message = ""
    }

    private fun clearWork() {
        if (state.pending) { state.error = "先查询上次提交结果，不能清空待确认单据"; return }
        state.cart.clear(); state.targetId = null; state.results.clear(); state.query = ""
        state.requestId = newRequestId(); state.draftOwnerId = state.user?.optInt("id")
        state.cameraVisible = false; state.confirmVisible = false; state.workOpen = false
        state.clearConfirmVisible = false
        saveDraft()
    }

    private fun submit() {
        if (draftRestricted()) { state.error = "保存的清单属于其他账号"; return }
        if (state.pending) { state.error = "请先查询上次提交结果"; return }
        if (state.device?.optBoolean("authorized") != true) { state.error = "手机尚未授权"; return }
        val target = state.targetId ?: run { state.error = "请选择目标位置"; return }
        if (state.cart.isEmpty()) { state.error = "清单为空"; return }
        state.pending = true
        saveDraft()
        submitSaved(target)
    }

    private fun submitSaved(target: Int? = state.targetId) {
        if (target == null) { state.error = "目标位置丢失，请人工核对保存的请求"; return }
        job {
            val id = state.requestId
            val mode = state.mode
            val items = state.cart.toList()
            try {
                val operation = api.submit(id, mode, target, items)
                main.post { finishSubmit(operation) }
            } catch (error: ApiFailure) {
                main.post {
                    if (error.status == 401) {
                        state.user = null
                        state.pending = true
                        state.error = "登录已过期，请重新登录后查询原请求结果"
                    } else if (error.status in 400..499 && error.status != 408 && error.status != 429) {
                        state.pending = false
                        state.error = "服务器拒绝提交：${error.message}。请刷新并核对清单。"
                    } else {
                        state.pending = true
                        state.error = "提交结果未确认：${error.message}。请先查询本次结果。"
                    }
                    saveDraft()
                }
            } catch (error: Exception) {
                main.post {
                    state.pending = true
                    state.error = "提交结果未确认：${error.message}。请先查询本次结果；不要重新建单。"
                    saveDraft()
                }
            }
        }
    }

    private fun queryPending() = job {
        try {
            val result = api.byRequest(state.requestId)
            main.post { finishSubmit(result) }
        } catch (error: ApiFailure) {
            main.post {
                if (error.status == 401) state.user = null
                state.error = when (error.status) {
                    401 -> "登录已过期，请重新登录后查询原请求结果"
                    404 -> "服务器未找到此请求。确认连接的是同一仓库后，可按原请求编号重试。"
                    else -> error.message.orEmpty()
                }
            }
        }
    }

    private fun finishSubmit(operation: JSONObject) {
        state.message = "服务器确认成功：单据 #${operation.getInt("id")}，${state.cart.size} 件。请刷新状态核对。"
        state.cart.clear(); state.pending = false; state.targetId = null
        state.workOpen = false; state.confirmVisible = false; state.cameraVisible = false
        state.requestId = newRequestId(); saveDraft()
    }

    private fun saveDraft() {
        if (draftRestricted()) return
        if (state.cart.isEmpty() && !state.pending) state.draftOwnerId = state.user?.optInt("id")
        if (state.draftOwnerId == null) state.draftOwnerId = state.user?.optInt("id")
        val items = JSONArray()
        state.cart.forEach { mold ->
            items.put(JSONObject().put("id", mold.id).put("code", mold.code).put("set_code", mold.setCode)
                .put("model_code", mold.modelCode).put("size_label", mold.size).put("status", mold.status)
                .put("version", mold.version).put("current_location", mold.currentLocation)
                .put("default_location_id", mold.defaultLocationId).put("default_location", mold.defaultLocation)
                .put("custodian", mold.custodian))
        }
        val draft = JSONObject().put("mode", state.mode).put("target", state.targetId)
            .put("request_id", state.requestId).put("pending", state.pending).put("items", items)
            .put("owner_id", state.draftOwnerId)
        getSharedPreferences("warehouse_draft", MODE_PRIVATE).edit().putString("current", draft.toString()).apply()
    }

    private fun restoreDraft() {
        val raw = getSharedPreferences("warehouse_draft", MODE_PRIVATE).getString("current", null) ?: return
        runCatching {
            val draft = JSONObject(raw)
            state.mode = draft.getString("mode")
            state.targetId = if (draft.isNull("target")) null else draft.getInt("target")
            state.requestId = draft.getString("request_id")
            state.pending = draft.getBoolean("pending")
            state.draftOwnerId = if (draft.isNull("owner_id")) null else draft.getInt("owner_id")
            state.cart.addAll(draft.getJSONArray("items").objects().map { Mold.from(it) })
            state.workOpen = state.cart.isNotEmpty() || state.pending || state.targetId != null
            state.confirmVisible = state.pending
            state.cameraVisible = state.workOpen && !state.pending
        }.onFailure { state.error = "保存的作业清单读取失败，请人工核对" }
    }

    private fun draftRestricted(): Boolean =
        (state.cart.isNotEmpty() || state.pending) && state.draftOwnerId != null && state.user != null && state.draftOwnerId != state.user?.optInt("id")

    @Composable
    private fun Screen() {
        val s = state
        val isReturn = s.mode == "RETURN"
        val action = if (isReturn) "归还" else "领取"
        val needsShelf = isReturn && s.targetId == null
        Scaffold(containerColor = ink, bottomBar = {
            if (s.user != null && s.workOpen && !s.pending) {
                Surface(color = paper, shadowElevation = 8.dp) {
                    Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        Button(
                            onClick = {
                                if (s.confirmVisible) submit()
                                else { s.confirmVisible = true; s.cameraVisible = false; s.error = ""; s.message = "" }
                            },
                            enabled = !s.busy && s.cart.isNotEmpty() && !needsShelf &&
                                (!s.confirmVisible || s.targetId != null && s.device?.optBoolean("authorized") == true),
                            colors = ButtonDefaults.buttonColors(containerColor = lime, contentColor = ink),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.fillMaxWidth().height(54.dp)
                        ) {
                            Text(if (s.confirmVisible) "确认提交 $action · ${s.cart.size} 件" else "完成$action · ${s.cart.size} 件", fontWeight = FontWeight.Black, fontSize = 16.sp)
                        }
                        Text("清单仅保存在本机，确认提交后才会更新库存", color = muted, fontSize = 11.sp,
                            modifier = Modifier.align(Alignment.CenterHorizontally).padding(top = 7.dp))
                    }
                }
            }
        }) { innerPadding ->
            Column(
                Modifier.fillMaxSize().padding(innerPadding).background(paper).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(15.dp)
            ) {
                Surface(color = ink, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(horizontal = 20.dp, vertical = 22.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Text("鞋模具仓库  /  MOBILE", color = lime, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            if (s.user != null && !s.workOpen) TextButton(onClick = { s.settingsOpen = !s.settingsOpen }) {
                                Text(if (s.settingsOpen) "关闭设置" else "设置", color = Color.White)
                            }
                        }
                        if (s.workOpen && s.user != null) TextButton(onClick = {
                            if (s.confirmVisible && !s.pending) { s.confirmVisible = false; s.cameraVisible = true }
                            else { s.workOpen = false; s.cameraVisible = false }
                        }, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                            Text(if (s.confirmVisible) "← 返回扫码" else "← 返回首页", color = Color.White)
                        }
                        Text(
                            when {
                                s.user == null -> "连接仓库"
                                !s.workOpen -> "今天要做什么？"
                                s.confirmVisible -> "核对本次$action"
                                else -> "$action 模具"
                            }, color = Color.White, fontWeight = FontWeight.Black, fontSize = 29.sp
                        )
                        Text(
                            when {
                                s.user == null -> "登录后开始作业"
                                !s.workOpen -> "选择一项，立即开始扫码"
                                s.confirmVisible -> "核对清单和目标位置，再提交"
                                needsShelf -> "第一步，扫描实际归还库位"
                                else -> "持续扫码，模具会逐行加入清单"
                            }, color = Color(0xFFC9D8CB), fontSize = 13.sp, modifier = Modifier.padding(top = 5.dp)
                        )
                    }
                }

                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(13.dp)) {
                    val scanning = s.user != null && s.workOpen && !s.confirmVisible
                    if (!scanning && s.error.isNotBlank()) Notice(s.error, Color(0xFFFFE5DE), Color(0xFF932F22))
                    if (!scanning && s.message.isNotBlank()) Notice(s.message, Color(0xFFE5F0C6), ink)
                    when {
                        s.user == null -> LoginContent()
                        draftRestricted() -> Notice("本机未完成作业属于另一个账号。请用原账号登录处理。", Color(0xFFFFE5DE), Color(0xFF932F22))
                        !s.workOpen -> HomeContent()
                        s.confirmVisible -> ConfirmContent()
                        else -> ScanContent()
                    }
                    Spacer(Modifier.height(18.dp))
                }
            }
        }
        if (s.clearConfirmVisible) AlertDialog(
            onDismissRequest = { s.clearConfirmVisible = false },
            title = { Text("清空本次作业？") },
            text = { Text("已扫描的模具和归还库位都会清除。库存不会改变。") },
            confirmButton = { TextButton(onClick = ::clearWork) { Text("清空", color = Color(0xFFB53F2E)) } },
            dismissButton = { TextButton(onClick = { s.clearConfirmVisible = false }) { Text("继续作业") } }
        )
    }

    @Composable
    private fun Notice(text: String, background: Color, foreground: Color) {
        Surface(color = background, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
            Text(text, color = foreground, fontSize = 13.sp, modifier = Modifier.padding(13.dp))
        }
    }

    @Composable
    private fun LoginContent() {
        val s = state
        if (BuildConfig.CAN_EDIT_SERVER) {
            TextButton(onClick = { s.settingsOpen = !s.settingsOpen }) {
                Text(if (s.settingsOpen) "收起服务器设置" else "服务器设置", color = ink)
            }
            if (s.settingsOpen) {
                OutlinedTextField(s.serverInput, { s.serverInput = it }, label = { Text("服务器地址") },
                    placeholder = { Text("http://电脑IP:5174") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Button(onClick = ::connect, enabled = !s.busy, colors = ButtonDefaults.buttonColors(containerColor = ink),
                    modifier = Modifier.fillMaxWidth()) { Text("测试连接并保存") }
            }
        }
        OutlinedTextField(s.username, { s.username = it }, label = { Text("账号") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(s.password, { s.password = it }, label = { Text("密码") }, singleLine = true,
            visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        Button(onClick = ::login, enabled = !s.busy && api.baseUrl.isNotBlank(),
            colors = ButtonDefaults.buttonColors(containerColor = lime, contentColor = ink),
            shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("登录", fontWeight = FontWeight.Bold) }
        if (api.baseUrl.isBlank()) Text("请先设置服务器地址", color = muted, fontSize = 12.sp)
    }

    @Composable
    private fun HomeContent() {
        val s = state
        val device = s.device
        val hasDraft = s.cart.isNotEmpty() || s.targetId != null || s.pending
        Text("开始作业", color = muted, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        if (hasDraft) {
            Surface(color = Color(0xFFE4EBCB), shape = RoundedCornerShape(8.dp)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("有未完成的${if (s.mode == "ISSUE") "领取" else "归还"}作业 · ${s.cart.size} 件", color = ink, fontWeight = FontWeight.Bold)
                    Button(onClick = { changeMode(s.mode) }, colors = ButtonDefaults.buttonColors(containerColor = ink),
                        modifier = Modifier.fillMaxWidth()) { Text("继续作业") }
                    if (!s.pending) TextButton(onClick = { s.clearConfirmVisible = true }) { Text("清空本次作业", color = Color(0xFF9B3B2A)) }
                }
            }
        }
        HomeAction("领取", "直接扫描模具", lime, ink, enabled = !s.pending, onClick = { changeMode("ISSUE") })
        HomeAction("归还", "先扫库位，再扫模具", Color(0xFF264638), Color.White,
            enabled = !s.pending, onClick = { changeMode("RETURN") })
        if (device?.optBoolean("authorized") != true) {
            Notice("设备${if (device?.optBoolean("registered") == true) "等待授权" else "尚未登记"}；扫码清单可保存，提交前需要完成授权。", Color(0xFFE7EBDB), ink)
            Button(onClick = { s.settingsOpen = true }, colors = ButtonDefaults.buttonColors(containerColor = ink)) { Text("打开设备设置") }
        }
        if (s.settingsOpen) SettingsContent()
    }

    @Composable
    private fun HomeAction(title: String, hint: String, background: Color, foreground: Color, enabled: Boolean, onClick: () -> Unit) {
        Button(onClick = onClick, enabled = enabled, colors = ButtonDefaults.buttonColors(containerColor = background, contentColor = foreground),
            shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth().height(128.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column { Text(title, fontSize = 31.sp, fontWeight = FontWeight.Black); Text(hint, fontSize = 13.sp, modifier = Modifier.padding(top = 5.dp)) }
                Text("↗", fontSize = 30.sp)
            }
        }
    }

    @Composable
    private fun SettingsContent() {
        val s = state
        Surface(color = Color.White, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                Text("连接与设备", color = ink, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("操作人：${s.user?.optString("person").orEmpty().ifBlank { s.user?.optString("username").orEmpty() }}", color = muted)
                Text("设备：${when { s.device == null -> "未读取"; s.device?.optBoolean("authorized") == true -> "已授权"; s.device?.optBoolean("registered") == true -> "已登记，等待电脑端授权"; else -> "尚未登记" }}", color = muted)
                if (BuildConfig.CAN_EDIT_SERVER) {
                    OutlinedTextField(s.serverInput, { s.serverInput = it }, label = { Text("服务器地址") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedButton(onClick = ::connect, enabled = !s.busy) { Text("测试新地址并保存") }
                }
                if (s.device?.optBoolean("registered") != true) {
                    OutlinedTextField(s.deviceLabel, { s.deviceLabel = it }, label = { Text("手机名称") }, modifier = Modifier.fillMaxWidth())
                    Button(onClick = ::registerDevice, enabled = !s.busy) { Text("登记手机") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = ::refreshDevice, enabled = !s.busy) { Text("刷新授权") }
                    OutlinedButton(onClick = ::refreshData, enabled = !s.busy) { Text("刷新资料") }
                }
                TextButton(onClick = ::logout, enabled = !s.busy) { Text("退出登录", color = Color(0xFF9B3B2A)) }
            }
        }
    }

    @Composable
    private fun ScanContent() {
        val s = state
        val needsShelf = s.mode == "RETURN" && s.targetId == null
        val shelf = s.locations.firstOrNull { it.id == s.targetId }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(if (needsShelf) "01  扫描库位" else "${if (s.mode == "RETURN") "02" else "01"}  扫描模具", color = ink, fontSize = 20.sp, fontWeight = FontWeight.Black)
            Surface(color = lime, shape = RoundedCornerShape(4.dp)) { Text("扫描中", color = ink, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp)) }
        }
        if (s.mode == "RETURN" && shelf != null) Notice("归还库位  ${shelf.code} · ${shelf.name}", Color(0xFFE4EBCB), ink)
        Surface(color = ink, shape = RoundedCornerShape(7.dp), modifier = Modifier.fillMaxWidth()) {
            Box(Modifier.fillMaxWidth().height(250.dp)) {
                if (s.cameraVisible) QrCamera { code ->
                    val now = System.currentTimeMillis()
                    if (!s.busy && (code != s.lastScan || now - s.lastScanAt > 2_000)) {
                        s.lastScan = code; s.lastScanAt = now
                        scanOrSearch(code, fromCamera = true)
                    }
                }
                val feedback = when {
                    s.busy -> "识别中…"
                    s.error.isNotBlank() -> s.error
                    s.message.isNotBlank() -> s.message
                    needsShelf -> "将库位二维码放入扫描框"
                    else -> "将模具二维码放入扫描框"
                }
                val feedbackColor = when {
                    s.busy -> lime
                    s.error.isNotBlank() -> Color(0xFFFFB8A8)
                    s.message.isNotBlank() -> lime
                    else -> Color.White
                }
                Surface(color = Color(0xE6172B25), shape = RoundedCornerShape(5.dp),
                    modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(9.dp).height(56.dp)) {
                    Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(if (s.busy) "◌" else if (s.error.isNotBlank()) "!" else if (s.message.isNotBlank()) "✓" else "□",
                            color = feedbackColor, fontWeight = FontWeight.Black, fontSize = 18.sp)
                        Text(feedback, color = feedbackColor, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
        Text("相机无法识别时，可手动输入${if (needsShelf) "库位" else "模具"}编号", color = muted, fontSize = 12.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(s.query, { s.query = it }, singleLine = true, label = { Text(if (needsShelf) "库位编号" else "模具编号") },
                modifier = Modifier.weight(1f))
            Button(onClick = { scanOrSearch(s.query) }, enabled = !s.busy, colors = ButtonDefaults.buttonColors(containerColor = ink)) { Text("确认") }
        }
        if (!needsShelf) {
            s.results.forEach { mold ->
                OutlinedButton(onClick = { addMold(mold) }, enabled = !s.pending, modifier = Modifier.fillMaxWidth()) {
                    Text("${mold.code} · ${mold.setCode} · 加入清单", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        CartContent()
        if (s.cart.isNotEmpty() || s.targetId != null) TextButton(onClick = { s.clearConfirmVisible = true }) {
            Text("清空本次作业", color = Color(0xFF9B3B2A))
        }
    }

    @Composable
    private fun CartContent() {
        val s = state
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("已扫描清单", color = ink, fontSize = 18.sp, fontWeight = FontWeight.Black)
            Text("${s.cart.size} 件", color = muted, fontWeight = FontWeight.Bold)
        }
        if (s.cart.isEmpty()) Notice("扫到的模具会一行一行出现在这里", Color(0xFFEBEEE3), muted)
        s.cart.forEachIndexed { index, mold ->
            Surface(color = Color.White, shape = RoundedCornerShape(6.dp), modifier = Modifier.fillMaxWidth().border(1.dp, Color(0xFFDCE2D8), RoundedCornerShape(6.dp))) {
                Row(Modifier.padding(11.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${index + 1}", color = ink, fontWeight = FontWeight.Black, modifier = Modifier.background(lime, RoundedCornerShape(3.dp)).padding(horizontal = 8.dp, vertical = 5.dp))
                    Column(Modifier.weight(1f)) {
                        Text(mold.code, color = ink, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                        Text("${mold.setCode} · ${mold.modelCode} · ${mold.size}", color = muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    if (!s.pending && !s.confirmVisible) TextButton(onClick = {
                        s.cart.remove(mold); s.requestId = newRequestId(); saveDraft()
                    }) { Text("移除", color = Color(0xFF8B4032), fontSize = 12.sp) }
                }
            }
        }
    }

    @Composable
    private fun ConfirmContent() {
        val s = state
        if (s.mode == "ISSUE") {
            Text("目标产线", color = ink, fontSize = 18.sp, fontWeight = FontWeight.Black)
            Text("扫码已完成，提交前选择模具要去的产线。", color = muted, fontSize = 13.sp)
            val lines = s.locations.filter { it.active && it.type == "LINE" }
            if (lines.isEmpty()) Notice("没有可用产线，请返回首页刷新资料。", Color(0xFFFFE5DE), Color(0xFF932F22))
            lines.forEach { location ->
                val selected = s.targetId == location.id
                OutlinedButton(onClick = { s.targetId = location.id; s.requestId = newRequestId(); saveDraft() },
                    enabled = !s.pending, modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.outlinedButtonColors(containerColor = if (selected) lime else Color.White, contentColor = ink)) {
                    Text("${if (selected) "✓  " else ""}${location.code} · ${location.name}", fontWeight = FontWeight.Bold)
                }
            }
        } else {
            val shelf = s.locations.firstOrNull { it.id == s.targetId }
            Notice("归还库位  ${shelf?.code ?: "未找到"} · ${shelf?.name.orEmpty()}", Color(0xFFE4EBCB), ink)
        }
        HorizontalDivider(color = Color(0xFFD7DFD3))
        CartContent()
        if (s.device?.optBoolean("authorized") != true) Notice("手机尚未授权，请返回首页打开设备设置。", Color(0xFFFFE5DE), Color(0xFF932F22))
        if (s.pending) {
            Notice("上次提交结果待确认 · 请求编号 ${s.requestId}", Color(0xFFFFE5DE), Color(0xFF932F22))
            Button(onClick = ::queryPending, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { Text("查询原提交结果") }
            OutlinedButton(onClick = { submitSaved() }, enabled = !s.busy && s.cart.isNotEmpty() && s.targetId != null,
                modifier = Modifier.fillMaxWidth()) { Text("按原请求编号重试") }
        }
    }

    private inner class ScreenState {
        var serverInput by mutableStateOf(api.baseUrl)
        var username by mutableStateOf("")
        var password by mutableStateOf("")
        var user by mutableStateOf<JSONObject?>(null)
        var device by mutableStateOf<JSONObject?>(null)
        var deviceLabel by mutableStateOf("我的手机")
        var busy by mutableStateOf(false)
        var error by mutableStateOf("")
        var message by mutableStateOf("")
        var query by mutableStateOf("")
        var mode by mutableStateOf("ISSUE")
        var targetId by mutableStateOf<Int?>(null)
        var requestId by mutableStateOf(newRequestId())
        var pending by mutableStateOf(false)
        var draftOwnerId by mutableStateOf<Int?>(null)
        var cameraVisible by mutableStateOf(false)
        var workOpen by mutableStateOf(false)
        var confirmVisible by mutableStateOf(false)
        var clearConfirmVisible by mutableStateOf(false)
        var settingsOpen by mutableStateOf(api.baseUrl.isBlank())
        var lastScan = ""
        var lastScanAt = 0L
        val locations = mutableStateListOf<Location>()
        val results = mutableStateListOf<Mold>()
        val cart = mutableStateListOf<Mold>()
    }
}
