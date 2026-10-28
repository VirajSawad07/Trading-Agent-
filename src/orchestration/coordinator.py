"""Multi-Agent Decision Coordinator & Consensus Engine."""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
from src.agents.llm_agent import LLMAgent, MacroContext
from src.agents.quant_agent import QuantAgent, QuantAssessment
from src.agents.regime_agent import RegimeAgent, RegimeState
from src.risk.risk_engine import OrderProposal


from src.features.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
)


@dataclass
class CoordinatorDecision:
    action: str              # "BUY", "SELL", "HOLD"
    consensus_score: float   # 0.0 to 1.0
    proposal: Optional[OrderProposal]
    quant_assessment: QuantAssessment
    regime_state: RegimeState
    macro_context: MacroContext
    audit_trail: List[str]


class DecisionCoordinator:
    """Orchestrates multi-agent deliberations, detects conflicts, and forms trading consensus."""

    def __init__(
        self,
        quant_agent: Optional[QuantAgent] = None,
        regime_agent: Optional[RegimeAgent] = None,
        llm_agent: Optional[LLMAgent] = None,
        allow_technical_fallback: bool = True,
    ):
        self.quant_agent = quant_agent or QuantAgent()
        self.regime_agent = regime_agent or RegimeAgent()
        self.llm_agent = llm_agent or LLMAgent()
        self.allow_technical_fallback = allow_technical_fallback

    def arbitrate(
        self,
        df_history: pd.DataFrame,
        symbol: str = "XAUUSD",
        spread_points: float = 25.0,
        economic_events: Optional[List[Dict]] = None,
    ) -> CoordinatorDecision:
        audit_trail: List[str] = []
        current_time = df_history.index[-1] if isinstance(df_history.index, pd.DatetimeIndex) else pd.to_datetime(df_history["time"].iloc[-1])
        current_price = float(df_history["close"].iloc[-1])

        # 1. Query Specialized Agents in Parallel
        regime = self.regime_agent.analyze(df_history)
        quant = self.quant_agent.evaluate_bar(df_history, spread_points=spread_points)
        macro = self.llm_agent.evaluate_context(
            current_time=current_time,
            current_price=current_price,
            h4_trend_bias="BULLISH" if regime.regime == "TRENDING_BULL" else ("BEARISH" if regime.regime == "TRENDING_BEAR" else "NEUTRAL"),
            economic_events=economic_events,
        )

        audit_trail.append(f"Regime Agent: {regime.regime} (ADX={regime.adx_value}, Conf={regime.confidence:.0%})")
        audit_trail.append(f"Quant Agent: {quant.action} (P={quant.probability:.1%}, EV=${quant.expected_value:.2f})")
        audit_trail.append(f"Macro Agent: Bias={macro.bias}, Lockout={macro.event_lockout}")

        # 2. Check Absolute Macro Veto
        if macro.veto_trade:
            audit_trail.append(f"REJECTED by Macro Agent: {macro.reasoning}")
            return CoordinatorDecision(
                action="HOLD",
                consensus_score=0.0,
                proposal=None,
                quant_assessment=quant,
                regime_state=regime,
                macro_context=macro,
                audit_trail=audit_trail,
            )

        # 3. Check Regime Constraints (Lockout on Extreme Volatility Spikes)
        if regime.regime == "HIGH_VOLATILITY":
            audit_trail.append(f"REJECTED by Regime Agent: Extreme volatility ({regime.reason})")
            return CoordinatorDecision(
                action="HOLD",
                consensus_score=0.0,
                proposal=None,
                quant_assessment=quant,
                regime_state=regime,
                macro_context=macro,
                audit_trail=audit_trail,
            )

        # 4. Multi-Horizon Signal Generation (ML Alpha or Broader Technical Setups)
        candidate_action = "HOLD"
        suggested_sl = 0.0
        suggested_tp = 0.0
        strategy_id = "MultiAgent_Consensus"
        setup_confidence = 0.0

        # Path A: Machine Learning Edge
        if quant.confidence_pass and quant.action in ("BUY", "SELL"):
            candidate_action = quant.action
            suggested_sl = quant.suggested_sl
            suggested_tp = quant.suggested_tp
            setup_confidence = quant.probability
            strategy_id = "Quant_ML_Alpha"
            audit_trail.append(f"Signal Source: Machine Learning model edge ({quant.reason})")

        # Path B: Broader Technical Multi-Regime Setups (Pullbacks & Range Reversals)
        elif self.allow_technical_fallback and len(df_history) >= 50:
            close_series = df_history["close"]
            atr = float(calculate_atr(df_history, 14).iloc[-1])
            rsi = float(calculate_rsi(close_series, 14).iloc[-1])
            ema20 = float(calculate_ema(close_series, 20).iloc[-1])
            ema50 = float(calculate_ema(close_series, 50).iloc[-1])
            bb = calculate_bollinger_bands(close_series, 20, 2.0)
            bb_lower = float(bb["bb_lower"].iloc[-1])
            bb_upper = float(bb["bb_upper"].iloc[-1])

            # Setup 1: Trend-Following Pullback Entry
            if regime.regime == "TRENDING_BULL" and current_price > ema50 and 38.0 <= rsi <= 68.0:
                candidate_action = "BUY"
                suggested_sl = round(current_price - (2.0 * atr), 2)
                suggested_tp = round(current_price + (3.0 * atr), 2)
                strategy_id = "Trend_Pullback_Long"
                setup_confidence = 0.70
                audit_trail.append(f"Signal Source: Bullish Trend Pullback (RSI={rsi:.1f}, Price > EMA50)")

            elif regime.regime == "TRENDING_BEAR" and current_price < ema50 and 32.0 <= rsi <= 62.0:
                candidate_action = "SELL"
                suggested_sl = round(current_price + (2.0 * atr), 2)
                suggested_tp = round(current_price - (3.0 * atr), 2)
                strategy_id = "Trend_Pullback_Short"
                setup_confidence = 0.70
                audit_trail.append(f"Signal Source: Bearish Trend Pullback (RSI={rsi:.1f}, Price < EMA50)")

            # Setup 2: Range Mean-Reversion (Buy Support / Sell Resistance)
            elif regime.regime == "RANGING":
                if current_price <= bb_lower + (0.25 * atr) and rsi <= 38.0:
                    candidate_action = "BUY"
                    suggested_sl = round(current_price - (1.5 * atr), 2)
                    suggested_tp = round(current_price + (2.0 * atr), 2)
                    strategy_id = "Range_Reversal_Long"
                    setup_confidence = 0.65
                    audit_trail.append(f"Signal Source: Range Support Bounce (RSI={rsi:.1f} Oversold, BB Lower=${bb_lower:.2f})")

                elif current_price >= bb_upper - (0.25 * atr) and rsi >= 62.0:
                    candidate_action = "SELL"
                    suggested_sl = round(current_price + (1.5 * atr), 2)
                    suggested_tp = round(current_price - (2.0 * atr), 2)
                    strategy_id = "Range_Reversal_Short"
                    setup_confidence = 0.65
                    audit_trail.append(f"Signal Source: Range Resistance Rejection (RSI={rsi:.1f} Overbought, BB Upper=${bb_upper:.2f})")

        # If no setup fired, stay in cash
        if candidate_action == "HOLD":
            audit_trail.append("NO TRADE: Neither Quant statistical edge nor multi-regime technical setup active.")
            return CoordinatorDecision(
                action="HOLD",
                consensus_score=0.0,
                proposal=None,
                quant_assessment=quant,
                regime_state=regime,
                macro_context=macro,
                audit_trail=audit_trail,
            )

        # 5. Cross-Agent Directional Conflict Auditing
        if candidate_action == "BUY":
            if not regime.allow_buy:
                audit_trail.append(f"VETO: Proposed BUY, but Regime forbids long trades ({regime.reason})")
                return CoordinatorDecision(
                    action="HOLD",
                    consensus_score=0.0,
                    proposal=None,
                    quant_assessment=quant,
                    regime_state=regime,
                    macro_context=macro,
                    audit_trail=audit_trail,
                )
            if macro.bias == "BEARISH":
                audit_trail.append("VETO: Proposed BUY, but Macro Agent has strong BEARISH bias.")
                return CoordinatorDecision(
                    action="HOLD",
                    consensus_score=0.0,
                    proposal=None,
                    quant_assessment=quant,
                    regime_state=regime,
                    macro_context=macro,
                    audit_trail=audit_trail,
                )

        if candidate_action == "SELL":
            if not regime.allow_sell:
                audit_trail.append(f"VETO: Proposed SELL, but Regime forbids short trades ({regime.reason})")
                return CoordinatorDecision(
                    action="HOLD",
                    consensus_score=0.0,
                    proposal=None,
                    quant_assessment=quant,
                    regime_state=regime,
                    macro_context=macro,
                    audit_trail=audit_trail,
                )
            if macro.bias == "BULLISH":
                audit_trail.append("VETO: Proposed SELL, but Macro Agent has strong BULLISH bias.")
                return CoordinatorDecision(
                    action="HOLD",
                    consensus_score=0.0,
                    proposal=None,
                    quant_assessment=quant,
                    regime_state=regime,
                    macro_context=macro,
                    audit_trail=audit_trail,
                )

        # 6. Consensus Approved! Build Order Proposal
        consensus_score = (setup_confidence * 0.60) + (regime.confidence * 0.40)
        audit_trail.append(f"CONSENSUS REACHED: {candidate_action} approved via {strategy_id} (Score={consensus_score:.2f})")

        proposal = OrderProposal(
            symbol=symbol,
            action=candidate_action,
            entry_price=current_price,
            stop_loss=suggested_sl,
            take_profit=suggested_tp,
            strategy_id=strategy_id,
        )

        return CoordinatorDecision(
            action=candidate_action,
            consensus_score=round(consensus_score, 2),
            proposal=proposal,
            quant_assessment=quant,
            regime_state=regime,
            macro_context=macro,
            audit_trail=audit_trail,
        )
