package com.warehouse.mold

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.media.AudioManager
import android.media.ToneGenerator
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import kotlinx.coroutines.delay

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
                    val sessionExpired = error.status == 401 && error.code != "BAD_CREDENTIALS"
                    if (sessionExpired) { state.user = null; state.searchOpen = false }
                    state.error = if (sessionExpired) "登录已过期，请重新登录；作业清单仍保留" else error.message ?: "请求失败"
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
        val proposed = WarehouseApi.validateServer(state.serverInput)
        // Check the new endpoint before replacing the saved address or its cookies.
        val url = java.net.URL("$proposed/api/health")
        val connection = url.openConnection() as java.net.HttpURLConnection
        connection.connectTimeout = 4_000
        connection.readTimeout = 4_000
        val ok = try {
            connection.responseCode == 200 && JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).optString("status") == "ok"
        } finally { connection.disconnect() }
        check(ok) { "新地址没有连接到仓库服务" }
        api.setServer(proposed)
        main.post {
            state.serverInput = api.baseUrl
            state.user = null
            state.searchOpen = false
            state.device = null
            state.results.clear()
            state.message = "已连接新地址。请重新登录并核对设备授权；未确认的单据仍保留。"
        }
    }

    private fun login() {
        val username = state.username.trim()
        val password = state.password
        job {
            val user = api.login(username, password)
            main.post { state.user = user; state.password = ""; state.message = ""; state.settingsOpen = false; state.searchOpen = false }
            val places = api.locations()
            val device = api.device()
            main.post {
                state.locations.clear(); state.locations.addAll(places)
                state.device = device
            }
        }
    }

    private fun refreshData() = job {
        val places = api.locations()
        val device = api.device()
        main.post { state.locations.clear(); state.locations.addAll(places); state.device = device; state.message = "作业资料已刷新" }
    }

    private fun openSearch() {
        state.settingsOpen = false
        state.searchOpen = true
        state.searchQuery = ""
        state.searchResults.clear()
        state.searchTotal = 0
        state.searchSubmitted = false
        state.error = ""
        state.message = ""
    }

    private fun searchMolds() {
        val query = state.searchQuery.trim()
        if (query.isBlank()) { state.error = "请输入模具编号、套号或型号"; return }
        state.searchResults.clear()
        state.searchSubmitted = false
        job {
            val result = api.searchMolds(query)
            main.post {
                if (state.searchOpen && state.searchQuery.trim() == query) {
                    state.searchResults.addAll(result.items)
                    state.searchTotal = result.total
                    state.searchSubmitted = true
                }
            }
        }
    }

    private fun logout() = job {
        api.logout()
        main.post { state.user = null; state.device = null; state.searchOpen = false; state.message = "已退出" }
    }

    private fun refreshDevice() = job { val device = api.device(); main.post { state.device = device } }
    private fun registerDevice() = job {
        require(state.deviceLabel.isNotBlank()) { "请填写手机名称" }
        api.registerDevice(state.deviceLabel.trim())
        val device = api.device()
        main.post { state.device = device; state.message = "手机已登记，请在电脑端系统管理授权，再点刷新状态。" }
    }

    private fun scanOrSearch(raw: String, fromCamera: Boolean = false) = job {
        state.message = ""
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
        if (!draftServerMatches() || draftRestricted()) { state.error = "清单属于原仓库或原账号，请清空普通草稿后重新扫码"; return false }
        if (state.targetId != null && state.targetId != id) {
            state.error = "已选库位。要更换库位，请先清空本次清单"
            return false
        }
        if (state.targetId == id) return false
        if (state.cart.isEmpty()) { state.draftOwnerId = state.user?.optInt("id"); state.draftServer = api.baseUrl }
        state.targetId = id
        state.message = "归还库位：$code。现在扫描模具"
        state.query = ""
        saveDraft()
        return true
    }

    private fun addMold(mold: Mold): Boolean {
        if (!draftServerMatches()) { state.error = "清单属于 ${state.draftServer ?: "未知仓库"}，请连接原地址或清空后重新扫码"; return false }
        if (draftRestricted()) { state.error = "保存的清单属于其他账号，请用原账号处理"; return false }
        if (state.pending) { state.error = "请先确认上次提交结果"; return false }
        if (state.mode == "RETURN" && state.targetId == null) { state.error = "请先扫描实际归还库位"; return false }
        val required = if (state.mode == "ISSUE") "READY" else "IN_USE"
        if (mold.status != required) { state.error = "${mold.code} 当前状态不适合${if (state.mode == "ISSUE") "领用" else "归还"}"; return false }
        if (state.cart.any { it.id == mold.id }) { state.message = "${mold.code} 已在清单中"; return false }
        if (state.cart.isEmpty()) { state.draftOwnerId = state.user?.optInt("id"); state.draftServer = api.baseUrl }
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
        state.manualEntryOpen = false
        state.settingsOpen = false
        state.searchOpen = false
        state.error = ""
        state.message = ""
    }

    private fun goBack() {
        when {
            state.clearConfirmVisible -> state.clearConfirmVisible = false
            state.changeShelfConfirmVisible -> state.changeShelfConfirmVisible = false
            state.searchOpen -> { state.searchOpen = false; state.error = ""; state.message = "" }
            state.settingsOpen && !state.workOpen -> state.settingsOpen = false
            state.confirmVisible && !state.pending -> { state.confirmVisible = false; state.cameraVisible = true }
            state.workOpen -> {
                state.workOpen = false; state.cameraVisible = false; state.manualEntryOpen = false
                state.error = ""; state.message = ""
            }
        }
    }

    private fun clearWork() {
        if (state.pending) { state.error = "先查询上次提交结果，不能清空待确认单据"; return }
        state.cart.clear(); state.targetId = null; state.results.clear(); state.query = ""
        state.requestId = newRequestId(); state.draftOwnerId = state.user?.optInt("id")
        state.cameraVisible = false; state.confirmVisible = false; state.workOpen = false
        state.clearConfirmVisible = false
        state.manualEntryOpen = false
        saveDraft()
    }

    private fun changeReturnShelf(clearCart: Boolean = false) {
        if (state.pending) { state.error = "请先确认上次提交结果"; return }
        if (state.cart.isNotEmpty() && !clearCart) { state.changeShelfConfirmVisible = true; return }
        if (clearCart) state.cart.clear()
        state.targetId = null; state.query = ""; state.results.clear()
        state.requestId = newRequestId()
        state.lastScan = ""; state.lastScanAt = 0L
        state.changeShelfConfirmVisible = false
        state.error = ""; state.message = ""
        state.manualEntryOpen = false
        state.cameraVisible = true
        saveDraft()
    }

    private fun submit() {
        if (!draftServerMatches()) { state.error = "清单属于其他仓库，请连接原地址后处理"; return }
        if (draftRestricted()) { state.error = "保存的清单属于其他账号"; return }
        if (state.pending) { state.error = "请先查询上次提交结果"; return }
        if (state.device?.optBoolean("authorized") != true) { state.error = "手机尚未授权"; return }
        val target = state.targetId ?: run { state.error = "请选择目标位置"; return }
        if (state.cart.isEmpty()) { state.error = "清单为空"; return }
        state.pending = true
        if (!saveDraft()) { state.pending = false; return }
        submitSaved(target)
    }

    private fun submitSaved(target: Int? = state.targetId) {
        if (!draftServerMatches() || draftRestricted()) { state.error = "不能向其他仓库或使用其他账号重试原请求，请连接原地址并用原账号登录"; return }
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
                    } else if (SubmissionRecovery.definitelyRejected(error.status, error.code)) {
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
        check(draftServerMatches() && !draftRestricted()) { "请连接原仓库地址并使用原账号查询：${state.draftServer}" }
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

    private fun saveDraft(): Boolean {
        if (draftRestricted()) return false
        if (state.cart.isEmpty() && state.targetId == null && !state.pending) {
            state.draftServer = api.baseUrl
            state.draftOwnerId = state.user?.optInt("id")
        }
        if (state.draftOwnerId == null) state.draftOwnerId = state.user?.optInt("id")
        val items = JSONArray()
        state.cart.forEach { mold ->
            items.put(JSONObject().put("id", mold.id).put("code", mold.code).put("set_code", mold.setCode)
                .put("model_code", mold.modelCode).put("name", mold.modelName).put("size_label", mold.size).put("status", mold.status)
                .put("version", mold.version).put("current_location", mold.currentLocation)
                .put("default_location_id", mold.defaultLocationId).put("default_location", mold.defaultLocation)
                .put("custodian", mold.custodian))
        }
        val draft = JSONObject().put("mode", state.mode).put("target", state.targetId)
            .put("request_id", state.requestId).put("pending", state.pending).put("items", items)
            .put("owner_id", state.draftOwnerId)
            .put("server", state.draftServer)
        return getSharedPreferences("warehouse_draft", MODE_PRIVATE).edit().putString("current", draft.toString()).commit().also {
            if (!it) state.error = "清单保存失败，暂不能提交"
        }
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
            state.draftServer = draft.optString("server").takeIf { it.isNotBlank() && it != "null" }
            state.cart.addAll(draft.getJSONArray("items").objects().map { Mold.from(it) })
            state.workOpen = state.cart.isNotEmpty() || state.pending || state.targetId != null
            state.confirmVisible = state.pending
            state.cameraVisible = state.workOpen && !state.pending
        }.onFailure { state.error = "保存的作业清单读取失败，请人工核对" }
    }

    private fun draftRestricted(): Boolean =
        (state.cart.isNotEmpty() || state.pending || state.targetId != null) && state.draftOwnerId != null && state.user != null && state.draftOwnerId != state.user?.optInt("id")

    private fun draftServerMatches(): Boolean =
        ServerAddress.allowsDraft(state.draftServer, api.baseUrl, state.cart.isNotEmpty() || state.pending || state.targetId != null)

    @Composable
    private fun Screen() {
        val s = state
        val isReturn = s.mode == "RETURN"
        val action = if (isReturn) "归还" else "领取"
        val needsShelf = isReturn && s.targetId == null
        BackHandler(enabled = s.clearConfirmVisible || s.changeShelfConfirmVisible ||
            s.user != null && (s.searchOpen || s.settingsOpen && !s.workOpen || s.workOpen)) { goBack() }
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
                    }
                }
            }
        }) { innerPadding ->
            Column(
                Modifier.fillMaxSize().padding(innerPadding).background(paper).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(15.dp)
            ) {
                Surface(color = ink, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
                        when {
                            s.user == null -> Text("连接仓库", color = Color.White, fontWeight = FontWeight.Black, fontSize = 24.sp,
                                modifier = Modifier.padding(vertical = 12.dp))
                            s.searchOpen || s.settingsOpen && !s.workOpen -> TextButton(onClick = ::goBack,
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                                Text(if (s.searchOpen) "← 搜索" else "← 设置", color = Color.White,
                                    fontWeight = FontWeight.Bold, fontSize = 22.sp)
                            }
                            !s.workOpen -> Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Image(painterResource(R.drawable.ic_launcher_foreground), contentDescription = "中乔鞋材仓库",
                                    modifier = Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)))
                                Spacer(Modifier.weight(1f))
                                TextButton(onClick = ::openSearch) { Text("搜索", color = Color.White) }
                                TextButton(onClick = { s.settingsOpen = true }) {
                                    Text("设置", color = Color.White)
                                }
                            }
                            else -> {
                                TextButton(onClick = ::goBack, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                                    Text(if (s.confirmVisible) "← 返回扫码" else "← $action", color = Color.White,
                                        fontWeight = FontWeight.Bold, fontSize = if (s.confirmVisible) 16.sp else 22.sp)
                                }
                                if (s.confirmVisible) Text("核对本次$action", color = Color.White, fontWeight = FontWeight.Black,
                                    fontSize = 24.sp, modifier = Modifier.padding(bottom = 8.dp))
                            }
                        }
                    }
                }

                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(13.dp)) {
                    val scanning = s.user != null && s.workOpen && !s.confirmVisible
                    if (!scanning && s.error.isNotBlank()) Notice(s.error, Color(0xFFFFE5DE), Color(0xFF932F22))
                    if (!scanning && s.message.isNotBlank()) Notice(s.message, Color(0xFFE5F0C6), ink)
                    when {
                        s.user == null -> LoginContent()
                        s.searchOpen -> SearchContent()
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
        if (s.changeShelfConfirmVisible) AlertDialog(
            onDismissRequest = { s.changeShelfConfirmVisible = false },
            title = { Text("更换归还库位？") },
            text = { Text("已扫模具会从本次清单中移除。") },
            confirmButton = { TextButton(onClick = { changeReturnShelf(clearCart = true) }) { Text("更换库位") } },
            dismissButton = { TextButton(onClick = { s.changeShelfConfirmVisible = false }) { Text("继续作业") } }
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
        val focus = LocalFocusManager.current
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
        OutlinedTextField(s.username, { s.username = it }, label = { Text("账号") }, singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false, keyboardType = KeyboardType.Ascii),
            modifier = Modifier.fillMaxWidth())
        OutlinedTextField(s.password, { s.password = it }, label = { Text("密码") }, singleLine = true,
            visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false, keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
            modifier = Modifier.fillMaxWidth())
        Button(onClick = { focus.clearFocus(); main.post(::login) }, enabled = !s.busy && api.baseUrl.isNotBlank(),
            colors = ButtonDefaults.buttonColors(containerColor = lime, contentColor = ink),
            shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("登录", fontWeight = FontWeight.Bold) }
        if (api.baseUrl.isBlank()) Text("请先设置服务器地址", color = muted, fontSize = 12.sp)
    }

    @Composable
    private fun HomeContent() {
        val s = state
        val device = s.device
        val hasDraft = s.cart.isNotEmpty() || s.targetId != null || s.pending
        if (s.settingsOpen) { SettingsContent(); return }
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
        HomeAction("领取", lime, ink, enabled = !s.pending, onClick = { changeMode("ISSUE") })
        HomeAction("归还", Color(0xFF264638), Color.White,
            enabled = !s.pending, onClick = { changeMode("RETURN") })
        if (device?.optBoolean("authorized") != true) {
            Notice(if (device?.optBoolean("registered") == true) "设备等待授权" else "设备尚未登记", Color(0xFFE7EBDB), ink)
            Button(onClick = { s.settingsOpen = true }, colors = ButtonDefaults.buttonColors(containerColor = ink)) { Text("设备设置") }
        }
    }

    @Composable
    private fun SearchContent() {
        val s = state
        val focus = LocalFocusManager.current
        OutlinedTextField(
            value = s.searchQuery,
            onValueChange = { s.searchQuery = it; s.searchSubmitted = false; s.searchResults.clear(); s.error = "" },
            label = { Text("搜索模具") },
            placeholder = { Text("模具编号、套号或型号") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { focus.clearFocus(); searchMolds() }),
            modifier = Modifier.fillMaxWidth()
        )
        Button(onClick = { focus.clearFocus(); searchMolds() }, enabled = !s.busy,
            colors = ButtonDefaults.buttonColors(containerColor = ink), modifier = Modifier.fillMaxWidth()) {
            Text("查找位置")
        }
        if (s.busy) Text("查询中…", color = muted, fontSize = 13.sp)
        if (s.searchSubmitted) {
            if (s.searchResults.isEmpty()) Text("没有找到模具", color = muted)
            else {
                Text(if (s.searchTotal > s.searchResults.size) "共 ${s.searchTotal} 件，显示前 ${s.searchResults.size} 件；可输入更准确的编号"
                    else "找到 ${s.searchTotal} 件", color = muted, fontSize = 13.sp)
                s.searchResults.forEach { mold ->
                    val location = s.locations.firstOrNull { it.code == mold.currentLocation }
                    val locationText = if (location == null) mold.currentLocation else "${location.code} · ${location.name}"
                    Surface(color = Color.White, shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth().border(1.dp, Color(0xFFDCE2D8), RoundedCornerShape(10.dp))) {
                        Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically) {
                                Text(mold.code, color = ink, fontWeight = FontWeight.Black, fontSize = 18.sp)
                                Text(moldStatusLabel(mold.status), color = if (mold.status == "READY") ink else muted,
                                    fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            }
                            Text("${mold.setCode} · ${mold.modelName.ifBlank { mold.modelCode }} · ${mold.size} 码",
                                color = muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("当前位置", color = muted, fontSize = 12.sp, modifier = Modifier.padding(top = 7.dp))
                            Text(locationText, color = ink, fontWeight = FontWeight.Black, fontSize = 19.sp)
                            if (mold.status == "IN_USE" && mold.custodian != null)
                                Text("领用人 ${mold.custodian}", color = muted, fontSize = 12.sp)
                        }
                    }
                }
            }
        }
    }

    private fun moldStatusLabel(status: String): String = when (status) {
        "READY" -> "在库可领"
        "IN_USE" -> "已领用"
        "PENDING_INSPECTION" -> "待检"
        "IN_REPAIR" -> "维修中"
        "UNVERIFIED" -> "待核查"
        "SCRAPPED" -> "已报废"
        else -> status
    }

    @Composable
    private fun HomeAction(title: String, background: Color, foreground: Color, enabled: Boolean, onClick: () -> Unit) {
        Button(onClick = onClick, enabled = enabled, colors = ButtonDefaults.buttonColors(containerColor = background, contentColor = foreground),
            shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth().height(168.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(title, fontSize = 34.sp, fontWeight = FontWeight.Black)
                Text("→", fontSize = 28.sp)
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
        val shownError = s.error
        val shownMessage = s.message
        LaunchedEffect(shownError, shownMessage) {
            if (shownError.isNotBlank() || shownMessage.isNotBlank()) {
                delay(if (shownError.isNotBlank()) 4_000 else 1_800)
                if (s.error == shownError) s.error = ""
                if (s.message == shownMessage) s.message = ""
            }
        }
        Text(if (needsShelf) "扫描库位" else "扫描模具", color = ink, fontSize = 20.sp, fontWeight = FontWeight.Black)
        if (s.mode == "RETURN" && shelf != null) Surface(color = Color(0xFFE4EBCB), shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
            Row(Modifier.padding(start = 13.dp, end = 4.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("库位 ${shelf.code}", color = ink, fontWeight = FontWeight.Bold)
                TextButton(onClick = { changeReturnShelf() }) { Text("更换", color = ink) }
            }
        }
        Surface(color = ink, shape = RoundedCornerShape(7.dp), modifier = Modifier.fillMaxWidth()) {
            Box(Modifier.fillMaxWidth().height(250.dp)) {
                if (s.cameraVisible) QrCamera { code ->
                    val now = System.currentTimeMillis()
                    if (!s.busy && (code != s.lastScan || now - s.lastScanAt > 2_000)) {
                        s.lastScan = code; s.lastScanAt = now
                        scanOrSearch(code, fromCamera = true)
                    }
                }
                if (s.error.isNotBlank() || s.message.isNotBlank()) {
                    val failed = s.error.isNotBlank()
                    val feedbackColor = if (failed) Color(0xFFFFB8A8) else lime
                    Surface(color = Color(0xE6172B25), shape = RoundedCornerShape(5.dp),
                        modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(9.dp).height(56.dp)) {
                        Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(if (failed) "!" else "✓", color = feedbackColor, fontWeight = FontWeight.Black, fontSize = 18.sp)
                            Text(if (failed) s.error else s.message, color = feedbackColor, fontSize = 12.sp,
                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            TextButton(onClick = { s.manualEntryOpen = !s.manualEntryOpen }) { Text("手动输入", color = muted) }
        }
        if (s.manualEntryOpen) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(s.query, { s.query = it }, singleLine = true, label = { Text(if (needsShelf) "库位编号" else "模具编号") }, modifier = Modifier.weight(1f))
            Button(onClick = { scanOrSearch(s.query) }, enabled = !s.busy, colors = ButtonDefaults.buttonColors(containerColor = ink)) { Text("确认") }
        }
        if (!needsShelf) {
            s.results.forEach { mold ->
                OutlinedButton(onClick = { addMold(mold) }, enabled = !s.pending, modifier = Modifier.fillMaxWidth()) {
                    Text("${mold.code} · ${mold.setCode} · 加入清单", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        if (!needsShelf) CartContent()
        if (s.cart.isNotEmpty() || s.targetId != null) TextButton(onClick = { s.clearConfirmVisible = true }) {
            Text("清空本次作业", color = Color(0xFF9B3B2A))
        }
    }

    @Composable
    private fun CartContent() {
        val s = state
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("已扫模具", color = ink, fontSize = 18.sp, fontWeight = FontWeight.Black)
            Text("${s.cart.size} 件", color = muted, fontWeight = FontWeight.Bold)
        }
        s.cart.forEach { mold ->
            Surface(color = Color.White, shape = RoundedCornerShape(6.dp), modifier = Modifier.fillMaxWidth().border(1.dp, Color(0xFFDCE2D8), RoundedCornerShape(6.dp))) {
                Row(Modifier.padding(11.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
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
                OutlinedButton(onClick = { if (draftServerMatches() && !draftRestricted()) { s.targetId = location.id; s.requestId = newRequestId(); saveDraft() } },
                    enabled = !s.pending && draftServerMatches() && !draftRestricted(), modifier = Modifier.fillMaxWidth(),
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
            if (!draftServerMatches()) Notice("原请求属于 ${s.draftServer}，不能向当前地址重试。请求编号 ${s.requestId}", Color(0xFFFFE5DE), Color(0xFF932F22))
            Notice("上次提交结果待确认 · 请求编号 ${s.requestId}", Color(0xFFFFE5DE), Color(0xFF932F22))
            Button(onClick = ::queryPending, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { Text("查询原提交结果") }
            OutlinedButton(onClick = { submitSaved() }, enabled = !s.busy && draftServerMatches() && s.cart.isNotEmpty() && s.targetId != null,
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
        var draftServer by mutableStateOf<String?>(null)
        var draftOwnerId by mutableStateOf<Int?>(null)
        var cameraVisible by mutableStateOf(false)
        var workOpen by mutableStateOf(false)
        var confirmVisible by mutableStateOf(false)
        var clearConfirmVisible by mutableStateOf(false)
        var changeShelfConfirmVisible by mutableStateOf(false)
        var manualEntryOpen by mutableStateOf(false)
        var settingsOpen by mutableStateOf(api.baseUrl.isBlank())
        var searchOpen by mutableStateOf(false)
        var searchQuery by mutableStateOf("")
        var searchTotal by mutableStateOf(0)
        var searchSubmitted by mutableStateOf(false)
        var lastScan = ""
        var lastScanAt = 0L
        val locations = mutableStateListOf<Location>()
        val results = mutableStateListOf<Mold>()
        val searchResults = mutableStateListOf<Mold>()
        val cart = mutableStateListOf<Mold>()
    }
}
