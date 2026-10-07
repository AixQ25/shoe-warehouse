package com.warehouse.mold

object SubmissionRecovery {
    fun definitelyRejected(status: Int, code: String?): Boolean =
        status in listOf(400, 404, 409, 422) && code !in listOf("REQUEST_ID_CONFLICT", "REQUEST_CONFLICT")
}
