# FantasyFootballCrew.com — Implementation Plan

> **Mission:** Build a beta-ready fantasy football platform with fully customizable scoring, multiple league types (standard, 2-man teams, conference 6v6), coaches/coordinators, and an AI analysis chatbot. Launch beta by August 2026.

## Architecture

```
fantasyfootballcrew.com
├── Vercel (Frontend) — Next.js 14 + Tailwind CSS
└── Railway (Backend) — FastAPI + PostgreSQL + Redis
    └── Supabase — Auth + Managed PostgreSQL
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Frontend | Next.js 14 (App Router) + Tailwind CSS | SSR/SEO, modern DX, easy theming |
| Backend | FastAPI + SQLAlchemy 2.0 + Alembic | Async, auto-docs, Python for scoring math |
| Database | PostgreSQL (via Supabase) | JSON fields for flexible scoring configs, complex league queries |
| Auth | Supabase Auth | Free tier, email/password + Google OAuth built-in |
| Data | Sleeper API | Free NFL player data, stats, depth charts |
| AI | Claude/OpenAI API + RAG | Custom football analysis agent |
| Hosting | Vercel (frontend) + Railway (backend) | Near-zero cost to start, scales |

## Project Structure

```
D:\fantasyfootballcrew\
├── frontend/                        # Next.js app
│   ├── src/
│   │   ├── app/                     # App Router pages
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx             # Landing page
│   │   │   ├── login/               # Auth pages
│   │   │   ├── dashboard/           # User dashboard
│   │   │   ├── leagues/             # League pages
│   │   │   │   ├── [id]/
│   │   │   │   ├── create/
│   │   │   │   └── join/
│   │   │   ├── teams/               # Team pages
│   │   │   └── api/                 # Next.js API routes (proxy to FastAPI)
│   │   ├── components/
│   │   │   ├── ui/                  # Reusable UI (buttons, cards, modals)
│   │   │   ├── layout/              # Header, sidebar, footer
│   │   │   ├── league/              # League-specific components
│   │   │   └── ai-chat/             # AI chatbot components
│   │   └── lib/
│   │       ├── supabase.ts          # Supabase client
│   │       ├── api-client.ts        # FastAPI backend client
│   │       └── utils.ts
│   ├── tailwind.config.ts           # Custom theme (black + gold)
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry
│   │   ├── core/
│   │   │   ├── config.py            # Settings
│   │   │   ├── database.py          # Async SQLAlchemy setup
│   │   │   └── dependencies.py      # DI helpers
│   │   ├── models/                  # SQLAlchemy models
│   │   │   ├── user.py
│   │   │   ├── league.py
│   │   │   ├── team.py
│   │   │   ├── player.py
│   │   │   ├── scoring.py
│   │   │   ├── draft.py
│   │   │   └── coach.py
│   │   ├── schemas/                 # Pydantic models
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── users.py
│   │   │   │   ├── leagues.py
│   │   │   │   ├── teams.py
│   │   │   │   ├── players.py
│   │   │   │   ├── drafts.py
│   │   │   │   ├── scoring.py
│   │   │   │   ├── trades.py
│   │   │   │   ├── waivers.py
│   │   │   │   └── ai.py
│   │   │   └── deps.py
│   │   └── services/                # Business logic
│   │       ├── scoring_engine.py    # Custom scoring calculations
│   │       ├── draft_manager.py
│   │       ├── trade_analyzer.py
│   │       ├── sleeper_sync.py      # Sleeper API ingestion
│   │       └── ai_service.py        # AI chatbot service
│   ├── alembic/                     # DB migrations
│   ├── requirements.txt
│   └── .env.example
└── README.md
```

## Data Models (Core)

### User
- id, email, username, avatar_url, provider (google/email), created_at

### League
- id, name, description, commissioner_id, league_type (standard/2man/conference), scoring_config (JSONB), max_teams, draft_status, draft_type (snake/auction), created_at

### Team
- id, name, owner_id(s), league_id, roster (JSONB), wins, losses, ties, points_for, points_against

### Player (NFL)
- id, sleeper_id, first_name, last_name, position, team, bye_week, injury_status, fantasy_positions, stats (JSONB)

### ScoringConfig
- id, league_id, category (passing/rushing/receiving/defense/misc), stat_name, points_per_unit, is_active

### Coach/Coordinator
- id, name, position (HC/OC/DC/STC), team_id, bonus_type, bonus_value, league_id

### DraftPick
- id, league_id, team_id, player_id, round, pick_number, drafted_at

## Scoring Engine Design

The customizable scoring engine is the heart of the platform. Design:

```python
# Storage: JSONB scoring_config on League model
scoring_config = {
    "passing": {"pass_yds": 0.04, "pass_td": 4, "int": -2},
    "rushing": {"rush_yds": 0.1, "rush_td": 6},
    "receiving": {"rec": 1, "rec_yds": 0.1, "rec_td": 6},
    "defense": {"sack": 1, "int": 2, "fum_rec": 2, "safety": 2, "td": 6},
    "kicking": {"fg_0_39": 3, "fg_40_49": 4, "fg_50_plus": 5, "xp": 1},
    "bonus": {"long_td_bonus": 3},
    "custom": []  # User-defined custom scoring rules
}
```

The engine maps Sleeper API stat keys to scoring categories and applies config multipliers. New stat keys can be added at any time without schema changes.

## Phase Plan

### Phase 1: Foundation (June 1-14)
- [✓] Project setup (Next.js + FastAPI + Supabase)
- [✓] Black + gold theme
- [✓] Auth (email + Google)
- [✓] NFL player data sync via Sleeper API
- [✓] Basic league creation
- [✓] Customizable scoring engine (core logic)

### Phase 2: Core Gameplay (June 15 - July 15)
- [ ] Snake draft system
- [ ] Team management + lineups
- [ ] Weekly scoring + standings
- [ ] Waivers + trades
- [ ] 2-Man Teams
- [ ] Conference Leagues (6v6)

### Phase 3: The Meta (July 15 - Aug 1)
- [ ] Coaches & Coordinators
- [ ] Co-managed team polish

### Phase 4: AI & Beta (Aug 1 - Aug 15)
- [ ] AI Chat Bot (lineup + trade analysis)
- [ ] Weather + matchup data
- [ ] Bet analysis
- [ ] Deployment + beta launch
