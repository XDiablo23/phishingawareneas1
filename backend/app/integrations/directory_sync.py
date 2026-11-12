"""
Shared roster-upsert logic for the directory-sync providers (Entra, LDAP).

Both providers fetch a list of raw user rows in their own shape, map them to
the common roster fields, and then need to idempotently upsert those into the
Employee table the identical way. Only the fetch + field-mapping differ
between providers; this module owns the one upsert/audit implementation both
call, so a change to that logic never needs to be made twice.
"""

from __future__ import annotations

from collections.abc import Callable

from app.db import models as m


def upsert_roster_from_directory(
    db, tenant_id: str, users: list[dict], map_fn: Callable[[dict], dict],
    actor: str, action: str,
) -> dict:
    """Idempotent-by-email upsert of `users` (provider-native rows) into the
    roster. `map_fn` converts one raw row into the common
    {email, full_name, department, job_title, office_location,
    seniority_level} shape. Writes one AuditLog summarising the run."""
    created = updated = skipped = 0
    for raw in users:
        d = map_fn(raw)
        if not d["email"]:
            skipped += 1
            continue
        try:
            sl = m.SeniorityLevel(d["seniority_level"])
        except ValueError:
            sl = None
        emp = db.query(m.Employee).filter_by(
            tenant_id=tenant_id, email=d["email"]).first()
        if emp is None:
            db.add(m.Employee(
                tenant_id=tenant_id, email=d["email"], full_name=d["full_name"],
                department=d["department"], job_title=d["job_title"],
                office_location=d["office_location"], seniority_level=sl))
            created += 1
        else:
            emp.full_name = d["full_name"]
            emp.department = d["department"]
            emp.job_title = d["job_title"]
            emp.office_location = d["office_location"]
            if sl is not None:
                emp.seniority_level = sl
            updated += 1

    result = {"total": len(users), "created": created,
              "updated": updated, "skipped": skipped}
    db.add(m.AuditLog(tenant_id=tenant_id, actor=actor, action=action, detail=result))
    db.commit()
    return result
