from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Setup:
    """One trade setup in the standard format, whatever its source."""
    symbol: str                    # as written in the post, e.g. "XAUUSD"
    side: str                      # "BUY" or "SELL"
    entry: Optional[float]         # None only for MARKET orders
    sl: float
    tps: List[float] = field(default_factory=list)   # nearest first
    order_type: str = "LIMIT"      # LIMIT | STOP | MARKET
    entry2: Optional[float] = None # recorded, not traded (SOP: first entry)
    sl2: Optional[float] = None    # recorded, not traded (SOP: SL1)
    risk_mode: Optional[str] = None    # per-setup override: "persen" | "dolar"
    risk_value: Optional[float] = None
    source: str = ""
    note: str = ""
    raw: str = ""

    def key(self) -> str:
        return f"{self.symbol}|{self.side}|{self.entry}|{self.sl}|{','.join(map(str, self.tps))}"


# Setup lifecycle in the journal.
RECEIVED = "received"
REJECTED = "rejected"
AWAITING = "awaiting_confirm"
DECLINED = "declined"
PENDING = "pending"        # limit/stop orders placed, nothing filled yet
RUNNING = "running"        # at least one leg filled
DONE = "done"
CANCELLED = "cancelled"
EXPIRED = "expired"

ACTIVE = (PENDING, RUNNING)

# Leg states.
LEG_PENDING = "pending"
LEG_OPEN = "open"
LEG_TP = "closed_tp"
LEG_SL = "closed_sl"
LEG_CLOSED = "closed"      # closed by bot, user, or stop-out
LEG_CANCELLED = "cancelled"

LEG_FINAL = (LEG_TP, LEG_SL, LEG_CLOSED, LEG_CANCELLED)
