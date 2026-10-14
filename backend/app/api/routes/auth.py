from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models import Student, User
from app.schemas.auth import LoginRequest, MeResponse, RegisterRequest, StudentOut, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a login for an EXISTING student record, identified by USN, and sign the student in.

    Student records are pre-loaded (simulated) university data; registration links a login to one.
    """
    email = body.email.lower()

    student = db.scalar(select(Student).where(Student.usn == body.usn))
    if student is None:
        raise HTTPException(404, "No student record found for this USN.")
    if student.user_id is not None:
        raise HTTPException(409, "This USN already has an account.")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(409, "This email is already registered.")

    user = User(email=email, password_hash=hash_password(body.password), role="student")
    try:
        db.add(user)
        db.flush()
        student.user_id = user.id
        db.commit()
    except IntegrityError:  # two requests raced past the checks above
        db.rollback()
        raise HTTPException(409, "This USN or email is already registered.")

    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # Always run one password verification so timing does not reveal whether the email exists.
    password_ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(401, "Invalid email or password.")
    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user, with their student record when they have one."""
    student = db.scalar(select(Student).where(Student.user_id == user.id))
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        student=StudentOut.model_validate(student) if student else None,
    )
