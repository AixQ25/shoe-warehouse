package com.warehouse.mold

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerAddressTest {
    @Test fun normalizesSameServer() {
        assertEquals("https://warehouse.local", ServerAddress.normalize(" https://WAREHOUSE.local:443/ "))
        assertEquals("https://192.168.1.2:5175", ServerAddress.normalize("https://192.168.1.2:5175/"))
        assertEquals("http://192.168.1.2:5174", ServerAddress.normalize(" http://192.168.1.2:5174/ "))
        assertEquals("http://warehouse.local", ServerAddress.normalize("http://WAREHOUSE.local:80/"))
    }

    @Test fun rejectsUnsupportedOrAmbiguousAddresses() {
        for (address in listOf("ftp://192.168.1.2:5174", "https://user@warehouse.local", "https://warehouse.local/api", "https://warehouse.local?q=1", "https://warehouse.local#fragment", "https://warehouse.local:70000", "http://warehouse.local:0")) {
            assertTrue("Should reject $address", runCatching { ServerAddress.normalize(address) }.isFailure)
        }
    }

    @Test fun preventsOldDraftFromBeingSentToAnotherServer() {
        val original = "http://192.168.1.2:5174"
        val other = "http://192.168.1.3:5174"
        assertTrue(ServerAddress.allowsDraft(original, original, true))
        assertTrue(ServerAddress.allowsDraft("https://WAREHOUSE.local:443/", "https://warehouse.local", true))
        assertFalse(ServerAddress.allowsDraft(original, other, true))
        assertFalse(ServerAddress.allowsDraft(original, "https://192.168.1.2:5174", true))
        assertFalse(ServerAddress.allowsDraft(null, original, true))
        assertTrue(ServerAddress.allowsDraft(original, other, false))
    }
}
