from sqlalchemy import func, select

from app import db as app_db
from app.models import AuditLog
from tests.conftest import PW, login, uid


def audit_count(action=None):
    with app_db.SessionLocal() as s:
        q = select(func.count()).select_from(AuditLog)
        if action:
            q = q.where(AuditLog.action == action)
        return s.scalar(q)


def test_no_token_and_bad_token_are_401(client):
    assert client.get("/admin/users").status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.get("/auth/me", headers=bad).status_code == 401


def test_login_failure_is_generic_and_audited(client):
    r = client.post(
        "/auth/login", json={"email": "sys@x.com", "password": "wrong-pass"}
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Unauthorized access"
    assert audit_count("auth.login_failed") == 1


def test_user_role_blocked_from_admin_apis(client):
    h = login(client, "user_a@x.com")
    for method, url in [
        ("get", "/admin/users"),
        ("post", "/admin/users"),
        ("get", "/admin/companies"),
        ("get", "/admin/audit-logs"),
    ]:
        assert getattr(client, method)(url, headers=h).status_code == 403


def test_admin_cannot_manage_companies(client):
    h = login(client, "admin_a@x.com")
    assert client.get("/admin/companies", headers=h).status_code == 403
    r = client.post("/admin/companies", json={"name": "C"}, headers=h)
    assert r.status_code == 403


def test_admin_sees_only_own_company(client):
    h = login(client, "admin_a@x.com")
    emails = {u["email"] for u in client.get("/admin/users", headers=h).json()}
    assert emails == {"admin_a@x.com", "admin_a2@x.com", "user_a@x.com"}


def test_admin_cannot_touch_other_company_user(client):
    h = login(client, "admin_a@x.com")
    other = uid("user_b@x.com")
    assert client.get(f"/admin/users/{other}", headers=h).status_code == 404
    r = client.patch(
        f"/admin/users/{other}", json={"active": False}, headers=h
    )
    assert r.status_code == 404


def test_admin_cannot_reach_sysadmin(client):
    h = login(client, "admin_a@x.com")
    sid = uid("sys@x.com")
    assert client.get(f"/admin/users/{sid}", headers=h).status_code == 404


def test_admin_create_user_forced_into_own_company(client):
    h = login(client, "admin_a@x.com")
    r = client.post(
        "/admin/users",
        json={
            "email": "new@x.com", "name": "New", "password": PW,
            "role": "user", "company_id": 2,
        },
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["company_id"] == 1


def test_admin_cannot_create_sysadmin(client):
    h = login(client, "admin_a@x.com")
    r = client.post(
        "/admin/users",
        json={
            "email": "s2@x.com", "name": "S", "password": PW,
            "role": "sysAdmin",
        },
        headers=h,
    )
    assert r.status_code == 403


def test_sysadmin_crosses_companies(client):
    h = login(client, "sys@x.com")
    assert len(client.get("/admin/users", headers=h).json()) == 6
    only_b = client.get("/admin/users?company_id=2", headers=h).json()
    assert {u["company_id"] for u in only_b} == {2}
    other = uid("user_b@x.com")
    r = client.patch(
        f"/admin/users/{other}", json={"name": "Renamed"}, headers=h
    )
    assert r.status_code == 200


def test_each_mutation_writes_one_audit_row(client):
    h = login(client, "sys@x.com")
    before = audit_count()
    r = client.post("/admin/companies", json={"name": "C"}, headers=h)
    cid = r.json()["id"]
    assert audit_count() == before + 1
    client.patch(f"/admin/companies/{cid}", json={"active": False}, headers=h)
    assert audit_count("company.deactivate") == 1
    assert audit_count() == before + 2


def test_audit_log_scoped_per_company(client):
    sys_h = login(client, "sys@x.com")
    client.patch(
        f"/admin/users/{uid('user_b@x.com')}",
        json={"name": "B2"}, headers=sys_h,
    )
    client.patch(
        f"/admin/users/{uid('user_a@x.com')}",
        json={"name": "A2"}, headers=sys_h,
    )
    rows = client.get(
        "/admin/audit-logs", headers=login(client, "admin_a@x.com")
    ).json()
    assert rows and {r["company_id"] for r in rows} == {1}
    all_rows = client.get("/admin/audit-logs", headers=sys_h).json()
    assert {r["company_id"] for r in all_rows} >= {1, 2}


def test_last_admin_and_self_guards(client):
    h = login(client, "admin_b@x.com")
    me = uid("admin_b@x.com")
    r = client.patch(f"/admin/users/{me}", json={"active": False}, headers=h)
    assert r.status_code == 400
    sys_h = login(client, "sys@x.com")
    r = client.patch(
        f"/admin/users/{me}", json={"active": False}, headers=sys_h
    )
    assert r.status_code == 409
    # company A has two admins, so demoting one is fine
    a2 = uid("admin_a2@x.com")
    r = client.patch(
        f"/admin/users/{a2}", json={"role": "user"}, headers=sys_h
    )
    assert r.status_code == 200


def test_deactivated_user_token_stops_working(client):
    user_h = login(client, "user_a@x.com")
    admin_h = login(client, "admin_a@x.com")
    client.patch(
        f"/admin/users/{uid('user_a@x.com')}",
        json={"active": False}, headers=admin_h,
    )
    assert client.get("/auth/me", headers=user_h).status_code == 401


def test_inactive_company_blocks_login_and_user_creation(client):
    sys_h = login(client, "sys@x.com")
    client.patch("/admin/companies/2", json={"active": False}, headers=sys_h)
    r = client.post(
        "/auth/login", json={"email": "user_b@x.com", "password": PW}
    )
    assert r.status_code == 401
    r = client.post(
        "/admin/users",
        json={
            "email": "n@x.com", "name": "N", "password": PW,
            "role": "user", "company_id": 2,
        },
        headers=sys_h,
    )
    assert r.status_code == 409
    assert "inactive" in r.json()["detail"]


def test_signup_creates_company_and_admin(client):
    body = {
        "company_name": "Newco", "name": "N", "email": "n@new.com",
        "password": PW,
    }
    r = client.post("/auth/signup", json=body)
    assert r.status_code == 201
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/auth/me", headers=h).json()
    assert me["role"] == "admin" and me["company_id"]
    assert audit_count("auth.signup") == 1
    assert client.post("/auth/signup", json=body).status_code == 409


def test_password_reset_is_single_use_and_not_an_access_token(client, caplog):
    import re

    r = client.post("/auth/forgot-password", json={"email": "user_a@x.com"})
    assert r.status_code == 200
    unknown = client.post("/auth/forgot-password", json={"email": "no@x.com"})
    assert unknown.json() == r.json()
    token = re.search(r"token=(\S+)", caplog.text).group(1)
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=bearer).status_code == 401
    ok = client.post(
        "/auth/reset-password", json={"token": token, "password": "newpass99"}
    )
    assert ok.status_code == 200
    again = client.post(
        "/auth/reset-password", json={"token": token, "password": "another99"}
    )
    assert again.status_code == 400
    r = client.post(
        "/auth/login", json={"email": "user_a@x.com", "password": "newpass99"}
    )
    assert r.status_code == 200
