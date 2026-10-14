"""Authentication request/response schemas.

USN validation policy:
- Canonical KLE Tech USNs (01FE format): must pair with a matching @kletech.ac.in email.
- Legacy/simulated USNs (SIM... format used in this prototype): accepted with any valid email,
  to preserve backward compatibility with the existing test suite and seeded simulated students.
- Other USN formats: accepted as-is (for flexibility during the prototype phase).

College email policy (applies ONLY when the USN is in canonical 01FE format):
- Email must equal usn.lower() + @kletech.ac.in (permitted input casing is normalised first).
- gmail.com, kletech.com, fakekletech.ac.in, kletech.ac.in.example.com and similar are rejected.
- Passing format validation does NOT prove mailbox existence or ownership; registration only
  creates the account credential (no verification workflow exists in this prototype yet —
  flagged here rather than silently claiming delivery/ownership).
"""
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.usn import UsNValidationError, normalize_email, validate_college_email, validate_usn


class RegisterRequest(BaseModel):
    usn: str = Field(min_length=3, max_length=20)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("usn")
    @classmethod
    def normalise_usn(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def check_canonical_usn_email_match(self) -> "RegisterRequest":
        """For canonical 01FE USNs: enforce matching @kletech.ac.in email."""
        usn: str = self.usn
        # Normalise permitted input casing before validation (canonical emails are lowercase).
        try:
            email: str = normalize_email(self.email)
        except UsNValidationError as exc:
            raise ValueError(str(exc)) from exc
        if validate_usn(usn):
            # Canonical USN: email must match exactly.
            if not validate_college_email(email, usn):
                expected = usn.lower() + "@kletech.ac.in"
                raise ValueError(
                    f"For USN '{usn}', the college email must be '{expected}'. "
                    f"Other domains (gmail.com, kletech.com, etc.) are not accepted."
                )
        # Non-canonical (SIM..., legacy formats): no email domain restriction.
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    usn: str
    full_name: str
    department: str
    semester: int
    cgpa: float
    backlog_count: int
    fee_status: str


class MeResponse(BaseModel):
    id: int
    email: str
    role: str
    student: StudentOut | None = None
