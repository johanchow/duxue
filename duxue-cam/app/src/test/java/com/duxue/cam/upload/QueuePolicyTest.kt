package com.duxue.cam.upload

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QueuePolicyTest {
    @Test fun limitsAreInclusive() {
        assertFalse(QueuePolicy.isOverCapacity(2_000, 500L * 1024 * 1024))
        assertTrue(QueuePolicy.isOverCapacity(2_001, 1))
        assertTrue(QueuePolicy.isOverCapacity(1, 500L * 1024 * 1024 + 1))
    }
}
