from app.models import DocumentType, User
from app.core.security import create_access_token
from tests.conftest import PDF_BYTES, PNG_BYTES


def submit(api, headers, doc_type_id, files=()):
    parts = [("files", (name, data, ctype)) for name, data, ctype in files]
    return api.post(
        "/api/applications", headers=headers, data={"document_type_id": str(doc_type_id)}, files=parts or None
    )


def test_submit_requires_login(api, doc_type):
    assert api.post("/api/applications", data={"document_type_id": str(doc_type.id)}).status_code == 401
    assert api.get("/api/applications").status_code == 401


def test_submit_without_files(api, student_auth, doc_type):
    _, headers = student_auth
    r = submit(api, headers, doc_type.id)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "SUBMITTED"
    assert body["status_label"] == "Submitted"
    assert body["document_type"]["code"] == doc_type.code
    assert body["documents"] == []
    assert len(body["history"]) == 1
    assert body["history"][0]["status"] == "SUBMITTED"
    assert body["history"][0]["note"] == "Application submitted"


def test_submit_with_files_stores_them(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    r = submit(
        api, headers, doc_type.id,
        [("grade card.pdf", PDF_BYTES, "application/pdf"), ("id.png", PNG_BYTES, "image/png")],
    )
    assert r.status_code == 201
    docs = r.json()["documents"]
    assert [d["original_filename"] for d in docs] == ["grade card.pdf", "id.png"]
    assert [d["content_type"] for d in docs] == ["application/pdf", "image/png"]
    assert [d["size_bytes"] for d in docs] == [len(PDF_BYTES), len(PNG_BYTES)]
    on_disk = sorted(p for p in upload_dir.rglob("*") if p.is_file())
    assert len(on_disk) == 2
    assert {p.suffix for p in on_disk} == {".pdf", ".png"}
    assert all(p.stem != "id" and " " not in p.name for p in on_disk)  # random names, not user-supplied


def test_unknown_or_inactive_document_type(api, student_auth, doc_type, db_session):
    _, headers = student_auth
    assert submit(api, headers, 999999).status_code == 400
    inactive = DocumentType(code="INACTIVE_TEST", name="Inactive", is_active=False)
    db_session.add(inactive)
    db_session.flush()
    assert submit(api, headers, inactive.id).status_code == 400


def test_list_shows_only_own_applications_newest_first(api, make_student, register, doc_type):
    a, b = make_student(), make_student()
    ha = {"Authorization": "Bearer " + register(a.usn, "a@example.com").json()["access_token"]}
    hb = {"Authorization": "Bearer " + register(b.usn, "b@example.com").json()["access_token"]}
    first = submit(api, ha, doc_type.id).json()["id"]
    second = submit(api, ha, doc_type.id).json()["id"]
    other = submit(api, hb, doc_type.id).json()["id"]

    mine = api.get("/api/applications", headers=ha).json()
    assert [x["id"] for x in mine] == [second, first]
    assert other not in [x["id"] for x in mine]
    assert mine[0]["document_type"]["name"] == doc_type.name
    assert [x["id"] for x in api.get("/api/applications", headers=hb).json()] == [other]


def test_cannot_read_someone_elses_application(api, make_student, register, doc_type):
    a, b = make_student(), make_student()
    ha = {"Authorization": "Bearer " + register(a.usn, "a@example.com").json()["access_token"]}
    hb = {"Authorization": "Bearer " + register(b.usn, "b@example.com").json()["access_token"]}
    app_id = submit(api, ha, doc_type.id).json()["id"]

    assert api.get(f"/api/applications/{app_id}", headers=ha).status_code == 200
    assert api.get(f"/api/applications/{app_id}", headers=hb).status_code == 404
    assert api.get("/api/applications/999999", headers=ha).status_code == 404


def test_admin_account_cannot_use_student_endpoints(api, db_session):
    admin = User(email="admin@example.com", password_hash="x", role="admin")
    db_session.add(admin)
    db_session.flush()
    headers = {"Authorization": f"Bearer {create_access_token(admin.id, 'admin')}"}
    assert api.get("/api/applications", headers=headers).status_code == 403
