package com.warehouse.mold

import java.net.URI

object ServerAddress {
    fun normalize(raw: String): String {
        val uri = URI(raw.trim().trimEnd('/'))
        require(uri.scheme in listOf("http", "https") && !uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null && uri.path.isNullOrBlank() && (uri.port == -1 || uri.port in 1..65535)) { "请输入 http://电脑IP:5174，或有效的 HTTPS 地址" }
        val defaultPort = if (uri.scheme == "https") 443 else 80
        return URI(uri.scheme, null, uri.host.lowercase(), if (uri.port == defaultPort) -1 else uri.port, null, null, null).toString()
    }

    fun allowsDraft(origin: String?, current: String, hasDraft: Boolean): Boolean =
        !hasDraft || origin != null && runCatching { normalize(origin) == normalize(current) }.getOrDefault(false)
}
