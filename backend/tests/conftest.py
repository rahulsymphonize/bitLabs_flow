import os

os.environ["JWT_SECRET"] = "test-secret"
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PW = "password123"


@pytest.fixture()
def client():
    app_db.engine.dispose()
    app_db.Base.metadata.drop_all(app_db.engine)
    app_db.Base.metadata.create_all(app_db.engine)
    with app_db.SessionLocal() as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        s.flush()
        for email, role, cid in [
            ("sys@x.com", "sysAdmin", None),
            ("admin_a@x.com", "admin", a.id),
            ("admin_a2@x.com", "admin", a.id),
            ("user_a@x.com", "user", a.id),
            ("admin_b@x.com", "admin", b.id),
            ("user_b@x.com", "user", b.id),
        ]:
            s.add(
                User(
                    email=email, name=email, role=role, company_id=cid,
                    password_hash=hash_password(PW),
                )
            )
        s.commit()
    return TestClient(app)


def login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def uid(email):
    with app_db.SessionLocal() as s:
        return s.query(User).filter_by(email=email).one().id
