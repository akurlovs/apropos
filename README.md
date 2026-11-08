# Apropos: procurement policy chatbot (prototype)

Answers questions about invoices and procurement policy FIN-POL-014 v3.2. Figures come from the data and are checked, policy statements are cited, and anything the data can't show is reported as "not determinable". This is a prototype, not a production system. How it was built: [process.md](process.md).

## Run it

Needs Docker and an Anthropic API key. The image builds on your machine, so nothing else needs installing.

```bash
cp .env.example .env                      # then add your key to .env
docker compose up --build                 # http://localhost:8000
```

**New data:** add or replace `data/invoices_YYYY_clean.csv`, then:

```bash
docker compose run --rm --user "$(id -u):$(id -g)" apropos python scripts/fetch_fx.py   # exchange rates first
docker compose restart
```

**Without Docker** (Python 3.12, Node 20):

```bash
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn backend.main:app --port 8000
```

**Tests** use the frozen data in `tests/fixtures/`. Install `backend/requirements-dev.txt`, then run `pytest tests` (offline) and `python tests/run_evals.py` (live; uses the API, `--repeat N` for pass rates).

The Docker setup was tested from a clean copy of the repo on an Intel Mac. Other platforms are expected to work but weren't tested.

## Backend (FastAPI, in-memory DuckDB, Anthropic SDK)

| File | Role |
|---|---|
| `db.py` | Rebuilds the database from the CSVs at startup: validates rows, converts to EUR at ECB rates |
| `contract.py` | The fixed schema and policy; a change blocks all figures rather than loading wrong data |
| `rules.py` | Deterministic policy flags (§2.2, §3.1, §4.1, §6.1) and approval levels |
| `clauses.py` | One entry per policy clause: what the data can check and what's missing |
| `tools.py` | The lookups the model can call, shared with the summary panel; records what ran |
| `llm.py`, `prompts.py` | Tool loop, citations, system prompt |
| `checks.py` | Checks on each finished answer; problems appear as warnings |
| `main.py` | `/api/health`, `/api/status`, `/api/summary`, `/api/invoices`, `/api/ask` |

## Frontend (React, Vite, TypeScript)

Chat with answer cards, a summary panel, and a per-invoice conversion table with CSV export. Header controls set period, currency and approver scope. Each answer shows policy citations, "not determinable" chips, warnings, and "How this was computed": the policy and data steps in the order they happened.

## Key choices

| Choice | Why |
|---|---|
| Rebuild from CSVs on each start | The CSVs stay the source of truth, so corrections, late FX rates and flags update themselves. Fast at this size; new data needs a restart |
| Data grows, shape doesn't | New rows and yearly files just work. A schema, policy or vendor-status change is a redesign, so it's enforced in code |
| Whole policy in context, cited per clause | It fits in one cached prompt, so keyword routing would only add a way to fail |
| Clause tools first, read-only SQL as fallback | Routing over a closed set of tested functions; free-form queries are the riskiest path |
| Sources come from the system | Citations, data lineage and "not determinable" are recorded by the backend. The one model-written step, "Rule being checked", is labelled as such |
| "Not determinable" over inference | No payment, requester, PO-date or exception data exists, so the bot names what's missing |
| Pattern checks on answers, not a second model | Cheap and predictable; tuned to avoid false alarms, which undermine trust |
| Answers in finance language | Technical detail stays in the trace |
| Gross, credit notes and net shown separately | Netting silently would hide credit notes |
| Quarters always carry a year; default is the latest year, labelled | "Q1" is ambiguous once there are two years |
| No usable FX rate means "pending" | Invoices stay visible but out of EUR totals; a stale rate would look correct and be wrong |
| Evals against independent pandas figures | Testing the app against its own functions would be circular |

## What we did not address

**Production** (outlined only, not built):
- **Access:** single sign-on and roles, with visibility enforced in the data layer. There is no login today, and the system prompt contains real sample rows.
- **Audit (§8):** an append-only record of each answer, kept 10 years with data snapshots. The trace currently reaches only the browser. §8.2 also puts the app under SOX-equivalent change control.
- **Data:** Snowflake behind the same named views, incremental loads, live refresh, paging.
- **Privacy:** invoice data and approver names go to the model provider, which needs legal review, including GDPR against 10-year retention.
- **Scale and cost:** multiple instances and per-user limits (today's limit is 10 per minute per IP). Model cost was about 2–3 cents per question in testing; infrastructure and control work would likely cost more.
- **Quality:** a finance-built test set, answer sampling, and a second-model grader or backend-filled numbers.

**Known limitations:**
- **Not determinable from the data:** §1 scope, §2.1 PO timing, §2.3 blanket POs, §3 approver roles, §4.2, §4.3, §5.2 payment terms, §6.1 matching, §7 requester and self-approval, §8.1, §9 exceptions, and whether anything was paid.
- **Answer checks** catch invented details and dropped caveats, not wrong reasoning over real figures.
- **Free-form SQL** (the fallback) doesn't get the default period or approver filter automatically; the model is told to apply them.
- **Vendor status** is a current snapshot, so past status can't be known.
- **§2.3:** blank POs on recurring services stay flagged, marked as possible blanket-PO cases.
- **Our interpretations:** ≥ EUR 1,000 for the PO threshold (§2.1 and §2.2 differ); weekends and holidays use the previous ECB rate; calendar quarters; credit notes left out of thresholds and approval levels.
- **Cost center owners** aren't named in the data.
- **Current-year figures** can move when a file is replaced; the load log shows that a file changed, not what changed.

## About the process

My first step was to take a close look at the data and the policy and come up with a prompt to Claude that took my concerns into consideration (the process.md file outlines the workflow and key prompts). My main goal was to address the big things such as potential hallucinations resulting from ambiguities in the policy and the data, as well as requirements that the data does not meet. One that immediately stood out to me was the requirement to report monetary totals in Euros in §5.1. Since I did not find it practical to query a conversion API each time, the approach i took was to download conversion rates for the dates in question. This resulted in the "Report currency" drop-down in the app. Another key ambiguity came from 3.1 "Invoices lacking an approver record must be held and may not be paid." Had they actually been paid? I made the decision to include the "Exclude invoices without approver record (§3.1 holds)" checkbox in the app for the totals as a result. Blank POs provided another source of ambiguity. An invoice with no PO is flagged under 2.2, but 2.3 allows recurring services to run under blanket POs, which are undefined. Even though 10 of the 21 invoices with no PO are for cloud hosting or facilities, the two services 2.3 names, I decided to keep all 21 flagged, mark those 10 as possible blanket-PO cases, and have the chatbot state the ambiguity. I also instructed Claude to use backend/tools.py as much as possible so that the answers could be based on pre-existing functions as much as possible to reduce the chance of hallucinations.

The primary goal of my first pass was to build a prototype that accurately produces documented outputs based on the CSVs. This means that i deliberately excluded some of the downstream considerations that are beyond the scope of the prototype. For example, the data flow / ETL pipeline is still not defined here. Who cleans the CSVs? How often do they come in? Is there a CSV per year (like there is for 2025)? None of these questions are answered in the current setup. The current app is based on the assumption that CSVs are per year (it says "2025" in the name), are clean, and have the same schema. The main potential future issue i accounted for is getting invoices from 2026 and beyond -- this is why the period drop-down exists even though only 2025 data has been provided so far. However, as the ETL questions remained unanswered, i did not take the liberty of designing some future-proof prototype, which will likely involve a Snowflake or other SQL style database with hopefully more information in the schema. As an example, it is not clear as of right now when a particular vendor was placed on hold. I would also likely develop an automatic converter from GBP/USD/etc to Euro before even loading to Snowflake, to avoid loading conversion tables; the rate and the date of conversion would also be included in the table in Snowflake.

Other questions that i did not address at this point are privacy and access, simply because they are beyond the scope of the prototype and because they depend on the organization. As an example, since no instructions were given otherwise, the app will readily show you the name of the approver. Does this break the privacy of the approver? Maybe. But I would want a clearer understanding of policy before committing to a decision in this situation. Maybe some analysts should be privy to this data while others are not? These questions cannot be answered based on the information I have in front of me at the moment and should be solved as they come in. The total monthly cost for a simple Snowflake-based setup with 100 questions/day is estimated by Claude based on tests to be within $500 (model cost from our tests, Snowflake compute from typical pricing, but does not include security and maintenance personnel).

Claude has conducted extensive tests, and there is a whole suite of tests in the eponymous directory. I instructed Claude to generate five tricky questions from the beginning (outputs in ROUTING_TEST_RESULTS.md), and then Claude has run extensive testing and verification of each major change using a variety of questions. In the future, this can be done in a multi-agent system where an independent agent verifies the results produced by the first, as well as in collaboration with financial analysts using the data. Currently, guardrails exist to reduce the chance of the chatbot making stuff up by always deferring to either the CSVs (for example, that invoice numbers are real) or policy clauses, and by explicitly stating when the answer cannot be determined from the information provided.
