import jwt
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import Student, User
from tests.conftest import PASSWORD


def test_register_links_login_to_student_and_returns_token(api, make_student, register, db_session):
    student = make_student()
    r = register(student.usn, "Ana@Example.com")
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]

    db_session.refresh(student)
    assert student.user_id is not None
    user = db_session.get(User, student.user_id)
    assert user.email == "ana@example.com"  # stored lower-case
    assert user.role == "student"

    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["student"]["usn"] == student.usn
    assert me.json()["student"]["cgpa"] == 8.5


def test_password_is_stored_hashed(make_student, register, db_session):
    student = make_student()
    register(student.usn)
    db_session.refresh(student)
    user = db_session.get(User, student.user_id)
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_usn_is_normalised(make_student, register):
    student = make_student(usn="ABC1234")
    assert register("  abc1234 ").status_code == 201


def test_register_unknown_usn(register):
    r = register("NOSUCHUSN")
    assert r.status_code == 404


def test_register_usn_already_registered(make_student, register):
    student = make_student()
    assert register(student.usn, "one@example.com").status_code == 201
    assert register(student.usn, "two@example.com").status_code == 409


def test_register_email_already_used(make_student, register):
    a, b = make_student(), make_student()
    assert register(a.usn, "same@example.com").status_code == 201
    assert register(b.usn, "same@example.com").status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"usn": "TEST0001", "email": "not-an-email", "password": PASSWORD},
        {"usn": "TEST0001", "email": "a@example.com", "password": "short"},
        {"usn": "TEST0001", "email": "a@example.com"},
    ],
)
def test_register_validation(api, payload):
    assert api.post("/api/auth/register", json=payload).status_code == 422


def test_login_success_and_token_works(api, make_student, register):
    student = make_student()
    register(student.usn, "login@example.com")
    r = api.post("/api/auth/login", json={"email": "LOGIN@example.com", "password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_login_failures_give_same_message(api, make_student, register):
    student = make_student()
    register(student.usn, "login@example.com")
    wrong_pw = api.post("/api/auth/login", json={"email": "login@example.com", "password": "wrong-password"})
    no_user = api.post("/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_me_requires_valid_token(api):
    assert api.get("/api/auth/me").status_code == 401
    assert api.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_token_rejected(api, make_student, register, db_session, monkeypatch):
    student = make_student()
    register(student.usn)
    db_session.refresh(student)
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    token = create_access_token(student.user_id, "student")
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_signed_with_other_key_rejected(api, make_student, register, db_session):
    student = make_student()
    register(student.usn)
    db_session.refresh(student)
    forged = jwt.encode({"sub": str(student.user_id), "role": "student"}, "x" * 40, algorithm="HS256")
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_deactivated_user_rejected(api, make_student, register, db_session):
    student = make_student()
    token = register(student.usn).json()["access_token"]
    db_session.refresh(student)
    db_session.get(User, student.user_id).is_active = False
    db_session.flush()
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    r = api.post("/api/auth/login", json={"email": "student@example.com", "password": PASSWORD})
    assert r.status_code == 401
