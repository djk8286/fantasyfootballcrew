# 🏈 FantasyFootballCrew

> The most customizable fantasy football platform. Custom scoring, 2-Man Teams, Conference Leagues, Coaches & Coordinators, and AI-powered analysis.

**Domain:** [fantasyfootballcrew.com](https://fantasyfootballcrew.com)  
**Status:** Beta — August 2026  
**Stack:** Next.js 14 + FastAPI + PostgreSQL + Supabase + Sleeper API

---

## Quick Start

### Backend

```bash
cd backend
source venv/Scripts/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

API docs at http://localhost:8001/docs

### Frontend

```bash
cd frontend
npm run dev
```

Open http://localhost:3000

### Both at once

```bash
cd frontend
npm run dev:all
```

---

## Project Structure

```
fantasyfootballcrew/
├── frontend/          # Next.js 14 (App Router) + Tailwind CSS
│   ├── src/
│   │   ├── app/       # Pages (/, /login, /register, /leagues, etc.)
│   │   ├── components/# Reusable UI components
│   │   └── lib/       # API client, Supabase client, utils
│   └── tailwind.config.ts
├── backend/           # FastAPI + SQLAlchemy + Alembic
│   ├── app/
│   │   ├── api/v1/    # REST endpoints (auth, leagues, teams, etc.)
│   │   ├── models/    # SQLAlchemy ORM models
│   │   ├── schemas/   # Pydantic validation schemas
│   │   ├── services/  # Business logic (scoring, sleeper sync, AI)
│   │   └── core/      # Config, DB, dependencies
│   └── requirements.txt
└── PLAN.md            # Full implementation roadmap
```

## Key Features

- **Customizable Scoring** — Any stat, any weight, any bonus. JSON-based config.
- **League Types** — Standard, 2-Man Teams, Conference (6v6)
- **Coaches & Coordinators** — HC, OC, DC, STC with performance bonuses
- **AI Chat Bot** — Lineup analysis, trade evaluation, bet analysis
- **Sleeper API** — Free NFL player data sync
- **Auth** — Email/password + Google OAuth (via Supabase)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Next.js 16, Tailwind CSS v4 |
| Backend | FastAPI, SQLAlchemy 2.0 |
| Database | SQLite (dev) / PostgreSQL (prod via Supabase) |
| Auth | Email + Google (Supabase Auth) |
| Data | Sleeper API (free) |
| AI | OpenAI / Anthropic API |
| Hosting | Vercel + Railway |

## Roadmap

See [PLAN.md](PLAN.md) for the full implementation roadmap.

**Phase 1 (June):** Foundation — Project setup, auth, player data, scoring engine, league creation  
**Phase 2 (June-July):** Core — Drafts, lineups, scoring, waivers, trades, 2-man teams, conferences  
**Phase 3 (July):** Meta — Coaches & Coordinators  
**Phase 4 (Aug):** AI & Beta — AI chatbot, deployment, beta launch
