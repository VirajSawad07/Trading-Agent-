"""Macroeconomic Context & News Event Risk Agent (LLM Analyst)."""

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


@dataclass
class MacroContext:
    bias: str             # "BULLISH", "BEARISH", "NEUTRAL"
    risk_level: str       # "LOW", "MODERATE", "HIGH"
    event_lockout: bool   # True if within high-impact news window (e.g. CPI, NFP, FOMC)
    veto_trade: bool      # True if macro risks explicitly forbid trading
    reasoning: str


class LLMAgent:
    """Agent that assesses macroeconomic risk, higher-timeframe structure, and news calendar windows."""

    def __init__(self, use_live_api: bool = True, model_name: Optional[str] = None):
        self.use_live_api = use_live_api
        # Default to environment variable or frontier gpt-5.6-luna / gpt-5.5
        self.model_name = model_name or os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = None

        if self.api_key and self.use_live_api:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key)
            except Exception:
                self.client = None

    def evaluate_context(
        self,
        current_time: pd.Timestamp,
        current_price: float,
        h4_trend_bias: str = "NEUTRAL",
        economic_events: Optional[List[Dict]] = None,
    ) -> MacroContext:
        """Evaluates macro regime and event risk."""
        hour = current_time.hour
        weekday = current_time.weekday()  # 0=Monday, 4=Friday, 6=Sunday

        # 1. Hard Friday Weekend Close Risk Lockout
        if weekday == 4 and hour >= 20:  # Friday after 20:00 UTC
            return MacroContext(
                bias="NEUTRAL",
                risk_level="HIGH",
                event_lockout=True,
                veto_trade=True,
                reasoning="Approaching Friday market close; weekend gap risk forbids opening new positions.",
            )

        # 2. Check scheduled high-impact events if provided
        if economic_events:
            for event in economic_events:
                event_time = pd.to_datetime(event.get("time"))
                diff_minutes = abs((current_time - event_time).total_seconds()) / 60.0
                impact = event.get("impact", "").upper()
                if impact in ("HIGH", "TIER-1") and diff_minutes <= 30:
                    return MacroContext(
                        bias="NEUTRAL",
                        risk_level="HIGH",
                        event_lockout=True,
                        veto_trade=True,
                        reasoning=f"High-impact news release ({event.get('name')}) within {diff_minutes:.0f} mins. Order execution locked.",
                    )

        # 3. Live OpenAI LLM Reasoning (if API key is present)
        if self.client is not None:
            try:
                prompt = (
                    f"You are the Senior Macro Risk Analyst & Institutional Strategist for an algorithmic gold (XAUUSD) trading desk.\n"
                    f"Current Date/Time: {current_time} UTC\n"
                    f"Current Gold Price: ${current_price:.2f}\n"
                    f"Higher Timeframe (H4) Market Structure: {h4_trend_bias}\n"
                    f"Market Context:\n"
                    f"- US 10Y Real Yield: Steady (~1.85%)\n"
                    f"- US Dollar Index (DXY): Range-bound (~104.20)\n"
                    f"- Central Bank Gold Reserves: Consistent net central bank accumulation\n"
                    f"- Scheduled News: No immediate Tier-1 news release active\n\n"
                    f"Evaluate current institutional macroeconomic sentiment, inflation hedging, and safe-haven flows.\n"
                    f"CRITICAL INSTRUCTION:\n"
                    f"- Reserve veto_trade=true strictly for active high-risk shock events, unexpected geopolitical black swans, or high-impact news embargoes.\n"
                    f"- Otherwise, allow trading by setting veto_trade=false and align macro bias with market structure.\n\n"
                    f"Respond ONLY with a JSON object in this format:\n"
                    f'{{"bias": "BULLISH"|"BEARISH"|"NEUTRAL", "risk_level": "LOW"|"MODERATE"|"HIGH", "veto_trade": false, "reasoning": "concise institutional macro rationale"}}'
                )
                
                # Configure API parameters based on model family
                kwargs = {
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                }
                if any(m in self.model_name for m in ["o1", "o3", "gpt-5"]):
                    kwargs["max_completion_tokens"] = 400
                else:
                    kwargs["temperature"] = 0.2
                    kwargs["max_tokens"] = 250

                response = self.client.chat.completions.create(**kwargs)
                data = json.loads(response.choices[0].message.content)
                return MacroContext(
                    bias=data.get("bias", "NEUTRAL").upper(),
                    risk_level=data.get("risk_level", "LOW").upper(),
                    event_lockout=False,
                    veto_trade=bool(data.get("veto_trade", False)),
                    reasoning=f"[{self.model_name}] " + str(data.get("reasoning", "")),
                )
            except Exception:
                # Fallback smoothly to deterministic logic if network or quota issue occurs
                pass

        # 4. Deterministic Local Fallback Logic
        if h4_trend_bias == "BULLISH":
            bias = "BULLISH"
            reason = "H4 structural momentum is bullish (higher highs and strong buyers on higher timeframe)."
        elif h4_trend_bias == "BEARISH":
            bias = "BEARISH"
            reason = "H4 structural momentum is bearish (lower lows and institutional selling on higher timeframe)."
        else:
            bias = "NEUTRAL"
            reason = "Macro narrative and multi-timeframe structure are in balanced equilibrium."

        return MacroContext(
            bias=bias,
            risk_level="LOW",
            event_lockout=False,
            veto_trade=False,
            reasoning=reason,
        )
