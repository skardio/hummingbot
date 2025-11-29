# core/risk_scanner.py

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class TradeStatus(str, Enum):
    TRADE = "TRADE"
    TRADE_WITH_CAUTION = "TRADE_WITH_CAUTION"
    DO_NOT_TRADE = "DO_NOT_TRADE"


@dataclass
class RiskScores:
    volatility: int         # 0–100
    spreads: int            # 0–100
    latency: int            # 0–100
    liquidity: int          # 0–100
    exchange_status: int    # 0–100


@dataclass
class RiskResult:
    timestamp: float
    score: int
    status: TradeStatus
    scores: RiskScores
    explanation: str


class ArbitrageRiskScanner:
    """
    Berekent een globale 'Arbitrage Risk Score' (0–100) en status:
    - TRADE
    - TRADE_WITH_CAUTION
    - DO_NOT_TRADE
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        trade_min_score: int = 70,
        caution_min_score: int = 40,
    ):
        self.weights = weights or {
            "volatility": 0.25,
            "spreads": 0.25,
            "latency": 0.20,
            "liquidity": 0.20,
            "exchange_status": 0.10,
        }
        self.trade_min_score = trade_min_score
        self.caution_min_score = caution_min_score
        self._last_status: Optional[TradeStatus] = None
        self._last_result: Optional[RiskResult] = None

    # ---------- SCORING FUNCTIES PER FACTOR ----------

    def score_volatility(self, returns_1m: List[float]) -> int:
        """
        returns_1m: lijst van procentuele returns per minuut (bijv. 0.001 = 0.1%)
        Score 0–100: 0 = doodstil, 100 = extreem volatiel.
        """
        if not returns_1m or len(returns_1m) < 5:
            return 50  # neutraal als we het niet weten

        mean = sum(returns_1m) / len(returns_1m)
        var = sum((r - mean) ** 2 for r in returns_1m) / (len(returns_1m) - 1)
        std = math.sqrt(var)

        # typische std-per-minute ongeveer 0–0.5%
        # map 0–0.5% → 0–100 (clip)
        std_pct = std * 100
        score = min(int((std_pct / 0.5) * 100), 100)
        return max(0, score)

    def score_spreads(self, avg_spread_bps: float) -> int:
        """
        Gemiddelde spread in basispunten (1 bp = 0.01%)
        score hoog = goede arbitrage-kans (grote spreads).
        """
        if avg_spread_bps <= 0:
            return 10

        # 0–10 bps = 0–30 score
        # 10–50 bps = 30–80
        # >50 bps = 80–100
        if avg_spread_bps < 10:
            score = 3 * avg_spread_bps  # tot 30
        elif avg_spread_bps < 50:
            extra = avg_spread_bps - 10
            score = 30 + extra * 1.25  # tot 80
        else:
            extra = min(avg_spread_bps - 50, 50)
            score = 80 + extra * 0.4  # max 100

        return int(max(0, min(score, 100)))

    def score_latency(self, latency_ms_by_exchange: Dict[str, float]) -> int:
        """
        latency_ms_by_exchange: {"binance": 20.5, "kraken": 85.0}
        Score hoog = lage latency.
        """
        if not latency_ms_by_exchange:
            return 50

        avg_latency = sum(latency_ms_by_exchange.values()) / len(
            latency_ms_by_exchange
        )

        # 0–50 ms = 100–80
        # 50–200 ms = 80–40
        # >200 ms = 40–10
        if avg_latency <= 50:
            score = 100 - (avg_latency / 50) * 20  # 100→80
        elif avg_latency <= 200:
            extra = avg_latency - 50
            score = 80 - (extra / 150) * 40  # 80→40
        else:
            extra = min(avg_latency - 200, 800)
            score = 40 - (extra / 800) * 30  # 40→10

        return int(max(0, min(score, 100)))

    def score_liquidity(self, total_volume_24h_usd: float) -> int:
        """
        Totale 24h volume over je relevante pairs (inschatting).
        Score hoog = veel liquiditeit.
        """
        if total_volume_24h_usd <= 0:
            return 10

        # 0–1M = 10–40
        # 1M–50M = 40–80
        # >50M = 80–100
        if total_volume_24h_usd < 1_000_000:
            score = 10 + (total_volume_24h_usd / 1_000_000) * 30
        elif total_volume_24h_usd < 50_000_000:
            extra = total_volume_24h_usd - 1_000_000
            score = 40 + (extra / 49_000_000) * 40
        else:
            extra = min(total_volume_24h_usd - 50_000_000, 150_000_000)
            score = 80 + (extra / 150_000_000) * 20

        return int(max(0, min(score, 100)))

    def score_exchange_status(self, status_by_exchange: Dict[str, str]) -> int:
        """
        status_by_exchange: {"binance": "ok", "kraken": "degraded", "kucoin": "down"}
        """
        if not status_by_exchange:
            return 50

        base = 100
        for ex, status in status_by_exchange.items():
            s = status.lower()
            if "down" in s or "outage" in s:
                base -= 40
            elif "degrad" in s or "partial" in s:
                base -= 20
            elif "maintenance" in s:
                base -= 15

        return int(max(0, min(base, 100)))

    # ---------- COMBINATIE & UITLEG ----------

    def _combine_scores(self, scores: RiskScores) -> int:
        w = self.weights
        total = (
            scores.volatility * w.get("volatility", 0)
            + scores.spreads * w.get("spreads", 0)
            + scores.latency * w.get("latency", 0)
            + scores.liquidity * w.get("liquidity", 0)
            + scores.exchange_status * w.get("exchange_status", 0)
        )
        return int(max(0, min(total, 100)))

    def _status_from_score(self, score: int) -> TradeStatus:
        if score >= self.trade_min_score:
            return TradeStatus.TRADE
        if score >= self.caution_min_score:
            return TradeStatus.TRADE_WITH_CAUTION
        return TradeStatus.DO_NOT_TRADE

    def _build_explanation(
        self,
        scores: RiskScores,
        score: int,
        status: TradeStatus,
    ) -> str:
        parts = [f"Global risk score: {score}/100 → {status.value}"]

        # simpele 'AI-achtige' reasoning
        if scores.spreads >= 70:
            parts.append("• Spreads zijn ruim → goede arbitrage-kansen.")
        elif scores.spreads <= 40:
            parts.append("• Spreads zijn klein → minder arbitrage-potentieel.")

        if scores.volatility >= 70:
            parts.append("• Markt is zeer volatiel → meer kansen maar ook meer risico.")
        elif scores.volatility <= 30:
            parts.append("• Markt is erg rustig → weinig prijsbeweging.")

        if scores.latency <= 40:
            parts.append("• API-latency is hoog → risico op slechte fills / stale data.")
        elif scores.latency >= 80:
            parts.append("• API-latency is laag → goede uitvoerbaarheid van orders.")

        if scores.liquidity <= 40:
            parts.append("• Liquiditeit is beperkt → kans op slippage.")
        elif scores.liquidity >= 70:
            parts.append("• Veel liquiditeit → makkelijker in/uit grotere posities.")

        if scores.exchange_status <= 60:
            parts.append(
                "• Minstens één exchange heeft storingen/maintenance → extra risico."
            )

        return "\n".join(parts)

    # ---------- PUBLIEKE API ----------

    def evaluate(
        self,
        *,
        returns_1m: List[float],
        avg_spread_bps: float,
        latency_ms_by_exchange: Dict[str, float],
        total_volume_24h_usd: float,
        status_by_exchange: Dict[str, str],
    ) -> RiskResult:
        """
        Hoofd-entrypoint. Aan te roepen vanuit je main loop / scheduler.
        """
        scores = RiskScores(
            volatility=self.score_volatility(returns_1m),
            spreads=self.score_spreads(avg_spread_bps),
            latency=self.score_latency(latency_ms_by_exchange),
            liquidity=self.score_liquidity(total_volume_24h_usd),
            exchange_status=self.score_exchange_status(status_by_exchange),
        )

        global_score = self._combine_scores(scores)
        status = self._status_from_score(global_score)
        explanation = self._build_explanation(scores, global_score, status)

        result = RiskResult(
            timestamp=time.time(),
            score=global_score,
            status=status,
            scores=scores,
            explanation=explanation,
        )

        self._last_result = result
        self._last_status = status
        return result

    @property
    def last_result(self) -> Optional[RiskResult]:
        return self._last_result

    @property
    def last_status(self) -> Optional[TradeStatus]:
        return self._last_status
