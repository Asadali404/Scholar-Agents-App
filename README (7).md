# 🎓 ScholarHunter

AI-powered, multi-agent scholarship discovery. ScholarHunter reads your CV, searches free public sources for
scholarships, **verifies deadlines against today's date**, assesses your fit, finds CV gaps and builds an
application plan. Built with Streamlit + CrewAI + Groq (`openai/gpt-oss-120b`).

## Features
- Multi-agent scholarship discovery (7 CrewAI agents, sequential)
- CV analysis (PDF, DOCX, TXT, RTF – processed in memory only)
- Free web search (DuckDuckGo via `ddgs`, no paid APIs)
- Deadline verification – expired scholarships are never shown
- Scholarship matching with transparent strengths/gaps
- CV gap analysis, application strategy and roadmap
- JSON export, filters, metrics and a polished dashboard

## Architecture
| # | Agent | Role |
|---|-------|------|
| 1 | CV Analyst | Structured candidate profile from the CV |
| 2 | Scholarship Researcher | Extracts facts from *fetched page text* (search itself is plain Python) |
| 3 | Scholarship Verifier | LLM consistency check; date/URL/name checks are enforced in code |
| 4 | Profile Matcher | Compatibility assessment per scholarship |
| 5 | CV Improvement Advisor | CV gaps vs. requirements found |
| 6 | Application Strategist | Per-scholarship plans + overall roadmap |
| 7 | Scholarship Report Generator | Executive summary; report is assembled deterministically |

`search → fetch → extract (LLM) → validate (code) → dedupe → verify (LLM can only downgrade) → match → plan → report`.
The LLM never supplies URLs or deadlines on its own: every URL must come from real search results/page links and every
deadline must be found in the page text.

## Installation (optional, local development)
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit the key
streamlit run app.py
```

## Environment variables / secrets
| Name | Required | Default |
|------|----------|---------|
| `GROQ_API_KEY` | yes | – |
| `LLM_MODEL` | no | `openai/gpt-oss-120b` |
| `LLM_FALLBACK_MODELS` | no | `openai/gpt-oss-20b` |
| `MAX_PAGES`, `MAX_RESULTS`, `MAX_QUERIES`, `RESULTS_PER_QUERY`, `MAX_OUTPUT_TOKENS` | no | 12, 12, 10, 8, 3000 |

## Streamlit Community Cloud deployment
1. Push this repository to GitHub (the real `secrets.toml` and any CVs are git-ignored).
2. Open https://share.streamlit.io and click **Create app**.
3. Choose your GitHub repository, branch `main`, main file `app.py`.
4. In **Advanced settings** choose Python 3.12 and paste your secrets (below).
5. Click **Deploy**.

## Secrets
App → **Settings → Secrets**:
```toml
GROQ_API_KEY = "your-groq-api-key"
```

## Troubleshooting: `PermissionDeniedError` (HTTP 403) from Groq
The app now shows Groq's real error message. Use the sidebar **🔌 Troubleshooting → Test Groq connection** button.
Typical causes and fixes:
- **Model blocked for your org/project** – console.groq.com → Settings → Limits → enable `openai/gpt-oss-120b`
  (check both *Organization* and *Project*). Until then the app falls back to the models in `LLM_FALLBACK_MODELS`.
- **API key from a different project/org** – create a new key at console.groq.com/keys and update Secrets.
- **Restricted account, VPN/proxy or blocked network** – use a normal connection or contact Groq support.
- Secrets must look exactly like `GROQ_API_KEY = "gsk_..."` (the app strips stray quotes/spaces).

## Important limitations
- Results depend on publicly accessible websites; some university sites block automated requests.
- Always confirm deadlines and eligibility on the official website before applying.
- AI assessments and scores are advisory, not scientifically validated.
- Unknown deadlines are never treated as confirmed open deadlines: they are labelled “Deadline unknown / not verified”, shown after confirmed ones, and can be hidden with the *confirmed open deadline* filter. Expired scholarships are always removed.
- Every run has a **🛠️ Run details** panel showing counts per step (search → pages → AI extraction → validation) so you can see exactly where results were lost.
- Free Groq tiers have rate limits; a run may pause and retry. Reduce `MAX_PAGES` if you hit limits.
- Your CV text is sent to Groq for analysis; ScholarHunter itself stores nothing.
