package com.warehouse.mold

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SubmissionRecoveryTest {
    @Test fun keepsOriginalRequestForUncertainResults() {
        for (status in listOf(401, 403, 408, 429, 500, 503, 504)) {
            assertFalse(SubmissionRecovery.definitelyRejected(status, null))
        }
        assertFalse(SubmissionRecovery.definitelyRejected(409, "REQUEST_CONFLICT"))
        assertFalse(SubmissionRecovery.definitelyRejected(409, "REQUEST_ID_CONFLICT"))
    }

    @Test fun permitsEditingAfterDefinitiveBusinessRejection() {
        assertTrue(SubmissionRecovery.definitelyRejected(409, "LOCATION_FULL"))
        assertTrue(SubmissionRecovery.definitelyRejected(409, "MOLD_VERSION_CONFLICT"))
        assertTrue(SubmissionRecovery.definitelyRejected(422, "MOLD_REFERENCE_INVALID"))
    }
}
