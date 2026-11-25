"""Business meaning of the registration status codes found in the daily health-check report."""

GROUPS = {
    "accepted": {"30"},
    "pending": {"10", "11", "60"},
    "abandoned": {"0", "1"},
    "verification_error": {"20", "21", "22", "23", "50"},
    "operator_edited": {"25"},
    "rejected": {"40"},
}

GROUP_ORDER = ["accepted", "pending", "abandoned", "verification_error", "operator_edited", "rejected"]

GROUP_LABELS = {
    "accepted": "Account created",
    "pending": "Waiting on review or approval",
    "abandoned": "Customer did not finish",
    "verification_error": "Failed verification checks",
    "operator_edited": "Corrected by an operator",
    "rejected": "Rejected",
}


def group_of(code):
    for key, codes in GROUPS.items():
        if str(code) in codes:
            return key
    return "other"
