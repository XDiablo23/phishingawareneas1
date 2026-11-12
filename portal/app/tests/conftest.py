"""
Portal test harness: in-memory DB, a fake PhishAwareness client (so the whole
escalation flow is testable without a live PA), and helpers to drive a module
through its non-skippable dwell + exam.
"""
import os

os.environ["PORTAL_DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.db as dbm
dbm.engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False},
    poolclass=StaticPool, future=True)
dbm.SessionLocal.configure(bind=dbm.engine)

from app.main import app            # noqa: E402
from app.db import Base             # noqa: E402
from app import pa_client as pa     # noqa: E402
from app import models as m         # noqa: E402
from app.seed import ensure_seed    # noqa: E402


def _band(h: float) -> str:
    return ("Low" if h < 25 else "Moderate" if h < 50
            else "High" if h < 75 else "Critical")


class FakePA:
    """In-memory stand-in for the PhishAwareness /portal API."""
    def __init__(self):
        self.emps: dict[str, dict] = {}

    def _new(self, email, full_name, department, job_title):
        return {"employee_id": "pa-" + email, "email": email,
                "full_name": full_name, "department": department,
                "job_title": job_title, "hrs": 0.0, "hrs_band": "Low",
                "campaigns_scored": 0, "susceptibility_index": 0.0,
                "org_risk": 0.0, "risk_floor": None,
                "needs_inperson_awareness": False, "inperson_reason": None,
                "inperson_since": None}

    def ensure_employee(self, db, email, full_name, department, job_title,
                        seniority_level=None):
        e = self.emps.get(email)
        if not e:
            e = self._new(email, full_name, department, job_title)
            self.emps[email] = e
        return dict(e)

    def get_by_email(self, db, email):
        e = self.emps.get(email)
        if not e:
            raise pa.PAError("employee not found")
        return dict(e)

    def _by_id(self, pid):
        for e in self.emps.values():
            if e["employee_id"] == pid:
                return e
        raise pa.PAError("no employee " + pid)

    def set_risk_floor(self, db, pid, value):
        e = self._by_id(pid)
        e["risk_floor"] = value
        if value and e["hrs"] < value:
            e["hrs"] = float(value)
            e["hrs_band"] = _band(float(value))
        return dict(e)

    def set_inperson_flag(self, db, pid, on, reason=None):
        e = self._by_id(pid)
        e["needs_inperson_awareness"] = bool(on)
        e["inperson_reason"] = reason
        return dict(e)

    def list_signals(self, db):
        return [dict(e) for e in self.emps.values()]

    def test_connection(self, db):
        return {"ok": True, "employees": len(self.emps)}

    def login_verify(self, base, email, password, verify=True):
        return {"role": "operator", "tenant_id": "T1", "email": email,
                "access_token": "fake"}

    # test-only mutation
    def set_state(self, email, hrs, band=None, campaigns=None):
        e = self.emps[email]
        e["hrs"] = float(hrs)
        e["hrs_band"] = band or _band(float(hrs))
        if campaigns is not None:
            e["campaigns_scored"] = campaigns


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(bind=dbm.engine)
    Base.metadata.create_all(bind=dbm.engine)
    db = dbm.SessionLocal()
    try:
        ensure_seed(db)
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    # no `with` -> lifespan skipped; schema/seed handled by _reset_db
    return TestClient(app)


@pytest.fixture
def fake_pa(monkeypatch):
    fp = FakePA()
    for name in ("ensure_employee", "get_by_email", "set_risk_floor",
                 "set_inperson_flag", "list_signals", "test_connection",
                 "login_verify"):
        monkeypatch.setattr(pa, name, getattr(fp, name))
    return fp


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def set_setting(**kw):
    from app import remediation as rem
    db = dbm.SessionLocal()
    try:
        s = rem.ensure_setting(db)
        for k, v in kw.items():
            setattr(s, k, v)
        db.commit()
    finally:
        db.close()


def correct_answers_for(module_key):
    db = dbm.SessionLocal()
    try:
        mod = db.query(m.Module).filter_by(key=module_key).first()
        return [q.correct_index for q in sorted(mod.questions, key=lambda q: q.order)]
    finally:
        db.close()


def complete_assignment(client, tok, aid, module_key, min_seconds):
    remaining = min_seconds
    while remaining > 0:
        step = min(30, remaining)
        client.post(f"/api/portal/assignments/{aid}/heartbeat",
                    json={"seconds": step}, headers=auth(tok))
        remaining -= step
    return client.post(f"/api/portal/assignments/{aid}/exam",
                       json={"answers": correct_answers_for(module_key)},
                       headers=auth(tok))
