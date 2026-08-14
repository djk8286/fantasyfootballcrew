"""
AI Analysis Service

Provides fantasy football analysis using LLM API (OpenAI/Claude).
Injects real-time context (player stats, matchups, weather) into prompts.
"""

from typing import Dict, Any, Optional
import httpx
import json

# Distinct from the "not configured" fallback -- this covers a
# configured key that fails at call time (quota exhausted, provider
# outage, transient network error, revoked key, etc). Every _call_*
# method below catches broad Exception around its actual HTTP call and
# returns this instead of letting the error propagate -- none of the
# calling service modules (commissioner_digest_service.py,
# trade_review_service.py, message_service.py, chat_service.py) wrap
# these calls in their own try/except, so an uncaught exception here
# would surface as a raw 500 to the user on what looks like a normal
# request. Logged server-side (visible in `railway logs`) so a real
# outage/quota problem is still diagnosable, same "don't let a
# third-party hiccup break the user-facing request" precedent
# email_service.py already established for outbound email.
AI_TEMPORARILY_UNAVAILABLE = "AI Analysis: the AI service is temporarily unavailable right now. Please try again in a few minutes."


# AI Co-Commissioner v1: tone/length are per-generation params on the
# weekly digest (not a persisted league setting -- see
# commissioner_digest_service.py), mapped here to one-line instruction
# phrases spliced into COMMISSIONER_DIGEST_PROMPT. An unrecognized
# value falls back to "professional"/"full" rather than raising --
# matches this codebase's general "degrade gracefully" convention for
# optional fields.
TONE_INSTRUCTIONS: Dict[str, str] = {
    "professional": "Write in a professional, measured tone.",
    "casual": "Write in a casual, conversational tone, like a friend texting league updates.",
    "hype": "Write with high energy and hype, like a sports hype-man.",
    "sarcastic": "Write with dry sarcasm and playful jabs at underperforming teams.",
    "dry": "Write in a deadpan, understated, dry-humor tone.",
}

LENGTH_INSTRUCTIONS: Dict[str, str] = {
    "short": "Keep the whole digest to 2-3 short paragraphs total, hitting only the highlights.",
    "full": "Write the full, detailed digest as specified below.",
}

# AI Co-Commissioner v1 Phase 2: Communication Helpers. message_type
# drives which fixed instructional framing COMMISSIONER_MESSAGE_PROMPT
# uses -- an unrecognized value falls back to "general" rather than
# raising, same degrade-gracefully convention as TONE_INSTRUCTIONS.
MESSAGE_TYPE_INSTRUCTIONS: Dict[str, str] = {
    "trade_deadline": "Write a reminder that the trade deadline is approaching -- encourage managers to finish any deals before it passes.",
    "playoff_explanation": "Explain how the playoffs work for this league, using the actual playoff settings provided below -- who makes it, how seeding works, and when it starts.",
    "inactivity_warning": "Write a gentle-but-clear warning about inactive teams in the league, using the specific at-risk team names provided below -- encourage them to get engaged without naming-and-shaming or being harsh.",
    "general": "Write a general announcement to the league based on the additional context provided below.",
}


# Default analysis prompts
LINEUP_ANALYSIS_PROMPT = """
You are an expert fantasy football analyst. Analyze the following lineup and matchups:

**Your Team Roster:**
{roster}

**Opponent's Team:**
{opponent_roster}

**Matchup Details:**
{player_matchups}

**Weather Conditions:**
{weather}

**Scoring Settings:**
{scoring_settings}

**Coaching Staff:**
{coaching_staff}

**Salary Cap:**
{salary_context}

**Linked Pair (Dual-Squad):**
{partner_context}

Provide:
1. Optimal lineup recommendation (who to start/sit)
2. Confidence level for this week (1-10)
3. Key matchups to watch
4. Waiver wire suggestions if applicable
"""

TRADE_ANALYSIS_PROMPT = """
You are an expert fantasy football trade analyzer. Evaluate this trade proposal:

**Team A gives up:**
{team_a_players}

**Team B gives up:**
{team_b_players}

**League Settings:**
{scoring_settings}

**Current Standings Context:**
{standings_context}

**Coaching Staff:**
- Team A: {team_a_coaching}
- Team B: {team_b_coaching}

**Salary Cap:**
- Team A: {team_a_salary}
- Team B: {team_b_salary}

**Linked Pair (Dual-Squad):**
- Team A: {team_a_partner}
- Team B: {team_b_partner}

Provide:
1. Trade grade for each team (A-F)
2. Who wins the trade
3. Long-term vs short-term impact
4. Counter-offer suggestion if unbalanced
"""

COMMISSIONER_DIGEST_PROMPT = """
You are an expert fantasy football commissioner's assistant. Write a
weekly digest for this league using ONLY plain text -- no markdown
syntax (no #, **, or -- for emphasis), since this will be displayed as
plain text, not rendered markdown. Use simple ALL-CAPS section titles
on their own line instead of markdown headers.

{tone_instruction} {length_instruction}

**League:** {league_name} -- Week {week}, {year}

**Standings:**
{standings}

**Combined Pairs Standings (Dual-Squad, if applicable):**
{combined_standings}

**Recent Transactions:**
{recent_transactions}

**Active League Features:**
{features}

**Scoring Settings:**
{scoring_config}

Write, in plain text with ALL-CAPS section titles:
1. POWER RANKINGS -- ranked list with a one-line reason for each team's spot
2. THIS WEEK'S STORYLINES -- 2-3 short paragraphs of narrative color
3. WAIVER & TRADE RECAP -- what moved and who it helps/hurts
4. COMMISSIONER NOTES -- any fairness/rule-adjustment observations worth flagging (advisory only -- the commissioner decides, never phrase this as an instruction)
"""

TRADE_REVIEW_PROMPT = """
You are an expert fantasy football commissioner's assistant, reviewing
a trade for FAIRNESS and LEAGUE IMPACT (not which side "wins" -- this
is for the commissioner deciding whether to approve it, not either
trading team). Plain text only, no markdown syntax.

Your response MUST start with exactly one of these three lines, then a
blank line, then your reasoning:
RECOMMENDATION: APPROVE
RECOMMENDATION: REVIEW CLOSELY
RECOMMENDATION: VETO

**League:** {league_name}

**Proposing team ({proposer_name}) gives up:**
{offered_players}

**Target team ({target_name}) gives up:**
{requested_players}

**Current Standings:**
{standings}

**Recent trades between these two specific teams (collusion-pattern context):**
{recent_trades_between_teams}

**Scoring Settings:**
{scoring_config}

After the RECOMMENDATION line, cover in plain text:
1. FAIRNESS -- is the trade roughly balanced under this league's actual scoring?
2. LEAGUE IMPACT -- how does this affect competitive balance/standings?
3. PATTERN CHECK -- anything about the history between these two teams worth flagging (or explicitly say nothing stands out)?
"""

COMMISSIONER_MESSAGE_PROMPT = """
You are a fantasy football league commissioner's assistant, drafting a
message the commissioner will review, optionally edit, and send to
every team in the league. Plain text only, no markdown syntax -- this
gets read as-is, not rendered.

{message_type_instruction}

{tone_instruction}

**League:** {league_name}

**Additional context:**
{context}

Write ONLY the message itself -- no preamble, no "Here's a draft:",
no sign-off unless it feels natural. This is a broadcast to the whole
league, not a private note to the commissioner.
"""

CHAT_SYSTEM_PROMPT = """
You are the AI Co-Commissioner assistant for {league_name}, a fantasy
football league on FantasyFootballCrew. You help the commissioner
understand what's happening in their league. Plain text only, no
markdown syntax.

You are ADVISORY ONLY -- you never take action, you only inform and
suggest. If asked to do something (approve a trade, send a message,
change a setting), explain that the commissioner needs to do that
themselves elsewhere in the app.

Current league snapshot (may not include very old history):
{context}
"""

BET_ANALYSIS_PROMPT = """
You are a sports betting analyst. Analyze these betting props/lines:

**Matchup:**
{matchup}

**Lines/Props:**
{lines}

**Key Factors:**
- Weather: {weather}
- Injuries: {injuries}
- Historical matchups: {history}

Provide:
1. Best bets with confidence level
2. Player props to target
3. Value picks vs trap lines
"""


class AIService:
    """Service for AI-powered fantasy football analysis."""

    def __init__(self, api_key: Optional[str] = None, model: str = "default", provider: str = "openai"):
        self.api_key = api_key
        self.model = model
        self.provider = provider

    async def analyze_lineup(
        self,
        roster: Dict[str, Any],
        opponent_roster: Dict[str, Any],
        matchups: Dict[str, Any],
        scoring: Dict[str, Any],
        weather: Optional[Dict] = None,
        coaching_staff: Optional[list] = None,
        salary_context: Optional[dict] = None,
        partner_context: Optional[dict] = None,
    ) -> str:
        """Analyze and optimize a user's lineup."""
        prompt = LINEUP_ANALYSIS_PROMPT.format(
            roster=json.dumps(roster, indent=2),
            opponent_roster=json.dumps(opponent_roster, indent=2),
            player_matchups=json.dumps(matchups, indent=2),
            weather=json.dumps(weather or {}, indent=2),
            scoring_settings=json.dumps(scoring, indent=2),
            coaching_staff=json.dumps(coaching_staff or [], indent=2),
            salary_context=json.dumps(salary_context or {}, indent=2),
            partner_context=json.dumps(partner_context or {}, indent=2),
        )
        return await self._call_llm(prompt)

    async def analyze_trade(
        self,
        team_a_players: list,
        team_b_players: list,
        scoring: Dict[str, Any],
        standings: Optional[Dict] = None,
        team_a_coaching: Optional[list] = None,
        team_b_coaching: Optional[list] = None,
        team_a_salary: Optional[dict] = None,
        team_b_salary: Optional[dict] = None,
        team_a_partner: Optional[dict] = None,
        team_b_partner: Optional[dict] = None,
    ) -> str:
        """Analyze a trade proposal between two teams."""
        prompt = TRADE_ANALYSIS_PROMPT.format(
            team_a_players=json.dumps(team_a_players, indent=2),
            team_b_players=json.dumps(team_b_players, indent=2),
            scoring_settings=json.dumps(scoring, indent=2),
            standings_context=json.dumps(standings or {}, indent=2),
            team_a_coaching=json.dumps(team_a_coaching or [], indent=2),
            team_b_coaching=json.dumps(team_b_coaching or [], indent=2),
            team_a_salary=json.dumps(team_a_salary or {}, indent=2),
            team_b_salary=json.dumps(team_b_salary or {}, indent=2),
            team_a_partner=json.dumps(team_a_partner or {}, indent=2),
            team_b_partner=json.dumps(team_b_partner or {}, indent=2),
        )
        return await self._call_llm(prompt)

    async def generate_commissioner_digest(
        self,
        league_name: str,
        week: int,
        year: int,
        standings: Optional[list] = None,
        combined_standings: Optional[list] = None,
        recent_transactions: Optional[list] = None,
        features: Optional[dict] = None,
        scoring_config: Optional[dict] = None,
        tone: str = "professional",
        length: str = "full",
    ) -> str:
        """Generate a weekly commissioner digest -- power rankings,
        storylines, and a waiver/trade recap (Phase 8, "AI-Assisted
        Commissioner Tools"). Commissioner-triggered on demand, never
        cron-driven -- see commissioner_digest_service.py. tone/length
        are per-generation params (AI Co-Commissioner v1) -- an
        unrecognized value degrades to the professional/full default
        rather than raising."""
        prompt = COMMISSIONER_DIGEST_PROMPT.format(
            tone_instruction=TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["professional"]),
            length_instruction=LENGTH_INSTRUCTIONS.get(length, LENGTH_INSTRUCTIONS["full"]),
            league_name=league_name,
            week=week,
            year=year,
            standings=json.dumps(standings or [], indent=2),
            combined_standings=json.dumps(combined_standings or [], indent=2),
            recent_transactions=json.dumps(recent_transactions or [], indent=2),
            features=json.dumps(features or {}, indent=2),
            scoring_config=json.dumps(scoring_config or {}, indent=2),
        )
        return await self._call_llm(prompt)

    async def generate_trade_review(
        self,
        league_name: str,
        proposer_name: str,
        target_name: str,
        offered_players: Optional[list] = None,
        requested_players: Optional[list] = None,
        standings: Optional[list] = None,
        recent_trades_between_teams: Optional[list] = None,
        scoring_config: Optional[dict] = None,
    ) -> str:
        """Commissioner-facing trade review -- fairness/league-impact
        analysis and an APPROVE/REVIEW CLOSELY/VETO recommendation, for
        the commissioner deciding whether to approve a pending trade
        (distinct from analyze_trade, which grades the trade for the
        two trading parties' own benefit). See trade_review_service.py
        for how the RECOMMENDATION first line is parsed out."""
        prompt = TRADE_REVIEW_PROMPT.format(
            league_name=league_name,
            proposer_name=proposer_name,
            target_name=target_name,
            offered_players=json.dumps(offered_players or [], indent=2),
            requested_players=json.dumps(requested_players or [], indent=2),
            standings=json.dumps(standings or [], indent=2),
            recent_trades_between_teams=json.dumps(recent_trades_between_teams or [], indent=2),
            scoring_config=json.dumps(scoring_config or {}, indent=2),
        )
        return await self._call_llm(prompt)

    async def generate_commissioner_message(
        self,
        league_name: str,
        message_type: str,
        tone: str = "professional",
        context: Optional[dict] = None,
    ) -> str:
        """Drafts a commissioner broadcast message (trade deadline
        reminder, playoff explanation, inactivity warning, general
        announcement) -- see message_service.py for how context is
        assembled per message_type and how the draft gets sent via
        notify_league_teams. Never sends anything itself -- this only
        returns the drafted text for the commissioner to review/edit."""
        prompt = COMMISSIONER_MESSAGE_PROMPT.format(
            message_type_instruction=MESSAGE_TYPE_INSTRUCTIONS.get(message_type, MESSAGE_TYPE_INSTRUCTIONS["general"]),
            tone_instruction=TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["professional"]),
            league_name=league_name,
            context=json.dumps(context or {}, indent=2),
        )
        return await self._call_llm(prompt)

    async def chat(self, league_name: str, context: dict, history: list) -> str:
        """Multi-turn AI Co-Commissioner Chat -- distinct from every
        other method on this class (all single-shot prompt-in/
        string-out). `history` is the real conversation so far, a list
        of {"role": "user"|"assistant", "content": str} dicts, NOT
        collapsed into one prompt string -- a genuine back-and-forth
        needs the LLM to see distinct turns. `context` is a fresh
        league-data snapshot the caller (chat_service.py) rebuilds on
        every call -- never stale, never persisted alongside the
        conversation itself. See chat_service.py for how history is
        capped and how context is assembled from the same compute
        functions already powering the other commissioner tabs."""
        system = CHAT_SYSTEM_PROMPT.format(league_name=league_name, context=json.dumps(context, indent=2))
        if self.provider == "openai" and self.api_key:
            return await self._call_openai_chat(system, history)
        elif self.provider == "anthropic" and self.api_key:
            return await self._call_anthropic_chat(system, history)
        return "AI Analysis: LLM API not configured. Set OPENAI_API_KEY in your .env to enable AI features."

    async def _call_openai_chat(self, system: str, history: list) -> str:
        """OpenAI puts the system prompt as a {"role": "system", ...}
        entry inside the messages array itself."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "system", "content": system}] + history,
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI call FAILED -- openai chat] {e}", flush=True)
            return AI_TEMPORARILY_UNAVAILABLE

    async def _call_anthropic_chat(self, system: str, history: list) -> str:
        """Anthropic's Messages API takes `system` as a top-level
        request field, separate from `messages` -- unlike OpenAI, it
        is NOT a message with role "system" inside the array."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1000,
                        "system": system,
                        "messages": history,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["content"][0]["text"]
        except Exception as e:
            print(f"[AI call FAILED -- anthropic chat] {e}", flush=True)
            return AI_TEMPORARILY_UNAVAILABLE

    async def analyze_bet(
        self,
        matchup: Dict[str, Any],
        lines: Dict[str, Any],
        weather: Optional[Dict] = None,
        injuries: Optional[list] = None,
        history: Optional[Dict] = None,
    ) -> str:
        """Analyze betting lines and props."""
        prompt = BET_ANALYSIS_PROMPT.format(
            matchup=json.dumps(matchup, indent=2),
            lines=json.dumps(lines, indent=2),
            weather=json.dumps(weather or {}, indent=2),
            injuries=json.dumps(injuries or [], indent=2),
            history=json.dumps(history or {}, indent=2),
        )
        return await self._call_llm(prompt)

    async def _call_llm(self, prompt: str) -> str:
        """Call the configured LLM API."""
        if self.provider == "openai" and self.api_key:
            return await self._call_openai(prompt)
        elif self.provider == "anthropic" and self.api_key:
            return await self._call_anthropic(prompt)
        else:
            return "AI Analysis: LLM API not configured. Set OPENAI_API_KEY in your .env to enable AI features."

    async def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are an expert fantasy football analyst. Provide detailed, data-driven analysis with clear recommendations.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI call FAILED -- openai] {e}", flush=True)
            return AI_TEMPORARILY_UNAVAILABLE

    async def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1000,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                            }
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["content"][0]["text"]
        except Exception as e:
            print(f"[AI call FAILED -- anthropic] {e}", flush=True)
            return AI_TEMPORARILY_UNAVAILABLE
