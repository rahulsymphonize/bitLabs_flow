import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.audit import log_action
from app.db import get_db
from app.deps import get_current_user, unauthorized
from app.models import Company, User
from app.schemas import (
    ForgotIn,
    LoginIn,
    ResetIn,
    SignupIn,
    TokenOut,
    UserOut,
)
from app.security import (
    create_reset_token,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

log = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = (
        user
        and user.active
        and (user.company is None or user.company.active)
        and verify_password(body.password, user.password_hash)
    )
    if not ok:
        log_action(
            db, None, "auth.login_failed",
            company_id=user.company_id if user else None,
            email=body.email.lower(),
        )
        db.commit()
        raise unauthorized()
    return TokenOut(access_token=create_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, db=Depends(get_db)):
    """Creates a new company and its first admin."""
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already exists")
    if db.scalar(select(Company).where(Company.name == body.company_name)):
        raise HTTPException(409, "Company name already exists")
    company = Company(name=body.company_name)
    db.add(company)
    db.flush()
    user = User(
        email=email,
        name=body.name,
        password_hash=hash_password(body.password),
        role="admin",
        company_id=company.id,
    )
    db.add(user)
    db.flush()
    log_action(
        db, user, "auth.signup", "company", company.id,
        company_id=company.id, email=email,
    )
    db.commit()
    return TokenOut(access_token=create_token(user))


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.active:
        # ponytail: no mail server yet, the link goes to the server log.
        # Send it by email instead when SMTP is available.
        log.warning(
            "PASSWORD RESET for %s: token=%s", user.email,
            create_reset_token(user),
        )
        log_action(
            db, None, "auth.reset_requested", "user", user.id,
            company_id=user.company_id,
        )
        db.commit()
    # Same answer either way so emails cannot be probed.
    return {"detail": "If the account exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(body: ResetIn, db=Depends(get_db)):
    claims = decode_token(body.token, "reset")
    user = db.get(User, int(claims["sub"])) if claims else None
    if (
        not user
        or not user.active
        or user.password_hash[-12:] != claims["ph"]
    ):
        raise HTTPException(400, "This reset link is invalid or has expired.")
    user.password_hash = hash_password(body.password)
    log_action(
        db, user, "auth.password_reset", "user", user.id,
        company_id=user.company_id,
    )
    db.commit()
    return {"detail": "Password updated."}
