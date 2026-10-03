from io import BytesIO
from datetime import date
import pandas as pd

def build_excel(rows, gap_report, profile):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="Scholarships")

        gaps = []
        for g in gap_report.get("per_scholarship", []):
            gaps.append({
                "scholarship_name": g["scholarship_name"],
                "weaknesses": ", ".join(g["weaknesses"]),
                "recommendations": " | ".join(g["recommendations"]),
                "priority": g["priority"],
                "est_prep_time": g["est_prep_time"],
            })
        pd.DataFrame(gaps).to_excel(writer, index=False, sheet_name="Gap_Analysis")

        profile_rows = [{"key": k, "value": v} for k, v in profile.items()]
        pd.DataFrame(profile_rows).to_excel(writer, index=False, sheet_name="Profile")

        total = len(rows)
        summary = {
            "total_scholarships": total,
            "applied": sum(x["status"] == "Applied" for x in rows),
            "pending": sum(x["status"] == "Pending" for x in rows),
            "remaining": sum(x["status"] == "Remaining" for x in rows),
            "critical_deadlines": sum(x["urgency"] == "Critical" for x in rows),
            "generation_date": str(date.today()),
        }
        pd.DataFrame([summary]).to_excel(writer, index=False, sheet_name="Summary")
    buf.seek(0)
    return buf
