from app.core.statuses import STATUS_LABELS, ApplicationStatus, status_label


def test_every_status_has_a_label():
    assert set(STATUS_LABELS) == set(ApplicationStatus)


def test_status_label_known_and_unknown():
    assert status_label("SUBMITTED") == "Submitted"
    assert status_label("SOMETHING_NEW") == "SOMETHING_NEW"
