package com.warehouse.mold

import org.junit.Assert.assertEquals
import org.junit.Test

class MoldIdentityTest {
    @Test fun showsStyleCategoryAndHalfSizeAndKeepsInternalCode() {
        val a = Mold(1, "QD-264301-A-40.5", "QD-264301-A", "QD-264301", "40.5", "READY", 1, "A-01-1", 1, "A-01-1", null, "QD-264301", "QD-264301", "A模")
        val b = a.copy(id = 2, code = "QD-264301-B-40.5", moldCategory = "B模")
        assertEquals("QD-264301 · A模 · 40.5#", a.displayName)
        assertEquals("QD-264301 · B模 · 40.5#", b.displayName)
        assertEquals("QD-264301-A-40.5", a.code)
        assertEquals("QD-264301 · 历史未分类 · 40.5#", a.copy(moldCategory = null).displayName)
    }
    @Test fun distinguishesShoeTypeWithoutChangingQrIdentity() {
        val mold = Mold(1, "G-01-A-35.5", "G-01-A", "G-01", "35.5", "READY", 1, "A-01-1", 1, "A-01-1", null, "G-01", moldCategory = "A模", shoeType = "女童")
        assertEquals("G-01 · A模 · 女童 · 35.5#", mold.displayName)
        assertEquals("G-01-A-35.5", mold.code)
    }
}
