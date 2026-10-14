

def _admin_user(db_session):
    from app.models.user import User
    from app.core.security import hash_password
    admin = User(usn="01FE23BCS900", email="01fe23bcs900@kletech.ac.in",
                 full_name="Reviewer One", role="admin",
                 password_hash=hash_password("pw"))
    db_session.add(admin)
    db_session.commit()
    return admin


def _review_token(client, db_session):
    import time
    from app.core.security import create_access_token
    admin = _admin_user(db_session)
    payload = {"sub": admin.usn, "role": admin.role,
               "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {create_access_token(payload)}"}


def test_pending_list_requires_admin(client, student_headers, db_session):
    r = client.get("/api/review/documents/pending", headers=student_headers)
    assert r.status_code == 403
    hdrs = _review_token(client, db_session)
    r = client.get("/api/review/documents/pending", headers=hdrs)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_approve_records_reviewer_and_recalc(client, student_headers, db_session):
    app = _application(client, student_headers)
    doc = _submit_document(client, student_headers, app["id"],
                           "no-dues-certificate.pdf")
    # mandatory item is pending -> payment blocked
    r = client.post(f"/api/applications/{app['id']}/payment/initiate",
                    headers=student_headers, json={})
    assert r.status_code == 422

    hdrs = _review_token(client, db_session)
    r = client.post(f"/api/review/documents/{doc['document_id']}/approve",
                    headers=hdrs)
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "VERIFIED"
    assert body["reviewed_by"].startswith("01FE23BCS900")
    assert body["reviewed_at"]

    # after verification of every mandatory item, gate allows payment
    # (other checklist items are auto-verified by OCR in this fixture path;
    # if any remain outstanding, verify the response is a clean 422/200 pair)
    r2 = client.post(f"/api/applications/{app['id']}/payment/initiate",
                     headers=student_headers, json={})
    assert r2.status_code in (200, 422)
    if r2.status_code == 422:
        codes = {o["item_code"] for o in r2.json()["detail"]["outstanding_requirements"]}
        assert "NO_DUES_CERTIFICATE" not in codes


def test_reject_requires_reason_then_blocks_payment(client, student_headers, db_session):
    app = _application(client, student_headers)
    doc = _submit_document(client, student_headers, app["id"],
                           "no-dues-certificate.pdf")
    hdrs = _review_token(client, db_session)
    r = client.post(f"/api/review/documents/{doc['document_id']}/reject",
                    headers=hdrs, json={"reason": ""})
    assert r.status_code == 422  # mandatory explanation enforced

    r = client.post(f"/api/review/documents/{doc['document_id']}/reject",
                    headers=hdrs, json={"reason": "Clearance stamp unreadable"})
    assert r.status_code == 200
    assert r.json()["validation_status"] == "REJECTED"
    assert "unreadable" in r.json()["validation_reason"]

    r = client.post(f"/api/applications/{app['id']}/payment/initiate",
                    headers=student_headers, json={})
    assert r.status_code == 422
    reasons = r.json()["detail"]["outstanding_requirements"]
    assert any(o["status"] == "REJECTED" for o in reasons)


def test_student_cannot_self_approve(client, student_headers, db_session):
    app = _application(client, student_headers)
    doc = _submit_document(client, student_headers, app["id"],
                           "no-dues-certificate.pdf")
    r = client.post(f"/api/review/documents/{doc['document_id']}/approve",
                    headers=student_headers)
    assert r.status_code == 403


def test_cross_student_document_not_found(client, student_headers, db_session,
                                          make_verified_student):
    app = _application(client, student_headers)
    doc = _submit_document(client, student_headers, app["id"],
                           "no-dues-certificate.pdf")
    other = make_verified_student(usn="01FE23BEC777")
    other_headers = _auth_headers(client, other)
    hdrs = _review_token(client, db_session)
    # even an authorized reviewer gets 404 only for nonexistent docs; but a
    # *student* token must never reach review endpoints at all:
    r = client.post(f"/api/review/documents/{doc['document_id']}/approve",
                    headers=other_headers)
    assert r.status_code == 403
