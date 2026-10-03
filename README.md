# ScholarHunter Agents

A Streamlit + CrewAI multi-agent scholarship research assistant using Groq GPT-OSS 120B, DuckDuckGo search, Pydantic contracts and Excel export.

## Architecture

1. Profile Analyst -> CandidateProfile
2. Opportunity Scout -> DuckDuckGo, maximum 5 queries
3. Database Architect + Gap Mentor -> scholarship records + skill gaps
4. Progress Tracker -> deterministic urgency/status logic + short LLM summary

Agent handoffs use Pydantic models. Search results are cached in `data/search_cache.json`.

## Local setup

Python 3.11 is recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

Set `GROQ_API_KEY`, then:

```bash
streamlit run app.py
```

## Streamlit Cloud

Push the repository to GitHub. In Streamlit Cloud, deploy `app.py` and add:

`GROQ_API_KEY = "..."`

under App settings -> Secrets.

## Important

Scholarship deadlines and funding details can change. The app intentionally leaves unsupported deadlines null and displays a verification reminder. Do not treat fit scores as admissions decisions.

The DuckDuckGo package is now published as `ddgs`; the older `duckduckgo-search` package name is deprecated/renamed.
