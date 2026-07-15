"""
AI Analysis Service

Provides fantasy football analysis using LLM API (OpenAI/Claude).
Injects real-time context (player stats, matchups, weather) into prompts.
"""

from typing import Dict, Any, Optional
import httpx
import json


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

Provide:
1. Trade grade for each team (A-F)
2. Who wins the trade
3. Long-term vs short-term impact
4. Counter-offer suggestion if unbalanced
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

    def __init__(self, api_key: Optional[str] = None, model: str = "default"):
        self.api_key = api_key
        self.model = model
        self.provider = "openai"  # Will make configurable

    async def analyze_lineup(
        self,
        roster: Dict[str, Any],
        opponent_roster: Dict[str, Any],
        matchups: Dict[str, Any],
        scoring: Dict[str, Any],
        weather: Optional[Dict] = None,
    ) -> str:
        """Analyze and optimize a user's lineup."""
        prompt = LINEUP_ANALYSIS_PROMPT.format(
            roster=json.dumps(roster, indent=2),
            opponent_roster=json.dumps(opponent_roster, indent=2),
            player_matchups=json.dumps(matchups, indent=2),
            weather=json.dumps(weather or {}, indent=2),
            scoring_settings=json.dumps(scoring, indent=2),
        )
        return await self._call_llm(prompt)

    async def analyze_trade(
        self,
        team_a_players: list,
        team_b_players: list,
        scoring: Dict[str, Any],
        standings: Optional[Dict] = None,
    ) -> str:
        """Analyze a trade proposal between two teams."""
        prompt = TRADE_ANALYSIS_PROMPT.format(
            team_a_players=json.dumps(team_a_players, indent=2),
            team_b_players=json.dumps(team_b_players, indent=2),
            scoring_settings=json.dumps(scoring, indent=2),
            standings_context=json.dumps(standings or {}, indent=2),
        )
        return await self._call_llm(prompt)

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

    async def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
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
