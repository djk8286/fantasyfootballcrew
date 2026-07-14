# FantasyFootballCrew — Deployment Guide

## Overview

- **Frontend:** Vercel (Next.js 16)
- **Backend:** Railway (FastAPI + PostgreSQL)
- **Domain:** fantasyfootballcrew.com (Namecheap)

---

## Backend — Railway

### Prerequisites

1. [Railway account](https://railway.app) — free tier works
2. [Railway CLI](https://docs.railway.app/develop/cli) (optional)

### Steps

```bash
# 1. Navigate to backend
cd fantasyfootballcrew/backend

# 2. Deploy via Railway CLI
railway login
railway init
railway up

# Or link existing project:
railway link <project-id>
railway up
```

### Environment Variables (Railway Dashboard)

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Railway auto-provides PostgreSQL URL |
| `JWT_SECRET` | `<random-string>` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CORS_ORIGINS` | `["https://fantasyfootballcrew.com","https://www.fantasyfootballcrew.com"]` | JSON array of allowed origins |

### Railway Auto-Configuration

The project includes:
- `Procfile` — `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `railway.json` — health check, restart policy
- `requirements.txt` — all dependencies incl. `asyncpg` for PostgreSQL

### Database Migration

The app auto-creates tables on startup (`Base.metadata.create_all`). For
PostgreSQL, Railway auto-provisions a database. Just set `DATABASE_URL`
to the Railway-provided connection string (replace `postgresql://` with
`postgresql+asyncpg://`).

For schema changes, create Alembic migrations later.

---

## Frontend — Vercel

### Prerequisites

1. [Vercel account](https://vercel.com)
2. [Vercel CLI](https://vercel.com/docs/cli) (optional)

### Steps

```bash
# 1. Navigate to frontend
cd fantasyfootballcrew/frontend

# 2. Deploy via Vercel CLI (or connect GitHub repo)
vercel login
vercel --prod

# 3. Set env vars
vercel env add NEXT_PUBLIC_API_URL
```

### Environment Variables (Vercel Dashboard)

| Variable | Value | Notes |
|----------|-------|-------|
| `NEXT_PUBLIC_API_URL` | `https://<railway-app>.up.railway.app` | Your Railway backend URL |

### Vercel Configuration

The project includes `vercel.json` with:
- Build: `npm run build`
- Output: `.next`
- Framework: Next.js

---

## Domain Setup

### DNS (Namecheap → Vercel)

1. In Vercel dashboard, add domain `fantasyfootballcrew.com`
2. In Namecheap, set custom DNS to Vercel's nameservers:
   - `dns1.vercel-dns.com`
   - `dns2.vercel-dns.com`
3. Wait for propagation (5–30 minutes)

### DNS (Namecheap → Railway)

Railway provides a `*.up.railway.app` URL. For a custom domain:
1. In Railway dashboard, add custom domain for the backend service
2. Add a CNAME record in Namecheap pointing to the Railway URL

---

## Post-Deployment Checklist

- [ ] Backend health check: `GET https://api.fantasyfootballcrew.com/health`
- [ ] Frontend loads: `https://fantasyfootballcrew.com`
- [ ] Registration flow works
- [ ] Create league works
- [ ] Draft board loads
- [ ] Scoring settings save/load
- [ ] Standings display
- [ ] Sleeper player sync (run manually via Railway console)
- [ ] SSL certificates (auto by Vercel/Railway)

### Manual Sleeper Sync (after deploy)

```bash
# Via Railway CLI or console:
cd backend
python -c "
import asyncio
from app.core.database import async_session, engine
from app.services.sleeper_sync import sync_players_to_db

async def sync():
    async with async_session() as db:
        count = await sync_players_to_db(db)
        print(f'Synced {count} players')
    await engine.dispose()

asyncio.run(sync())
"
```

---

## Local Development

```bash
# Backend
cd backend
source venv/Scripts/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8005

# Frontend
cd frontend
npm run dev
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8005
- API Docs: http://localhost:8005/docs

---

## Architecture Notes

### API Routes (48 total)

| Group | Endpoints | Purpose |
|-------|-----------|---------|
| Auth | `/api/v1/auth/*` | Register, login, JWT |
| Leagues | `/api/v1/leagues/*` | CRUD, scoring config, commissioner |
| Teams | `/api/v1/teams/*` | CRUD, bulk-add CPU, claim |
| Players | `/api/v1/players/*` | NFL player list/search |
| Draft | `/api/v1/drafts/*` | Snake draft, timer, auto-pick, mock |
| Scoring | `/api/v1/scoring/*` | Calculator, validation, Sleeper weekly |
| Standings | `/api/v1/leagues/{id}/standings/*` | Standings, weekly scores, calculate |
| Commissioner | `/api/v1/leagues/{id}/commissioner/*` | Adjustments, trades, draft order |
| AI | `/api/v1/ai/*` | Analysis, lineup, trade (needs API key) |

### Frontend Pages

| Route | Page |
|-------|------|
| `/` | Landing page |
| `/login` | Log in |
| `/register` | Sign up |
| `/dashboard` | League list |
| `/leagues/create` | Create league |
| `/leagues/[id]` | League detail + team mgmt |
| `/leagues/[id]/scoring` | Scoring settings |
| `/leagues/[id]/standings` | Standings + weekly scores |
| `/leagues/[id]/commissioner` | Commissioner panel |
| `/draft/[id]` | Draft war room |

### Key Features Status

| Feature | Status |
|---------|--------|
| ✅ Landing page | Complete |
| ✅ Auth (JWT) | Complete |
| ✅ League CRUD | Complete |
| ✅ Team management | Complete |
| ✅ Snake draft w/ timer | Complete |
| ✅ Auto-pick (CPU) | Complete |
| ✅ Mock drafts | Complete |
| ✅ Scoring settings UI | Complete |
| ✅ Scoring engine | Complete |
| ✅ Standings + weekly | Complete |
| ✅ Commissioner controls | Complete |
| ✅ Player sync (Sleeper) | Complete |
| ✅ Bulk CPU team add | Complete |
| 🔲 AI Chat (The Oracle) | Needs API key |
| 🔲 Coach/Coordinator UI | Backend ready, frontend bonus |
| 🔲 Waivers/Trades | Backend endpoints ready, frontend TBD |