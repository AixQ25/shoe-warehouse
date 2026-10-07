package com.warehouse.mold

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.CookieManager
import java.net.CookiePolicy
import java.net.HttpCookie
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class Mold(
    val id: Int, val code: String, val setCode: String, val modelCode: String,
    val size: String, val status: String, val version: Int,
    val currentLocation: String, val defaultLocationId: Int, val defaultLocation: String,
    val custodian: String?, val modelName: String
) {
    companion object {
        fun from(json: JSONObject) = Mold(
            json.getInt("id"), json.getString("code"), json.getString("set_code"),
            json.getString("model_code"), json.getString("size_label"), json.getString("status"),
            json.getInt("version"), json.getString("current_location"),
            json.getInt("default_location_id"), json.getString("default_location"),
            json.optString("custodian").takeIf { it.isNotBlank() && it != "null" },
            json.optString("name")
        )
    }
}

data class MoldSearch(val total: Int, val items: List<Mold>)

data class Location(val id: Int, val code: String, val name: String, val type: String, val active: Boolean) {
    companion object {
        fun from(json: JSONObject) = Location(json.getInt("id"), json.getString("code"), json.getString("name"), json.getString("type"), json.getBoolean("active"))
    }
}

class ApiFailure(val status: Int, val code: String?, message: String) : Exception(message)

class WarehouseApi(context: Context) {
    private val prefs = context.getSharedPreferences("warehouse_client", Context.MODE_PRIVATE)
    private val cookies = CookieManager(null, CookiePolicy.ACCEPT_ALL)
    private val cookieExpiry = mutableMapOf<String, Long>()
    var baseUrl: String = if (BuildConfig.CAN_EDIT_SERVER) prefs.getString("server", "").orEmpty() else BuildConfig.SERVER_URL
        private set

    init { restoreCookies() }

    fun setServer(raw: String) {
        check(BuildConfig.CAN_EDIT_SERVER) { "正式版不能更换服务器地址" }
        val value = validateServer(raw)
        if (value != baseUrl) {
            cookies.cookieStore.removeAll()
            cookieExpiry.clear()
            prefs.edit().remove("cookies").putString("server", value).apply()
            baseUrl = value
        }
    }

    companion object {
        fun validateServer(raw: String): String {
            return ServerAddress.normalize(raw)
        }
    }

    fun health(): Boolean = request("GET", "/api/health").optString("status") == "ok"
    fun me(): JSONObject = request("GET", "/api/auth/me")
    fun login(username: String, password: String): JSONObject = request("POST", "/api/auth/login", JSONObject().put("username", username).put("password", password))
    fun logout() { request("POST", "/api/auth/logout", JSONObject(), true); cookies.cookieStore.removeAll(); saveCookies() }
    fun device(): JSONObject = request("GET", "/api/devices/current")
    fun registerDevice(label: String): JSONObject = request("POST", "/api/devices/register", JSONObject().put("label", label), true)
    fun locations(): List<Location> = requestArray("/api/locations").map { Location.from(it) }
    fun findMolds(query: String): List<Mold> {
        val encoded = java.net.URLEncoder.encode(query, "UTF-8")
        val result = request("GET", "/api/molds?q=$encoded&limit=30")
        return result.getJSONArray("items").objects().map { Mold.from(it) }
    }
    fun searchMolds(query: String): MoldSearch {
        val encoded = java.net.URLEncoder.encode(query, "UTF-8")
        val result = request("GET", "/api/molds?q=$encoded&limit=50")
        return MoldSearch(result.getInt("total"), result.getJSONArray("items").objects().map { Mold.from(it) })
    }
    fun scan(raw: String): JSONObject = request("POST", "/api/scan/resolve", JSONObject().put("raw_code", raw))
    fun submit(requestId: String, mode: String, targetId: Int, molds: List<Mold>): JSONObject {
        val items = JSONArray()
        molds.forEach { items.put(JSONObject().put("mold_id", it.id).put("expected_version", it.version)) }
        return request("POST", "/api/operations", JSONObject()
            .put("request_id", requestId).put("type", mode)
            .put("target_location_id", targetId).put("items", items), true)
    }
    fun byRequest(requestId: String): JSONObject = request("GET", "/api/operations/by-request/$requestId")

    private fun requestArray(path: String): List<JSONObject> {
        val result = exchange("GET", path, null, false)
        return JSONArray(result).objects()
    }
    private fun request(method: String, path: String, body: JSONObject? = null, csrf: Boolean = false): JSONObject =
        JSONObject(exchange(method, path, body, csrf))

    private fun exchange(method: String, path: String, body: JSONObject?, csrf: Boolean): String {
        check(baseUrl.isNotBlank()) { "请先设置服务器地址" }
        check(BuildConfig.CAN_EDIT_SERVER || URI(baseUrl).scheme == "https") { "正式版必须使用 HTTPS 服务器地址" }
        val uri = URI(baseUrl + path)
        val connection = URL(uri.toString()).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 5_000
        connection.readTimeout = 10_000
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        cookies.get(uri, emptyMap()).entries.forEach { (name, values) ->
            connection.setRequestProperty(name, values.joinToString("; "))
        }
        if (csrf) connection.setRequestProperty("X-CSRF-Token", cookies.cookieStore.cookies.firstOrNull { it.name == "warehouse_csrf" }?.value.orEmpty())
        try {
            if (body != null) {
                connection.doOutput = true
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val responseHeaders = connection.headerFields.filterKeys { it != null }
            cookies.put(uri, responseHeaders)
            responseHeaders.entries.filter { it.key.equals("Set-Cookie", true) }.flatMap { it.value }.forEach { header ->
                val name = header.substringBefore('=').trim()
                val maxAge = Regex("(?:^|;)\\s*max-age=(\\d+)", RegexOption.IGNORE_CASE).find(header)?.groupValues?.get(1)?.toLongOrNull()
                if (maxAge != null) cookieExpiry[name] = System.currentTimeMillis() + maxAge * 1_000
            }
            saveCookies()
            val text = (if (status in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val detail = runCatching { JSONObject(text).getJSONObject("detail") }.getOrNull()
                val message = detail?.optString("message")?.takeIf { it.isNotBlank() } ?: "请求失败（$status）"
                throw ApiFailure(status, detail?.optString("error_code"), message)
            }
            return text
        } finally { connection.disconnect() }
    }

    private fun saveCookies() {
        val array = JSONArray()
        cookies.cookieStore.cookies.filter { !it.hasExpired() && (cookieExpiry[it.name] ?: 0L) > System.currentTimeMillis() }.forEach { cookie ->
            array.put(JSONObject().put("name", cookie.name).put("value", cookie.value)
                .put("domain", cookie.domain).put("path", cookie.path)
                .put("expiresAt", cookieExpiry.getValue(cookie.name)).put("secure", cookie.secure).put("httpOnly", cookie.isHttpOnly))
        }
        prefs.edit().putString("cookies", encrypt(array.toString())).apply()
    }

    private fun restoreCookies() {
        val saved = prefs.getString("cookies", null) ?: return
        runCatching {
            val array = JSONArray(decrypt(saved))
            val uri = URI(baseUrl)
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val cookie = HttpCookie(item.getString("name"), item.getString("value"))
                cookie.domain = item.optString("domain").takeIf { it.isNotBlank() && it != "null" }
                cookie.path = item.optString("path", "/")
                val expiresAt = item.getLong("expiresAt")
                val remaining = (expiresAt - System.currentTimeMillis()) / 1_000
                if (remaining <= 0) continue
                cookie.maxAge = remaining
                cookie.secure = item.getBoolean("secure")
                cookie.isHttpOnly = item.getBoolean("httpOnly")
                if (!cookie.hasExpired()) { cookies.cookieStore.add(uri, cookie); cookieExpiry[cookie.name] = expiresAt }
            }
        }.onFailure { prefs.edit().remove("cookies").apply() }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("warehouse-cookie-key", null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder("warehouse-cookie-key", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }
    private fun encrypt(clear: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return Base64.encodeToString(cipher.iv + cipher.doFinal(clear.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }
    private fun decrypt(encoded: String): String {
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        return String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
    }
}

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
fun newRequestId(): String = UUID.randomUUID().toString()
