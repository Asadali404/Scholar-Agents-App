import sys

import streamlit as st

# CrewAI currently requires Python < 3.14.
# Keep this guard before importing CrewAI-dependent modules so a future
# Streamlit runtime change produces a clear message instead of a Pydantic
# import traceback.
if sys.version_info >= (3, 14):
    st.error(
        "ScholarHunter requires Python 3.10–3.13. "
        "Please deploy this app with Python 3.11 or 3.12."
    )
    st.stop()

import json
import os
from pathlib import Path

from pypdf import PdfReader

from crew import (
    profile_agent,
    scout_agent,
    database_and_gap,
    fit_score,
    tracker_summary,
)
from tracker import enrich_records, summary
from export import build_excel

st.set_page_config(page_title="ScholarHunter Agents", page_icon="🎓", layout="wide")

DATA = Path("data")
DEMO = DATA / "demo_run.json"


def pdf_text(upload):
    reader = PdfReader(upload)
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def load_demo():
    return json.loads(DEMO.read_text(encoding="utf-8"))


def save_state(state):
    st.session_state["run"] = state


def apply_status_edits(rows):
    if not rows:
        return []

    edited = st.data_editor(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "official_link": st.column_config.LinkColumn(
                "Official link"
            ),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=[
                    "Remaining",
                    "Pending",
                    "Applied",
                ],
                required=True,
            ),
            "fit_score": st.column_config.NumberColumn(
                "Fit",
                min_value=0,
                max_value=100,
            ),
        },
        disabled=[
            column
            for column in rows[0].keys()
            if column not in {"status", "notes"}
        ],
        key="tracker_editor",
    )

    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")

    if isinstance(edited, list):
        return edited

    return rows


st.title("🎓 ScholarHunter Agents")
st.caption("Find. Prepare. Track. Never miss a scholarship.")

with st.sidebar:
    st.header("Candidate")

    upload = st.file_uploader("Upload CV", type=["pdf", "txt"])

    interests = st.text_area(
        "Research interests",
        placeholder="Machine Learning, Deep Learning, Robotics",
    )

    domain = st.text_input("Target domain (optional)")

    level = st.selectbox(
        "Level",
        ["MS", "PhD", "Postdoc", "Any"],
    )

    countries = st.multiselect(
        "Countries",
        [
            "USA",
            "UK",
            "Canada",
            "Australia",
            "Germany",
            "South Korea",
            "Japan",
            "China",
            "France",
            "Netherlands",
        ],
    )

    custom = st.text_input("Custom country")

    if custom.strip() and custom.strip() not in countries:
        countries = countries + [custom.strip()]

    demo = st.toggle("Demo mode", value=False)

    run = st.button(
        "🚀 Run Agents",
        type="primary",
        use_container_width=True,
    )


if run:
    if demo:
        save_state(load_demo())
        st.success("Cached demo loaded.")

    elif not upload or not interests:
        st.error("Upload a CV and enter research interests.")

    elif not os.getenv("GROQ_API_KEY"):
        st.error(
            "GROQ_API_KEY is missing. Add it under "
            "Streamlit Cloud → Settings → Secrets."
        )

    else:
        if upload.name.lower().endswith(".pdf"):
            cv = pdf_text(upload)
        else:
            cv = upload.read().decode("utf-8", errors="ignore")

        with st.status(
            "Running ScholarHunter Agents...",
            expanded=True,
        ) as status:

            st.write("🔎 Agent 1 — Profile Analyst")
            profile = profile_agent(
                cv,
                interests,
                domain,
                level,
                countries,
            )

            st.write("🌐 Agent 2 — Opportunity Scout (max 5 searches)")
            queries, raw = scout_agent(profile)

            st.write("🧠 Agent 3 — Database + Gap Mentor")
            records, gap = database_and_gap(
                profile,
                raw,
            )

            st.write("📋 Agent 4 — Progress Tracker")

            for record in records:
                record.fit_score = fit_score(
                    profile,
                    record,
                )

            rows = enrich_records(records)
            weekly = tracker_summary(rows)

            state = {
                "profile": profile.model_dump(),
                "raw_results": [
                    x.model_dump()
                    for x in raw
                ],
                "records": [
                    x.model_dump()
                    for x in records
                ],
                "gap": gap.model_dump(),
                "rows": rows,
                "weekly": weekly,
                "queries": queries,
            }

            save_state(state)

            status.update(
                label="All four agents completed",
                state="complete",
            )


state = st.session_state.get("run")

if not state:
    st.info(
        "Upload a CV, add research interests, then run the agents — "
        "or enable Demo mode."
    )
    st.stop()


profile = state["profile"]
gap = state["gap"]
rows = state["rows"]


tab1, tab2, tab3, tab4 = st.tabs(
    [
        "🔎 Discover",
        "🧩 Gap Analysis",
        "📋 Tracker",
        "📤 Export",
    ]
)


with tab1:
    st.subheader("Extracted profile")

    with st.expander(
        "CandidateProfile",
        expanded=False,
    ):
        st.json(profile)

    st.subheader(
        f"Scholarships ({len(rows)})"
    )

    if rows:
        st.caption(
            "⚠️ Verify every deadline on the official scholarship site "
            "before applying."
        )

        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.warning(
            "No validated scholarship records were produced. "
            "Try Demo mode or another search."
        )


with tab2:
    st.subheader("Overall strengths")

    for item in gap.get("overall_strengths", []):
        st.write("•", item)

    st.subheader("Common gaps")

    for item in gap.get("common_gaps", []):
        st.write("•", item)

    st.subheader("Per-scholarship recommendations")

    for item in gap.get("per_scholarship", []):
        with st.expander(
            f"{item['scholarship_name']} — "
            f"{item['priority']} priority"
        ):
            st.write(
                "**Weaknesses:**",
                ", ".join(item["weaknesses"])
                or "None identified",
            )

            st.write("**Recommendations:**")

            for recommendation in item["recommendations"]:
                st.write("•", recommendation)

            st.write(
                "**Estimated prep:**",
                item["est_prep_time"],
            )


with tab3:
    st.subheader("Application tracker")

    tracker_stats = summary(rows)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", tracker_stats["total"])
    c2.metric("Applied", tracker_stats["applied"])
    c3.metric("Pending", tracker_stats["pending"])
    c4.metric("Critical", tracker_stats["critical"])

    st.progress(
        (
            tracker_stats["applied"]
            / tracker_stats["total"]
        )
        if tracker_stats["total"]
        else 0
    )

    st.info(state["weekly"])

    if rows:
        edited = apply_status_edits(rows)

        if rows:
    edited = apply_status_edits(rows)

    state["rows"] = edited.to_dict("records")
    st.session_state["run"] = state
        st.session_state["run"] = state

    critical = [
        row
        for row in state["rows"]
        if row["urgency"] == "Critical"
    ]

    if critical:
        st.warning("Critical deadlines")

        st.dataframe(
            critical,
            use_container_width=True,
            hide_index=True,
        )


with tab4:
    st.subheader("Excel export")

    excel = build_excel(
        state["rows"],
        state["gap"],
        state["profile"],
    )

    st.download_button(
        "⬇️ Download ScholarHunter.xlsx",
        data=excel,
        file_name="ScholarHunter.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )

    st.caption(
        "Deadline values are evidence-based where possible; "
        "always verify them on the official scholarship page."
    )
