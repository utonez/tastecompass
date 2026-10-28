# TasteCompass

**An agent that matches your taste to UK cities and master's programmes, checks official fees and deadlines, and plans your application.** Built for the Qloo Agentic Hackathon 2026.

Most study-abroad advice ranks universities. TasteCompass also asks the question students actually live with for a year: *will I like living there?* It reads your taste in music, films, food and hobbies through Qloo, scores every major UK student city on one taste map, then combines that with academic fit, budget and English requirements, using programme facts checked on official course pages.

- **Live demo:** https://tastecompass.onrender.com (homepage) · https://tastecompass.onrender.com/app (agent)
- Hosted on a free plan: if it has been idle, the first load can take up to a minute while the server wakes up.
- **Homepage:** `/` · **Agent UI:** `/app`

## Why an agent, and why Qloo

A general chatbot answers from memory: last year's deadlines, no sources, generic city descriptions. TasteCompass plans which tools to call from what you have already decided, and only reports facts it can source.

| | General chatbot | TasteCompass |
| --- | --- | --- |
| Fees and deadlines | From training data, often out of date, no source | From the official course page, with link and date checked |
| Missing data | Plausible guess | Marked *unverified*, scored neutral |
| City fit | Generic adjectives | Your tastes scored on Qloo's taste graph across 24 major student cities |
| Your constraints | Drift during the chat | Hard filters; better options outside them shown separately |
| Next steps | Generic checklist | Dated timeline worked back from the next open round, exportable to calendar |

**What Qloo does here** (without it, the product would not work):

1. **Understands your taste** - `/search` (restricted to works and people) and `/v2/tags` map each interest to a Qloo entity or tag. *Radiohead* becomes an artist entity; *hiking* becomes an activity tag.
2. **Compares cities on one scale** - one `/v2/insights` call with `filter.type=urn:heatmap` over the whole UK; each city's score is the mean affinity within 10 km of its centre. Per-city place affinities are ranked within each city, so they can't be compared; the national heatmap can.
3. **Shows what you'd love there** - `/v2/insights` places per city, filtered to the city itself and cleaned of national chains, become the "You'd like in…" list and a first-week plan.

## How it works

```
your scope ─┐                       ┌─ official course data (data/programs.json)
your tastes ├─► Qloo: search/tags ─► UK heatmap ─► city taste ─┐
weights ────┘                                                   ├─► Fit score ─► ranking ─► dated plan
                                                academic, budget, language ─┘
```

`Fit = w_taste·taste + w_academic·academic + w_budget·budget + w_language·language` (default 0.35 / 0.35 / 0.20 / 0.10, adjustable with sliders).

**Scope modes** - whatever you have decided becomes a hard filter:

| Mode | Decided | The agent… |
| --- | --- | --- |
| A | Nothing | ranks cities by taste, then programmes |
| B | Country (UK) | picks the city and programme for you |
| C | City | ranks programmes in that city; lists every university there |
| D | Programmes | checks fit, plans deadlines, and flags better-fitting alternatives |

Every run keeps a trace of the tool calls, shown as "What the agent did" in the UI.

## Data, and how honest it is

- **13 programmes verified** on official pages for 2027 entry: Oxford, Cambridge, Imperial, LSE, UCL, King's College London, Edinburgh, Manchester, Bristol, Glasgow, Leeds. Each record has its source URL and the date it was checked.
- **110 universities in 63 UK cities**, each with its official site (`data/universities.json`).
- Values a course page doesn't state are `null`, shown as *unverified*, and scored neutral (0.5) so they never help or hurt a programme.
- Taste ranking covers the 24 major student cities. In smaller towns Qloo's heatmap mostly reflects how busy an area is, so those towns are listed but not ranked on taste.

## Run it locally

Python 3.10+ only, no packages needed.

```bash
git clone https://github.com/utonez/tastecompass.git
cd tastecompass
cp .env.example .env        # paste QLOO_API_KEY (and optionally OPENAI_API_KEY)
python web.py               # http://localhost:8000
```

Without a Qloo key it runs in **mock mode** (clearly labelled, synthetic taste scores) so the flow can be tried offline: `python web.py --mock`.

Command-line report: `python run.py profiles/mode_b.json --out out/report.md`

The optional chat ("Ask" tab) uses OpenAI (`OPENAI_API_KEY`) or Claude (`ANTHROPIC_API_KEY` + `pip install anthropic`). It only explains results; numbers always come from the data, and what-if questions rerun the real scoring.

## Deploy (Render)

`render.yaml` is included. Create a Render web service from this repo, then set `QLOO_API_KEY` and `OPENAI_API_KEY` in the service's environment. The server binds `0.0.0.0:$PORT` when `--host 0.0.0.0` is passed (as in `render.yaml`).

## Project layout

```
web.py                  HTTP server: homepage, agent UI, JSON API
static/landing.html     homepage
static/index.html       agent UI
tastecompass/agent.py   scope modes, tool calls, ranking, trace
tastecompass/qloo.py    Qloo client (retries, disk cache) + offline mock
tastecompass/scoring.py fit score
tastecompass/planner.py deadline picking and backward timeline
tastecompass/explain.py LLM explanations and what-if tool
data/                   cities, universities, verified programmes
```

## License

MIT - see [LICENSE](LICENSE).
