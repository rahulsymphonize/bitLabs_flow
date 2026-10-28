from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.audit import log_action
from app.db import get_db
from app.deps import ADMIN, SYS_ADMIN, require_permission, scoped
from app.models import AuditLog, Company, User
from app.schemas import (
    AuditOut,
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])

manage_companies = require_permission("company:manage")
manage_users = require_permission("user:manage")
read_audit = require_permission("audit:read")

INACTIVE_COMPANY = "This company is inactive. Restore it before adding users."


def _action(prefix, changes):
    if "active" in changes:
        return f"{prefix}.{'activate' if changes['active'] else 'deactivate'}"
    if "role" in changes:
        return f"{prefix}.role_change"
    return f"{prefix}.update"


# ---- companies (sysAdmin) ----


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(_=Depends(manage_companies), db=Depends(get_db)):
    return db.scalars(select(Company).order_by(Company.id)).all()


@router.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(
    body: CompanyCreate, actor=Depends(manage_companies), db=Depends(get_db)
):
    if db.scalar(select(Company).where(Company.name == body.name)):
        raise HTTPException(409, "Company name already exists")
    company = Company(name=body.name)
    db.add(company)
    db.flush()
    log_action(
        db, actor, "company.create", "company", company.id,
        company_id=company.id, name=company.name,
    )
    db.commit()
    return company


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int,
    body: CompanyUpdate,
    actor=Depends(manage_companies),
    db=Depends(get_db),
):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(company, key, value)
    log_action(
        db, actor, _action("company", changes), "company", company.id,
        company_id=company.id, **changes,
    )
    db.commit()
    return company


# ---- users (admin: own company, sysAdmin: all) ----


@router.get("/users", response_model=list[UserOut])
def list_users(
    company_id: int | None = None,
    actor=Depends(manage_users),
    db=Depends(get_db),
):
    query = scoped(select(User), actor).order_by(User.id)
    if actor.role == SYS_ADMIN and company_id is not None:
        query = query.where(User.company_id == company_id)
    return db.scalars(query).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate, actor=Depends(manage_users), db=Depends(get_db)
):
    if actor.role == SYS_ADMIN and body.role == SYS_ADMIN:
        company_id = None
    elif body.role == SYS_ADMIN:
        raise HTTPException(403, "Unauthorized access")
    elif actor.role == SYS_ADMIN:
        company_id = body.company_id
    else:
        company_id = actor.company_id
    if body.role != SYS_ADMIN:
        company = db.get(Company, company_id) if company_id else None
        if not company:
            raise HTTPException(422, "A valid company is required")
        if not company.active:
            raise HTTPException(409, INACTIVE_COMPANY)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already exists")
    user = User(
        email=email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
        company_id=company_id,
    )
    db.add(user)
    db.flush()
    log_action(
        db, actor, "user.create", "user", user.id,
        company_id=company_id, email=email, role=body.role,
    )
    db.commit()
    return user


def _target(db, actor, user_id):
    # Scoping makes another company's user indistinguishable from missing.
    user = db.scalar(scoped(select(User).where(User.id == user_id), actor))
    if not user:
        raise HTTPException(404, "Not found")
    return user


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int, actor=Depends(manage_users), db=Depends(get_db)
):
    return _target(db, actor, user_id)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    actor=Depends(manage_users),
    db=Depends(get_db),
):
    target = _target(db, actor, user_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if target.id == actor.id and ("role" in changes or "active" in changes):
        raise HTTPException(400, "You cannot change your own role or status.")
    if "role" in changes and target.role == SYS_ADMIN:
        raise HTTPException(400, "A system admin's role cannot be changed.")
    loses_admin = target.role == ADMIN and target.active and (
        changes.get("role") == "user" or changes.get("active") is False
    )
    if loses_admin:
        others = db.scalar(
            select(func.count()).where(
                User.company_id == target.company_id,
                User.role == ADMIN,
                User.active.is_(True),
                User.id != target.id,
            )
        )
        if not others:
            raise HTTPException(
                409, "A company needs at least one active admin."
            )
    if "password" in changes:
        target.password_hash = hash_password(changes.pop("password"))
        changes["password_reset"] = True
    meta = dict(changes)
    for key in ("name", "role", "active"):
        if key in changes:
            setattr(target, key, changes[key])
    log_action(
        db, actor, _action("user", changes), "user", target.id,
        company_id=target.company_id, **meta,
    )
    db.commit()
    return target


# ---- audit log ----


@router.get("/audit-logs", response_model=list[AuditOut])
def audit_logs(
    action: str | None = None,
    company_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor=Depends(read_audit),
    db=Depends(get_db),
):
    query = (
        scoped(
            select(AuditLog, User.email).outerjoin(
                User, User.id == AuditLog.actor_id
            ),
            actor,
            AuditLog.company_id,
        )
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if action:
        query = query.where(AuditLog.action == action)
    if actor.role == SYS_ADMIN and company_id is not None:
        query = query.where(AuditLog.company_id == company_id)
    return [
        AuditOut(
            id=row.id, actor_id=row.actor_id, actor_email=email,
            company_id=row.company_id, action=row.action,
            target_type=row.target_type, target_id=row.target_id,
            meta=row.meta, created_at=row.created_at,
        )
        for row, email in db.execute(query)
    ]
