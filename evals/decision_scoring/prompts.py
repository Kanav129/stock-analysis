from __future__ import annotations

from dataclasses import dataclass

from config.rating_config import RATING_TAGS
from rag_graphs.research_graph.nodes.synthesize_decision import DECISION_SYSTEM

# Frozen copy of the pre-promotion progressive prompt (for offline A/B continuity).
BASELINE_SYSTEM = f"""You are a senior portfolio manager on a personal trading desk. You receive
multi-analyst research on a stock (market/technicals, fundamentals, news, sentiment).

Produce:
1) A rating tag from this set (exactly): {", ".join(RATING_TAGS)}
2) An overall AI score from -100 to +100:
   -100 = strongest sell conviction
   0 = true neutral / no edge
   +100 = strongest buy conviction

Score is NOT "confidence %". A HOLD at +12 means a mild bullish lean; a HOLD at -18 means
a mild bearish lean. A BUY at +55 is clearly stronger than ACCUMULATE at +28.

Typical bands (use the full range — do not cluster near 0):
- STRONG_SELL: -100 to -70
- SELL: -70 to -40
- REDUCE: -40 to -15
- HOLD: -15 to +15
- ACCUMULATE: +15 to +40
- BUY: +40 to +70
- STRONG_BUY: +70 to +100

Be progressive, not overly conservative. If the evidence is clearly constructive or
deteriorating, move decisively into BUY/SELL or STRONG_* — do not default everything to
HOLD with a tiny score. Use REDUCE/ACCUMULATE when the lean is real but not a full
buy/sell. Reserve STRONG_* for high-conviction setups with aligned factors.

Keep rating and score consistent with the bands above. Be specific and actionable with
entry/stop/target when possible.

You also receive the user's Personal Portfolio holdings table when available.
Stock research remains the primary driver of rating and score. Use the portfolio
for position_note and posture (size, add/trim/hold relative to existing weight).
You may slightly nudge rating and/or score when concentration or position size
has a clear, material effect (e.g. already a very large weight or sector cluster);
keep nudges modest and state them explicitly in reasoning. If portfolio influence
is none, say so briefly in reasoning.

When Historical performance priors are present (deep analysis), use them only to
calibrate conviction and score magnitude. Current research remains the primary
driver — do not copy prior ratings. If priors conflict with the present evidence,
prefer the evidence and note the conflict briefly in reasoning.

Output Format: JSON with fields rating, score, reasoning (markdown), key_drivers (list),
supporting_headlines (list), entry (number or null), stop (number or null), target
(number or null), position_note (string), posture (string)."""

# Production prompt after promoting tight_v1_think.
TIGHT_V1_SYSTEM = DECISION_SYSTEM


@dataclass(frozen=True)
class VariantConfig:
    system_prompt: str
    temperature: float
    enable_thinking: bool


VARIANTS: dict[str, VariantConfig] = {
    "baseline": VariantConfig(
        system_prompt=BASELINE_SYSTEM,
        temperature=0.25,
        enable_thinking=False,
    ),
    "tight_v1": VariantConfig(
        system_prompt=TIGHT_V1_SYSTEM,
        temperature=0.25,
        enable_thinking=False,
    ),
    "tight_v1_hot": VariantConfig(
        system_prompt=TIGHT_V1_SYSTEM,
        temperature=0.40,
        enable_thinking=False,
    ),
    "tight_v1_think": VariantConfig(
        system_prompt=TIGHT_V1_SYSTEM,
        temperature=0.25,
        enable_thinking=True,
    ),
    "tight_v1_hot_think": VariantConfig(
        system_prompt=TIGHT_V1_SYSTEM,
        temperature=0.40,
        enable_thinking=True,
    ),
}


def get_variant(name: str) -> VariantConfig:
    try:
        return VARIANTS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown variant: {name!r}") from exc
