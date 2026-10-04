"""ScholarHunter – Streamlit entry point (UI + orchestration only)."""
from __future__ import annotations

# --- deployment shims: must run before crewai/chromadb are imported --------------------
import os
import sys
import tempfile

try:  # Streamlit Cloud ships an old sqlite3; chromadb (a CrewAI dependency) needs >= 3.35
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except Exception:
    pass
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_STORAGE_DIR", os.path.join(tempfile.gettempdir(), "crewai"))

import logging
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="ScholarHunter", page_icon="🎓", layout="wide")

from sh_app.core.config import MissingAPIKeyError, get_settings
from sh_app.core.models import DISCLAIMER, ScholarHunterReport, ScholarshipEntry, SearchPreferences
from sh_app.services.report_service import compute_metrics, refreshed, to_json
from sh_app.tools.cv_parser import CVParseError, parse_cv
from sh_app.utils.text import esc, is_valid_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scholarhunter")

COUNTRIES = ["Any country", "Germany", "South Korea", "USA", "Canada", "Australia", "Japan", "UK", "China",
             "Finland", "Sweden", "Norway", "Denmark", "Netherlands", "Switzerland", "France", "Italy",
             "Austria", "Ireland", "Singapore", "Turkey", "Hungary", "New Zealand", "Saudi Arabia", "Malaysia"]
LEVELS = {"MS / Master's": "MS", "PhD": "PhD", "Postdoctoral": "Postdoctoral"}
FLAGS = {"germany": "🇩🇪", "south korea": "🇰🇷", "korea": "🇰🇷", "usa": "🇺🇸", "united states": "🇺🇸", "canada": "🇨🇦",
         "australia": "🇦🇺", "japan": "🇯🇵", "uk": "🇬🇧", "united kingdom": "🇬🇧", "china": "🇨🇳", "finland": "🇫🇮",
         "sweden": "🇸🇪", "norway": "🇳🇴", "denmark": "🇩🇰", "netherlands": "🇳🇱", "switzerland": "🇨🇭",
         "france": "🇫🇷", "italy": "🇮🇹", "austria": "🇦🇹", "ireland": "🇮🇪", "singapore": "🇸🇬", "turkey": "🇹🇷",
         "hungary": "🇭🇺", "new zealand": "🇳🇿", "saudi arabia": "🇸🇦", "malaysia": "🇲🇾"}
FIT_LABELS = {"Academic Fit": "academic", "Research Fit": "research", "Technical Fit": "technical",
              "Experience Fit": "experience", "Eligibility Fit": "eligibility"}
MATCH_BADGE = {"Strong Match": ("ok", "🟢"), "Potential Match": ("info", "🔵"),
               "Needs Improvement": ("warn", "🟠"), "Insufficient Information": ("gray", "⚪")}
DEFAULT_ROADMAP = [("Improve CV", "Close the gaps listed in the CV Gap Analysis."),
                   ("Identify supervisors", "Shortlist professors whose research matches yours."),
                   ("Prepare SOP", "Draft a research-focused statement of purpose."),
                   ("Request recommendation letters", "Ask referees early and share your CV."),
                   ("Prepare documents", "Collect transcripts, language scores, ID and certificates."),
                   ("Submit application", "Apply on the official portal before the deadline.")]


# ---------------------------------------------------------------- state / styling
def init_state() -> None:
    st.session_state.setdefault("report", None)
    st.session_state.setdefault("nonce", 0)


def reset_session() -> None:
    """New Search: drop results and reset the file uploader."""
    st.session_state["report"] = None
    st.session_state["nonce"] += 1


def inject_css() -> None:
    css = Path(__file__).parent / "assets" / "style.css"
    if css.exists():
        st.markdown(f"<style>{css.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def render_header() -> None:
    st.markdown(
        '<div class="sh-hero"><h1>🎓 ScholarHunter</h1>'
        "<p>Find scholarships. Understand your fit. Build a stronger application.</p>"
        "<small>AI-Powered Scholarship Discovery &amp; Profile Analysis</small></div>",
        unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar + run
def sidebar() -> tuple[bool, dict]:
    with st.sidebar:
        st.markdown("### Your academic profile")
        uploaded = st.file_uploader("Upload CV", type=["pdf", "docx", "txt", "rtf"],
                                    key=f"cv_{st.session_state['nonce']}",
                                    help="Processed in memory for this session only; never stored.")
        countries = st.multiselect("Countries of interest", COUNTRIES, placeholder="Select countries")
        extra = st.text_input("Other countries (comma-separated)", placeholder="e.g. Estonia, Poland")
        department = st.text_input("Department / major", placeholder="e.g. Artificial Intelligence")
        level = st.radio("Academic level", list(LEVELS))
        funding = st.radio("Funding", ["Either", "Fully Funded", "Partially Funded"])
        go = st.button("🔎 Find My Scholarships", type="primary")
        if st.session_state["report"] is not None:
            st.button("↺ New Search", on_click=reset_session)
        st.caption("Your CV text is sent to the Groq API for analysis. Nothing is saved by ScholarHunter.")
    extra_list = [c.strip() for c in extra.split(",") if c.strip()]
    return go, {"file": uploaded, "countries": list(dict.fromkeys(countries + extra_list)),
                "department": department.strip(), "level": LEVELS[level], "funding": funding}


def run_analysis(form: dict) -> None:
    errors = []
    if form["file"] is None:
        errors.append("Upload your CV (PDF, DOCX, TXT or RTF).")
    if not form["department"]:
        errors.append("Enter your department or major.")
    if not form["countries"]:
        errors.append("Select at least one country, or choose “Any country”.")
    if errors:
        for e in errors:
            st.warning(e)
        return
    box = st.container()
    bar, log, lines = box.progress(0.0, text="Starting…"), box.empty(), []

    def progress(frac: float, msg: str) -> None:
        lines.append(msg)
        bar.progress(min(max(frac, 0.0), 1.0), text=msg)
        log.markdown("\n\n".join(lines))

    try:
        cv_text = parse_cv(form["file"].getvalue(), form["file"].name)
        from sh_app.core.crew import ScholarHunterCrew, StageError  # lazy: keeps first paint fast
        prefs = SearchPreferences(countries=form["countries"], department=form["department"],
                                  degree_level=form["level"], funding_type=form["funding"])
        crew = ScholarHunterCrew(get_settings())
        report = crew.run(cv_text, prefs, progress)
        st.session_state["report"] = report.model_dump(mode="json")
        box.empty()
    except MissingAPIKeyError as exc:
        box.empty()
        st.error(f"{exc}  See the README → “Secrets”.")
    except CVParseError as exc:
        box.empty()
        st.error(str(exc))
    except Exception as exc:  # StageError, LLM errors, anything unexpected
        box.empty()
        logger.error("Run failed: %s", type(exc).__name__)
        msg = str(exc) if exc.__class__.__name__ in {"StageError", "LLMCallError"} else \
            "Something went wrong while analysing. Please try again in a minute."
        st.error(msg)


# ---------------------------------------------------------------- rendering helpers
def bullets(items: list[str], empty: str = "Information unavailable") -> None:
    if not items:
        st.caption(empty)
        return
    st.markdown("\n".join(f"- {i}" for i in items))


def flag_for(country: str) -> str:
    return FLAGS.get((country or "").lower().strip(), "🌍")


def card_html(s, m) -> str:
    status = s.deadline_status
    cls = {"CLOSING_SOON": "soon", "UNKNOWN": "unk"}.get(status, "")
    if s.deadline_iso:
        when = f"📅 Deadline: {esc(s.deadline)}<br>⏳ {s.days_remaining} days remaining"
    elif s.deadline == "Rolling":
        when = "📅 Deadline: Rolling admissions"
    else:
        when = f"📅 Deadline: {esc(s.deadline or 'Not verified')}<br>⚠️ Deadline could not be independently verified."
    badge_status = {"OPEN": ("ok", "Open"), "CLOSING_SOON": ("warn", "Closing soon"),
                    "UNKNOWN": ("gray", "Deadline unknown")}[status]
    ver = ('<span class="sh-badge ok">🟢 Verified (official source)</span>' if s.verified
           else '<span class="sh-badge warn">🟡 Not verified on an official page</span>')
    mc, icon = MATCH_BADGE.get(m.category if m else "Insufficient Information")
    match = f'<span class="sh-badge {mc}">{icon} {esc(m.category if m else "No assessment")}</span>'
    if s.official_url and is_valid_url(s.official_url):
        link = f'<a class="sh-btn" href="{esc(s.official_url)}" target="_blank" rel="noopener noreferrer">View official scholarship</a>'
    elif s.source_url and is_valid_url(s.source_url):
        link = (f'<a class="sh-btn alt" href="{esc(s.source_url)}" target="_blank" rel="noopener noreferrer">'
                "View source (not verified as official)</a>")
    else:
        link = '<span class="sh-badge gray">Official URL not verified</span>'
    return (f'<div class="sh-card {cls}"><p class="sh-title">🎓 {esc(s.scholarship_name)}</p>'
            f'<p class="sh-sub">{esc(s.university or "University not verified")} · {flag_for(s.country)} {esc(s.country or "Country not verified")}</p>'
            f'<div class="sh-row">{esc(s.degree_level or "Level n/a")} • {esc(s.field or "Field not verified")}</div>'
            f'<div class="sh-row">💰 {esc(s.funding_type)}{": " + esc(s.funding_details) if s.funding_details else ""}</div>'
            f'<div class="sh-row">{when}</div>'
            f'<div class="sh-row"><span class="sh-badge {badge_status[0]}">{badge_status[1]}</span>{ver}{match}</div>{link}</div>')


def render_details(e: ScholarshipEntry) -> None:
    s, m, p = e.scholarship, e.match, e.plan
    with st.expander(f"Details: {s.scholarship_name}"):
        st.markdown(f"**Eligibility:** {s.eligibility or 'Information unavailable'}")
        st.markdown(f"**Application requirements:** {s.application_requirements or 'Information unavailable'}")
        st.caption(f"Verification: {s.verification_notes or 'n/a'} {s.deadline_note}")
        if s.source_url:
            st.caption(f"Source: {s.source_url}")
        if m:
            st.markdown("**Match assessment** (AI-assisted)")
            st.write(m.match_summary or "No summary.")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("✅ *Matching requirements*")
                bullets(m.matching_requirements)
                st.markdown("⚠️ *Potential concerns*")
                bullets(m.potential_concerns)
            with c2:
                st.markdown("❌ *Missing requirements*")
                bullets(m.missing_requirements)
                st.markdown("➡️ *Recommended actions*")
                bullets(m.recommended_actions)
        if p:
            st.markdown("**Application plan**")
            st.write(p.why_match)
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("*Documents likely required*")
                bullets(p.documents_required)
                st.markdown("*Preparation checklist*")
                bullets(p.preparation_checklist)
                st.markdown("*Suggested timeline*")
                bullets(p.suggested_timeline)
            with c2:
                st.markdown("*Research positioning*")
                bullets(p.research_positioning)
                st.markdown("*Professor contact*")
                bullets(p.professor_contact)
                st.markdown("*SOP & recommendation letters*")
                bullets(p.sop_suggestions + p.recommendation_letters)


def render_snapshot(r: ScholarHunterReport) -> None:
    c = r.candidate
    edu = ", ".join(x for x in (c.degree, c.university, c.graduation_year, f"GPA {c.gpa}" if c.gpa else "") if x)
    cards = [("🎓 Education", edu or "Not found in CV"),
             ("💼 Experience", "; ".join((c.experience + c.internships)[:3]) or "Not found in CV"),
             ("🧠 Skills", ", ".join((c.skills + c.programming_languages)[:10]) or "Not found in CV"),
             ("🔬 Research areas", ", ".join(c.research_interests[:6]) or "Not found in CV"),
             ("📜 Certifications", "; ".join(c.certifications[:4]) or "None listed")]
    st.subheader("Candidate snapshot")
    for col, (t, body) in zip(st.columns(5), cards):
        col.markdown(f'<div class="sh-snap"><b>{t}</b><span>{esc(body)}</span></div>', unsafe_allow_html=True)


def render_metrics(entries: list[ScholarshipEntry]) -> None:
    m = compute_metrics(entries)
    for col, (label, key) in zip(st.columns(5), [("Scholarships found", "found"), ("Verified opportunities", "verified"),
                                                 ("Fully funded", "fully_funded"), ("Strong matches", "strong"),
                                                 ("Closing soon", "closing_soon")]):
        col.metric(label, m[key])


def filter_entries(entries: list[ScholarshipEntry]) -> list[ScholarshipEntry]:
    with st.expander("🎚️ Filters", expanded=True):
        a, b, c = st.columns(3)
        countries = a.multiselect("Country", sorted({e.scholarship.country for e in entries if e.scholarship.country}))
        degrees = b.multiselect("Degree", sorted({e.scholarship.degree_level for e in entries if e.scholarship.degree_level}))
        funding = c.multiselect("Funding type", sorted({e.scholarship.funding_type for e in entries}))
        d, e2, f = st.columns(3)
        match = d.multiselect("Match category", ["Strong Match", "Potential Match", "Needs Improvement", "Insufficient Information"])
        deadline = e2.selectbox("Deadline", ["Any", "Within 30 days", "Within 90 days", "Known date only"])
        verified_only = f.checkbox("Verified only", value=False)
        open_only = f.checkbox("Show only currently open scholarships", value=True,
                               help="Hides scholarships whose deadline could not be verified.")
    out = []
    for e in entries:
        s = refreshed(e.scholarship)
        days = s.days_remaining
        if open_only and s.deadline_status not in {"OPEN", "CLOSING_SOON"}:
            continue
        if (countries and s.country not in countries) or (degrees and s.degree_level not in degrees):
            continue
        if funding and s.funding_type not in funding:
            continue
        if match and (e.match.category if e.match else "Insufficient Information") not in match:
            continue
        if verified_only and not s.verified:
            continue
        if deadline == "Within 30 days" and not (days is not None and days <= 30):
            continue
        if deadline == "Within 90 days" and not (days is not None and days <= 90):
            continue
        if deadline == "Known date only" and days is None:
            continue
        out.append(ScholarshipEntry(scholarship=s, match=e.match, plan=e.plan))
    return out


def render_match_dashboard(entries: list[ScholarshipEntry]) -> None:
    st.subheader("Your profile match")
    st.caption("AI-assisted assessment — rough indicators, not scientifically validated probabilities.")
    scored = [e.match for e in entries if e.match and any(vars(e.match.fit_scores).values())]
    if not scored:
        st.info("No match scores available for the current selection.")
        return
    for label, attr in FIT_LABELS.items():
        avg = round(sum(getattr(m.fit_scores, attr) for m in scored) / len(scored))
        st.progress(avg / 100, text=f"{label}: {avg}/100")
    st.markdown("**Per scholarship**")
    for e in entries:
        if e.match:
            icon = MATCH_BADGE[e.match.category][1]
            st.markdown(f"- {icon} **{e.scholarship.scholarship_name}** — {e.match.category}. {e.match.match_summary}")


def render_gap(r: ScholarHunterReport) -> None:
    a = r.profile_assessment
    st.header("🧩 CV Gap Analysis")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### Strengths")
        bullets(a.strengths)
    with c2:
        st.markdown("### Gaps")
        bullets(a.gaps)
    with c3:
        st.markdown("### Recommended improvements")
        bullets(a.recommendations)
    if a.missing_information:
        st.markdown("**Information missing from your CV**")
        bullets(a.missing_information)


def render_roadmap(r: ScholarHunterReport, entries: list[ScholarshipEntry]) -> None:
    st.header("🗺️ Application Roadmap")
    dated = sorted((e.scholarship for e in entries if e.scholarship.days_remaining is not None),
                   key=lambda s: s.days_remaining)
    if dated:
        s = dated[0]
        st.info(f"Nearest verified deadline: **{s.scholarship_name}** — {s.deadline} ({s.days_remaining} days). "
                "Start with the steps below and work backwards from this date.")
    steps = [(x.title, x.details + (f" ({x.timeframe})" if x.timeframe else "")) for x in r.application_strategy.roadmap
             if x.title] or DEFAULT_ROADMAP
    for i, (title, details) in enumerate(steps, 1):
        st.markdown(f'<div class="sh-step"><b>Step {i}: {esc(title)}</b><br>{esc(details)}</div>', unsafe_allow_html=True)
        if i < len(steps):
            st.markdown('<div class="sh-arrow">↓</div>', unsafe_allow_html=True)


def render_strategy(r: ScholarHunterReport) -> None:
    s = r.application_strategy
    st.header("🧭 Application strategy")
    for title, items in [("Priority actions", s.priority_actions), ("Documents to prepare", s.documents_to_prepare),
                         ("Research preparation", s.research_preparation), ("SOP preparation", s.sop_preparation),
                         ("Recommendation letters", s.recommendation_letter_preparation),
                         ("Professor-contact strategy", s.professor_contact_strategy)]:
        with st.expander(title, expanded=title == "Priority actions"):
            bullets(items, "Not generated for this run")


def render_empty() -> None:
    st.warning("No currently verifiable open scholarships matched your criteria.")
    st.markdown("Try one of these:\n- Broaden the country selection or choose “Any country”\n- Use a broader major\n"
                "- Change the degree level\n- Allow partially funded opportunities\n- Try again later")


def render_results(r: ScholarHunterReport) -> None:
    active = [ScholarshipEntry(scholarship=refreshed(e.scholarship), match=e.match, plan=e.plan)
              for e in r.scholarships if refreshed(e.scholarship).deadline_status != "EXPIRED"]
    render_snapshot(r)
    if r.executive_summary:
        st.markdown(f"> {r.executive_summary}")
    for w in r.warnings:
        st.caption(f"⚠️ {w}")
    st.info(DISCLAIMER)
    render_metrics(active)
    t1, t2, t3, t4, t5 = st.tabs(["🎯 Opportunities", "📊 Profile match", "🧩 CV gaps", "🗺️ Roadmap", "🧭 Strategy"])
    with t1:
        if not active:
            render_empty()
        else:
            shown = filter_entries(active)
            st.caption(r.ranking_note)
            if not shown:
                st.warning("No scholarships match the current filters.")
            for e in shown:
                st.markdown(card_html(e.scholarship, e.match), unsafe_allow_html=True)
                render_details(e)
    with t2:
        render_match_dashboard(active)
    with t3:
        render_gap(r)
    with t4:
        render_roadmap(r, active)
    with t5:
        render_strategy(r)
    st.download_button("⬇ Download Scholarship Report", data=to_json(r), file_name="scholarhunter_report.json",
                       mime="application/json")


def render_welcome() -> None:
    st.markdown("### How it works")
    cols = st.columns(3)
    texts = [("1 · Upload & choose", "Add your CV, countries, field, degree level and funding preference in the sidebar."),
             ("2 · Agents search & verify", "Seven agents read your CV, search free public sources, and check every deadline against today's date."),
             ("3 · Review your fit", "See verified open scholarships, match details, CV gaps, a roadmap and a downloadable report.")]
    for col, (t, b) in zip(cols, texts):
        col.markdown(f'<div class="sh-snap"><b>{t}</b><span>{b}</span></div>', unsafe_allow_html=True)
    st.info(DISCLAIMER)


def main() -> None:
    init_state()
    inject_css()
    render_header()
    go, form = sidebar()
    if go:
        run_analysis(form)
    if st.session_state["report"]:
        try:
            render_results(ScholarHunterReport.model_validate(st.session_state["report"]))
        except Exception as exc:
            logger.error("Render failed: %s", type(exc).__name__)
            st.error("The saved results could not be displayed. Please start a new search.")
    else:
        render_welcome()


main()
