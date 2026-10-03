import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from crewai import Agent, Crew, Process, Task, LLM
from pydantic import BaseModel

from schemas import (
    CandidateProfile, RawResult, RawResults,
    ScholarshipRecord, ScholarshipRecords, GapReport, TrackerSummary
)
from tools import ddg_search

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

def make_llm():
    # CrewAI uses LiteLLM-compatible model routing for Groq.
    return LLM(
        model=f"groq/{MODEL}",
        api_key=os.environ["GROQ_API_KEY"],
        temperature=0.1,
        max_tokens=2500,
    )

def _agent(role, goal, backstory):
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=make_llm(),
        verbose=False,
        allow_delegation=False,
    )

def _run(task, agent, model_cls, retries=1):
    last_error = ""
    for attempt in range(retries + 1):
        instruction = task + (f"\nPrevious validation error: {last_error}\nReturn corrected JSON only." if last_error else "")
        t = Task(description=instruction, expected_output="Valid JSON matching the required Pydantic schema.", agent=agent, output_pydantic=model_cls)
        try:
            result = Crew(agents=[agent], tasks=[t], process=Process.sequential, verbose=False).kickoff()
            obj = getattr(result, "pydantic", None)
            if obj is not None:
                return obj
            raw = getattr(result, "raw", str(result))
            return model_cls.model_validate_json(raw)
        except Exception as e:
            last_error = str(e)
            time.sleep(1.5 * (attempt + 1))
    return None

def profile_agent(cv_text, interests, domain, level, countries):
    a = _agent(
        "Academic Profile Analyst",
        "Convert stated CV facts and user inputs into a precise, search-ready candidate profile.",
        "You extract only explicit facts. Never invent missing qualifications, scores, publications or experience."
    )
    prompt = f"""
Create CandidateProfile from the following information.

CV:
{cv_text[:18000]}

Research interests: {interests}
Target domain: {domain or "null"}
Target level: {level}
Countries: {countries}

Rules:
- Extract only what is stated.
- Unknown fields must be null.
- keywords must contain 8-12 useful search terms.
- Do not write prose outside the JSON object.
"""
    out = _run(prompt, a, CandidateProfile, 1)
    if out:
        return out
    return CandidateProfile(
        degree="Unknown", field="Unknown", target_level=level,
        target_domain=domain, countries=countries, keywords=[]
    )

def build_queries(profile):
    level = profile.target_level
    domain = profile.target_domain or " ".join(profile.research_pillars[:2]) or "research"
    countries = profile.countries or ["international"]
    kw = profile.keywords[0] if profile.keywords else domain
    q = [
        f"fully funded {level} scholarship {domain} {countries[0]} 2026 2027",
        f"{countries[min(1, len(countries)-1)]} government scholarship international students {level}",
        f"{kw} funded PhD position open",
        f"{domain} fellowship stipend {countries[0]} deadline",
        f"scholarships for international students {level}",
    ]
    return q[:5]

def scout_agent(profile):
    # Agent 2 is responsible for research strategy; actual HTTP search is
    # deterministic Python so the five-query hard cap cannot be bypassed.
    queries = build_queries(profile)
    raw = ddg_search(queries, max_queries=5, max_results=5)
    return queries, [RawResult(**x) for x in raw]

def _records_batch(profile, batch):
    a = _agent(
        "Database Architect",
        "Convert search evidence into accurate ScholarshipRecord objects.",
        "You normalize scholarship data. Deadlines must never be guessed. Official URLs are preferred."
    )
    evidence = json.dumps([x.model_dump() for x in batch], ensure_ascii=False)
    prompt = f"""
Candidate context:
{profile.model_dump_json()}

Search evidence:
{evidence}

Extract only scholarships supported by the evidence.
Rules:
- official_link must be a real URL from the evidence.
- Never guess a deadline. Use null when unsupported.
- confidence is high only when evidence strongly supports the record.
- Prefer .edu, .gov, .ac or official programme domains.
- Do not invent requirements.
Return ScholarshipRecords JSON only.
"""
    out = _run(prompt, a, ScholarshipRecords, 1)
    return out.records if out else []

def _gaps_batch(profile, records):
    a = _agent(
        "Admissions Gap Mentor",
        "Identify honest preparation gaps for each scholarship.",
        "You give practical, evidence-based advice without inventing requirements."
    )
    prompt = f"""
Candidate:
{profile.model_dump_json()}

Scholarships:
{json.dumps([r.model_dump() for r in records], ensure_ascii=False)}

Return GapReport.
For each scholarship, compare the stated candidate profile with the stated scholarship requirements.
Do not claim a missing item unless the record requires it.
Keep recommendations actionable and estimate preparation time.
"""
    out = _run(prompt, a, GapReport, 1)
    return out or GapReport()

def database_and_gap(profile, raw_results):
    # 3-4 search results per batch; record extraction and gap analysis are
    # independent workers and run concurrently.
    batches = [raw_results[i:i+4] for i in range(0, len(raw_results), 4)]
    records, reports = [], []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(batches)*2))) as ex:
        futures = []
        for b in batches:
            futures.append(ex.submit(_records_batch, profile, b))
        for f in as_completed(futures):
            try:
                records.extend(f.result())
            except Exception:
                pass

    # Gap analysis receives normalized records, also in small batches.
    gap_batches = [records[i:i+4] for i in range(0, len(records), 4)]
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(gap_batches)))) as ex:
        futures = [ex.submit(_gaps_batch, profile, b) for b in gap_batches]
        for f in as_completed(futures):
            try:
                reports.append(f.result())
            except Exception:
                pass

    # Deduplicate scholarships by official URL.
    unique = {}
    for r in records:
        unique.setdefault(r.official_link, r)
    records = list(unique.values())

    merged = GapReport()
    for rep in reports:
        merged.overall_strengths.extend(rep.overall_strengths)
        merged.common_gaps.extend(rep.common_gaps)
        merged.per_scholarship.extend(rep.per_scholarship)

    merged.overall_strengths = list(dict.fromkeys(merged.overall_strengths))
    merged.common_gaps = list(dict.fromkeys(merged.common_gaps))
    merged.per_scholarship = list({x.scholarship_name: x for x in merged.per_scholarship}.values())
    return records, merged

def fit_score(profile, record):
    text = " ".join([
        record.scholarship_name, record.provider or "", record.level or "",
        record.funding or "", " ".join(record.requirements)
    ]).lower()
    keys = set(k.lower() for k in profile.keywords)
    score = 0
    score += min(45, sum(1 for k in keys if k and k in text) * 10)
    if profile.target_domain and profile.target_domain.lower() in text:
        score += 20
    if profile.target_level.lower() in (record.level or "").lower():
        score += 15
    elif profile.target_level == "Any":
        score += 10
    if any(c.lower() in (record.country or "").lower() for c in profile.countries):
        score += 20
    return min(100, score)

def tracker_summary(rows):
    from tracker import summary
    s = summary(rows)
    a = _agent(
        "Progress Tracker",
        "Write a short weekly priorities summary from deterministic tracker metrics.",
        "Be concise. Mention urgent deadlines and status counts. Never invent deadlines."
    )
    prompt = f"Write one short weekly priorities summary for these metrics: {json.dumps(s)}"
    out = _run(prompt, a, TrackerSummary, 1)
    return out.summary if out else f"{s['critical']} critical deadlines; {s['remaining']} remaining."
