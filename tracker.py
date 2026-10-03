from datetime import date, datetime

STATUSES = ["Remaining", "Pending", "Applied"]

def parse_date(value):
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def urgency(deadline):
    d = parse_date(deadline)
    if not d:
        return None, "Verify"
    days = (d - date.today()).days
    if days <= 14:
        return days, "Critical"
    if days <= 30:
        return days, "Soon"
    return days, "OK"

def enrich_records(records, states=None):
    states = states or {}
    rows = []
    for i, r in enumerate(records, start=1):
        days, flag = urgency(r.deadline)
        status = states.get(r.official_link, "Remaining")
        rows.append({
            "id": i,
            "country": r.country,
            "scholarship_name": r.scholarship_name,
            "provider": r.provider or "",
            "level": r.level or "",
            "deadline": r.deadline or "",
            "requirements": ", ".join(r.requirements),
            "funding": r.funding or "",
            "official_link": r.official_link,
            "confidence": r.confidence,
            "fit_score": r.fit_score,
            "status": status,
            "days_left": days,
            "urgency": flag,
            "notes": states.get(f"note:{r.official_link}", "")
        })
    return rows

def summary(rows):
    return {
        "total": len(rows),
        "applied": sum(x["status"] == "Applied" for x in rows),
        "pending": sum(x["status"] == "Pending" for x in rows),
        "remaining": sum(x["status"] == "Remaining" for x in rows),
        "critical": sum(x["urgency"] == "Critical" for x in rows),
    }
