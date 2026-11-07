# Apropos — procurement policy chatbot (prototype)

Answers questions about the 2025 invoices and policy FIN-POL-014 v3.2. Every figure comes from a backend
tool call, and every policy statement carries a citation. Full README (Docker quickstart, design decisions,
known limitations) is phase 5; this file covers running it locally.

## Run locally

Needs Python 3.12 and Node 20. Put your key in `.env` (copy `.env.example`; `.env` is gitignored):

```
ANTHROPIC_API_KEY=sk-ant-...
MODEL=claude-sonnet-5-5
```

```bash
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn backend.main:app --port 8000      # open http://localhost:8000
```

Dev mode with hot reload: `uvicorn backend.main:app --reload` plus `cd frontend && npm run dev`
(http://localhost:5173, which proxies `/api` to port 8000).

## Tests

```bash
pytest tests                                                    # offline, no API key needed
python tests/run_evals.py                                       # 21 live evals (uses the API)
python tests/run_evals.py --routing --md ROUTING_TEST_RESULTS.md  # the 5 policy+data routing questions
```

FX rates: `data/fx_rates.csv` comes from the ECB Data Portal (series `EXR.D.{USD,GBP}.EUR.SP00.A`, 2025,
fetched 2026-11-07 by `scripts/fetch_fx.py`) and is committed so the app runs offline.
