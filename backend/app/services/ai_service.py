"""
AI Analysis Service

Provides fantasy football analysis using LLM API (OpenAI/Claude).
Injects real-time context (player stats, matchups, weather) into prompts.
"""

from datetime import date
from typing import Dict, Any, Optional
import httpx
import json

# Prepended to every LLM call's system message. Two concrete, real gaps
# this closes (found investigating a David-reported "the AI gave a few
# answers that were a little off on player movement/who's on what team"
# bug): the model was never told what day it is, and was never told to
# prefer the app's own data over its training memory -- so on anything
# it wasn't explicitly handed, it silently guessed from (possibly
# stale-by-now) training knowledge and stated it as fact. today is a
# real server-computed date.today(), not hardcoded text -- this line is
# accurate on every call, forever, unlike a prompt with a fixed date
# baked into it.
def _grounding_preamble() -> str:
    # %-d (no leading zero) is a glibc/Linux-only strftime extension --
    # not portable to Windows (this app runs on Railway/Linux in prod but
    # is developed on Windows), so deliberately not used here.
    today = date.today().strftime("%A, %B %d, %Y")
    return (
        f"Today's real date is {today}. Treat any roster, injury, trade, "
        "or depth-chart detail you were not explicitly given below as "
        "UNVERIFIED -- your training data has a cutoff and NFL rosters "
        "change constantly (trades, cuts, signings, injuries), especially "
        "close to or during a season. Never state a player's current team "
        "or status as fact from memory alone; if it's not in the data "
        "provided, say you're not certain rather than guessing."
    )

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

# OpenAI's cost-tier model, confirmed directly against api.openai.com
# (GET /v1/models) and openai.com's own docs: $0.20/1M input,
# $1.20/1M output tokens -- "designed for cost-sensitive, high-volume
# workloads," roughly the nano tier of the GPT-5.6 family. Every AI
# Co-Commissioner call is a short analysis/chat-reply task, not
# something needing frontier reasoning, so the cheapest tier is the
# right default. Named constant, not a magic string repeated at every
# call site -- swap this one line to change models everywhere at once.
OPENAI_MODEL = "gpt-5.6-luna"

# httpx.AsyncClient()'s own default is a 5-second TOTAL timeout -- far
# too tight for an LLM chat completion, whose whole point is generating
# a non-trivial amount of text ("detailed, data-driven analysis" is the
# literal system prompt). Confirmed directly: an identical real call
# against the real API/key routinely took several seconds for a genuine
# response, and every httpx timeout exception's str() is '' (empty) --
# which is exactly what was showing up as the blank "[AI call FAILED]"
# lines in production logs. This was hitting the 5s ceiling on most
# calls, not a rare edge case, which is why every AI Analysis request
# was coming back as "temporarily unavailable." email_service.py
# already sets timeout=10 for its (much smaller) Resend API calls;
# this is deliberately looser since a full LLM completion is a longer
# request by nature.
LLM_HTTP_TIMEOUT = 60.0


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

TOP_PLAYERS_SUMMARY_PROMPT = """
You are an expert NFL analyst. Write a short, engaging recap of this
week's best real-world NFL performances, using ONLY plain text -- no
markdown syntax, this is displayed as-is.

**Week:** {week}, {year}

**Top performers this week (ranked by a standard fantasy scoring
system, real per-player stat lines -- trust this list over anything
you think you know about these players' recent performances):**
{top_players}

Write 2-4 short paragraphs: who had standout weeks and why (cite the
actual stat lines given), any notable trend across positions, and one
or two players worth watching next week based on this week's showing.
Do not invent stats, injuries, or context beyond what's given above.
"""

NFL_SCORES_RECAP_PROMPT = """
You are a witty NFL recap writer. Write a fun recap of this week's
real NFL games, using ONLY plain text -- no markdown syntax, this is
displayed as-is.

{tone_instruction}

**Week:** {week}, {year}

**This week's real games and final/current scores (trust this over
anything you think you know -- these are the actual synced results):**
{games}

Write 2-4 short paragraphs covering the week's biggest storylines --
upsets, blowouts, any standout team performances -- using ONLY the
scores/results given above. If a game hasn't finished yet (not marked
completed), don't state its outcome as final. Don't invent stats,
injuries, or storylines beyond what the scores themselves tell you.
"""

TEAM_RECAPS_PROMPT = """
You are a fantasy football beat writer. Write a SHORT (2-3 sentences
each) recap blurb for EVERY team below, covering their week. Plain
text only, no markdown. Format each team as:

TEAM NAME: <blurb>

one per line/paragraph, in the same order given below -- no extra
commentary before or after the list of blurbs.

**League:** {league_name} -- Week {week}, {year}

**Every team's week (result, score, opponent, top performer):**
{teams}

Keep it light and specific -- reference the actual score/result/top
performer given for each team, don't invent details. A "bye" result
means no matchup this week (schedule quirk, not eliminated) -- note it
briefly, don't treat it as a loss.
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

{grounding}

Current league snapshot (may not include very old history):
{context}
"""

BET_ANALYSIS_PROMPT = """
You are an expert NFL betting analyst and oddsmaker, giving sharp,
realistic, data-driven betting analysis. Explicitly factor in what
point in the season this is (preseason, early/mid/late regular season,
playoffs) -- preseason especially is inherently noisy: limited starter
snaps, heavy rotation, roster experimentation, and coaches prioritizing
evaluation over winning, so confidence should be lower and hedged more
than a regular-season take.

**The user's own description of the matchup/question:**
{matchup}

**Verified current player data (from this app's own synced roster
data, NOT the model's training memory -- trust this over anything you
think you know about these specific players):**
{verified_players}

**Lines/Props the user provided (if empty, no live odds feed exists in
this app yet -- say so explicitly and reason about the matchup
qualitatively instead of inventing specific numbers):**
{lines}

**Other factors the user provided (if empty, you were not given this --
do not invent specific injury news, weather, or historical results you
don't actually have):**
- Weather: {weather}
- Injuries: {injuries}
- Historical matchups: {history}

Structure your answer:
1. KEY CONTEXT -- season stage, expected starter/snap involvement if
   knowable, anything relevant from the verified player data above
2. MARKET ASSESSMENT -- only discuss specific lines/odds if they were
   actually provided above; otherwise discuss the matchup qualitatively
3. SHARP ANGLES -- situational edges, total lean, spread lean, each
   with a confidence level (Low/Medium/High)
4. BEST BET -- one primary play (or "Pass" if there's no real edge),
   with a conservative 1-5 unit stake suggestion
5. RISK FACTORS -- the biggest reasons this could be wrong, and what
   would flip your lean

Be honest about uncertainty -- real edges are usually small, and
preseason ones especially so. Never invent specific injury/depth-chart
details you weren't given; flag that uncertainty clearly instead.
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

    async def generate_top_players_summary(self, week: int, year: int, top_players: Optional[list] = None) -> str:
        """Dashboard AI Summaries: NFL-wide (not per-league) recap of
        the week's best real performances -- see top_performers_service.py
        for how top_players is ranked (DEFAULT_SCORING, not any one
        league's custom rules)."""
        prompt = TOP_PLAYERS_SUMMARY_PROMPT.format(
            week=week, year=year, top_players=json.dumps(top_players or [], indent=2),
        )
        return await self._call_llm(prompt)

    async def generate_nfl_scores_recap(self, week: int, year: int, games: Optional[list] = None, tone: str = "sarcastic") -> str:
        """Dashboard AI Summaries: funny recap of the week's real NFL
        games -- reuses the existing "sarcastic" tone (TONE_INSTRUCTIONS
        above) rather than inventing a new one; it already covers
        "funny" well. games comes from nfl_schedule_service.py's
        ESPN-synced NFLGame rows."""
        prompt = NFL_SCORES_RECAP_PROMPT.format(
            tone_instruction=TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["sarcastic"]),
            week=week, year=year, games=json.dumps(games or [], indent=2),
        )
        return await self._call_llm(prompt)

    async def generate_team_recaps(self, league_name: str, week: int, year: int, teams: Optional[list] = None) -> str:
        """Dashboard AI Summaries: one LLM call producing a short blurb
        for every team in a league at once -- see team_recap_service.py
        for why (N times cheaper than one call per team)."""
        prompt = TEAM_RECAPS_PROMPT.format(
            league_name=league_name, week=week, year=year, teams=json.dumps(teams or [], indent=2),
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
        system = CHAT_SYSTEM_PROMPT.format(
            league_name=league_name, context=json.dumps(context, indent=2), grounding=_grounding_preamble(),
        )
        if self.provider == "openai" and self.api_key:
            return await self._call_openai_chat(system, history)
        elif self.provider == "anthropic" and self.api_key:
            return await self._call_anthropic_chat(system, history)
        return "AI Analysis: LLM API not configured. Set OPENAI_API_KEY in your .env to enable AI features."

    async def _call_openai_chat(self, system: str, history: list) -> str:
        """OpenAI puts the system prompt as a {"role": "system", ...}
        entry inside the messages array itself."""
        try:
            async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        # No "temperature" -- OPENAI_MODEL (gpt-5.6-luna)
                        # rejects any non-default value with a 400
                        # ("Only the default (1) value is supported"),
                        # confirmed directly against the real API.
                        # Omitting it just uses the provider's default.
                        "model": OPENAI_MODEL,
                        "messages": [{"role": "system", "content": system}] + history,
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
            async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as client:
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
        verified_players: Optional[list] = None,
    ) -> str:
        """Analyze betting lines and props.

        verified_players: real, currently-synced roster data (name,
        position, current NFL team, injury_status) for any players the
        caller matched out of the user's own free-text prompt -- see
        api/v1/ai.py's analyze_bet endpoint, which does that matching
        against this app's own Player table (synced from Sleeper) before
        calling this. Empty list means either no player names were
        recognized in the prompt, or none matched -- the prompt template
        itself instructs the model to treat that as "no verified data,"
        not as "no players involved."
        """
        prompt = BET_ANALYSIS_PROMPT.format(
            matchup=json.dumps(matchup, indent=2),
            verified_players=json.dumps(verified_players or [], indent=2),
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
            async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        # No "temperature" -- see _call_openai_chat's
                        # comment; OPENAI_MODEL rejects any non-default value.
                        "model": OPENAI_MODEL,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert fantasy football analyst. Provide detailed, "
                                    "data-driven analysis with clear recommendations. "
                                    + _grounding_preamble()
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
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
            async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as client:
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
                        # Was missing entirely before -- this call had zero
                        # system framing (unlike _call_anthropic_chat, which
                        # already used Anthropic's top-level "system" field
                        # correctly). Now matches _call_openai's system
                        # message above.
                        "system": (
                            "You are an expert fantasy football analyst. Provide detailed, "
                            "data-driven analysis with clear recommendations. "
                            + _grounding_preamble()
                        ),
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
