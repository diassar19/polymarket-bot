"""
Phase 1: Polymarket Trading Bot — Foundation
=============================================
This is the complete, runnable Phase 1 implementation.
It connects to the real Polymarket API, fetches live markets,
scans for edge opportunities, and paper-trades them.

SETUP INSTRUCTIONS (see bottom of file or run with --help)
"""

import os
import re
import sys
import json
import math
import time
import sqlite3
import logging
import argparse
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Third-party imports — install with: pip install requests websockets
# For LIVE trading only:  pip install py-clob-client
# ---------------------------------------------------------------------------
try:
    import requests
except ImportError:
    print("Run: pip install requests")
    sys.exit(1)

# Optional: py-clob-client for live trading (Phase 3)
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        OrderArgs, MarketOrderArgs, OrderType, BookParams
    )
    from py_clob_client.order_builder.constants import BUY, SELL
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False

# Optional: websockets for real-time streaming
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(level=logging.INFO):
    fmt = "%(asctime)s | %(name)-18s | %(levelname)-5s | %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")
    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

log = logging.getLogger("polybot")


# ============================================================================
# REMOVED: Weather and Sports models
# Bot now focuses only on crypto markets for better performance
# ============================================================================


# ============================================================================
# CRYPTO ASSET MAP (name/ticker → Binance symbol + Deribit currency)
# ============================================================================

CRYPTO_ASSET_MAP = {
    # name/ticker → (binance_symbol, deribit_currency_or_None)
    "bitcoin": ("BTCUSDT", "BTC"), "btc": ("BTCUSDT", "BTC"),
    "ethereum": ("ETHUSDT", "ETH"), "eth": ("ETHUSDT", "ETH"),
    "solana": ("SOLUSDT", "SOL"), "sol": ("SOLUSDT", "SOL"),
    "xrp": ("XRPUSDT", None), "ripple": ("XRPUSDT", None),
    "dogecoin": ("DOGEUSDT", None), "doge": ("DOGEUSDT", None),
    "cardano": ("ADAUSDT", None), "ada": ("ADAUSDT", None),
    "avalanche": ("AVAXUSDT", None), "avax": ("AVAXUSDT", None),
    "polygon": ("MATICUSDT", None), "matic": ("MATICUSDT", None),
    "polkadot": ("DOTUSDT", None), "dot": ("DOTUSDT", None),
    "chainlink": ("LINKUSDT", None), "link": ("LINKUSDT", None),
    "litecoin": ("LTCUSDT", None), "ltc": ("LTCUSDT", None),
    "uniswap": ("UNIUSDT", None), "uni": ("UNIUSDT", None),
    "shiba inu": ("SHIBUSDT", None), "shib": ("SHIBUSDT", None),
    "tron": ("TRXUSDT", None), "trx": ("TRXUSDT", None),
    "near": ("NEARUSDT", None), "near protocol": ("NEARUSDT", None),
    "pepe": ("PEPEUSDT", None),
    "sui": ("SUIUSDT", None),
    "aptos": ("APTUSDT", None), "apt": ("APTUSDT", None),
    "arbitrum": ("ARBUSDT", None), "arb": ("ARBUSDT", None),
    "optimism": ("OPUSDT", None),
    "bnb": ("BNBUSDT", None), "binance coin": ("BNBUSDT", None),
}


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class Config:
    """All tunable parameters. Override via environment variables or CLI."""
    
    # --- API endpoints ---
    gamma_api: str = "https://gamma-api.polymarket.com"
    clob_api: str = "https://clob.polymarket.com"
    data_api: str = "https://data-api.polymarket.com"
    ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    # --- Authentication (only needed for live trading) ---
    # NEVER hardcode keys here. Use environment variables:
    #   export POLYMARKET_PRIVATE_KEY="your-key"
    #   export POLYMARKET_FUNDER_ADDRESS="your-address"
    private_key: str = ""
    funder_address: str = ""
    chain_id: int = 137          # Polygon mainnet
    signature_type: int = 0      # 0=EOA, 1=email/Magic wallet
    
    # --- Kelly sizing ---
    kelly_fraction: float = 0.25
    max_single_position_pct: float = 0.07
    max_correlated_exposure_pct: float = 0.15
    max_total_exposure_pct: float = 0.50
    max_positions: int = 10
    
    # --- Edge thresholds ---
    min_edge: float = 0.05           # 5¢ minimum edge
    min_ev_per_dollar: float = 0.08  # 8% minimum ROI
    min_volume_24h: float = 5000     # Skip illiquid markets
    min_liquidity: float = 1000      # Minimum order book depth
    
    # --- Risk management ---
    initial_bankroll: float = 10000.0
    daily_drawdown_limit: float = 0.10
    max_book_depth_pct: float = 0.50
    
    # --- Scanning ---
    scan_interval_seconds: int = 60
    markets_per_page: int = 50
    max_pages: int = 10              # Fetch up to 500 markets
    
    # --- Paper trading ---
    paper_trading: bool = True
    db_path: str = "polybot_trades.db"

    @classmethod
    def from_env(cls):
        """Load config with env var overrides."""
        c = cls()
        c.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        c.funder_address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
        sig = os.getenv("POLYMARKET_SIGNATURE_TYPE", "0")
        c.signature_type = int(sig)
        bankroll = os.getenv("POLYMARKET_BANKROLL", "")
        if bankroll:
            c.initial_bankroll = float(bankroll)
        return c


# ============================================================================
# DATA MODELS
# ============================================================================

class Side(Enum):
    YES = "YES"
    NO = "NO"

@dataclass
class Market:
    """Parsed market from Gamma API."""
    market_id: str
    condition_id: str
    question: str
    category: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume_24h: float
    total_volume: float
    liquidity: float
    end_date: Optional[datetime]
    slug: str
    active: bool
    
    @property
    def spread(self) -> float:
        return abs(1.0 - (self.yes_price + self.no_price))
    
    @property
    def implied_prob(self) -> float:
        return self.yes_price

@dataclass
class OrderBookLevel:
    price: float
    size: float

@dataclass
class OrderBook:
    token_id: str
    bids: list  # List of OrderBookLevel
    asks: list  # List of OrderBookLevel
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    depth_bid: float = 0.0
    depth_ask: float = 0.0

@dataclass
class Signal:
    """A detected trading opportunity."""
    market: Market
    side: Side
    p_true: float
    market_price: float
    edge: float
    ev_per_share: float
    ev_per_dollar: float
    kelly_full: float
    kelly_quarter: float
    position_size_usd: float
    confidence: float
    reasoning: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class PaperPosition:
    """Tracks a paper trade."""
    id: int
    market_id: str
    question: str
    side: Side
    entry_price: float
    shares: float
    size_usd: float
    p_true: float
    entry_time: datetime
    yes_token_id: str = ""
    no_token_id: str = ""
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    closed: bool = False
    exit_price: float = 0.0
    realized_pnl: float = 0.0


# ============================================================================
# MODULE 1: MARKET DATA FETCHER
# ============================================================================

class MarketFetcher:
    """
    Fetches market data from Polymarket's Gamma API (no auth needed).
    
    Three API layers:
    - Gamma API (gamma-api.polymarket.com) — market metadata, no auth
    - CLOB API (clob.polymarket.com) — order books & trading
    - Data API (data-api.polymarket.com) — user positions & history
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketBot/1.0"
        })
        self.log = logging.getLogger("MarketFetcher")
    
    def health_check(self) -> bool:
        """Verify API connectivity."""
        try:
            # Gamma API health
            r = self.session.get(f"{self.config.gamma_api}/markets", 
                                params={"limit": 1}, timeout=10)
            r.raise_for_status()
            self.log.info("Gamma API: OK")
            
            # CLOB API health
            r2 = self.session.get(f"{self.config.clob_api}/", timeout=10)
            self.log.info(f"CLOB API: OK")
            
            return True
        except Exception as e:
            self.log.error(f"API health check failed: {e}")
            return False
    
    def fetch_all_active_markets(self) -> list[Market]:
        """
        Fetch all active markets with pagination.
        Uses the events endpoint (recommended by Polymarket docs).
        Falls back to markets endpoint if needed.
        """
        all_markets = []
        offset = 0
        
        for page in range(self.config.max_pages):
            try:
                # Fetch from Gamma API — markets endpoint with filters
                params = {
                    "active": "true",
                    "closed": "false",
                    "limit": self.config.markets_per_page,
                    "offset": offset,
                    "order": "volume24hr",
                    "ascending": "false",
                }
                
                r = self.session.get(
                    f"{self.config.gamma_api}/markets",
                    params=params,
                    timeout=15
                )
                r.raise_for_status()
                raw_markets = r.json()
                
                if not raw_markets:
                    break  # No more markets
                
                for m in raw_markets:
                    parsed = self._parse_market(m)
                    if parsed:
                        all_markets.append(parsed)
                
                offset += self.config.markets_per_page
                time.sleep(0.2)  # Rate limiting courtesy
                
            except Exception as e:
                self.log.warning(f"Failed to fetch page {page}: {e}")
                break
        
        self.log.info(f"Fetched {len(all_markets)} active markets")
        return all_markets
    
    def _parse_market(self, raw: dict) -> Optional[Market]:
        """Parse a raw Gamma API market response into our Market dataclass."""
        try:
            # Extract token IDs from clobTokenIds
            clob_tokens = raw.get("clobTokenIds", "")
            if isinstance(clob_tokens, str):
                try:
                    clob_tokens = json.loads(clob_tokens) if clob_tokens else []
                except json.JSONDecodeError:
                    clob_tokens = []
            
            if not clob_tokens or len(clob_tokens) < 2:
                return None
            
            # Extract prices from outcomePrices
            prices = raw.get("outcomePrices", "")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices) if prices else []
                except json.JSONDecodeError:
                    prices = []
            
            if not prices or len(prices) < 2:
                return None
            
            yes_price = float(prices[0])
            no_price = float(prices[1])
            
            # Skip clearly broken markets
            if yes_price <= 0 or no_price <= 0:
                return None
            if yes_price >= 1.0 or no_price >= 1.0:
                return None  # Already resolved
            
            # Parse end date
            end_str = raw.get("endDate") or raw.get("end_date_iso")
            end_date = None
            if end_str:
                try:
                    end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass
            
            # Determine category from tags
            tags = raw.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = []
            category = tags[0].get("label", "unknown") if tags and isinstance(tags, list) and tags else "unknown"
            
            return Market(
                market_id=str(raw.get("id", "")),
                condition_id=raw.get("conditionId", ""),
                question=raw.get("question", "Unknown"),
                category=category,
                yes_token_id=clob_tokens[0],
                no_token_id=clob_tokens[1],
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=float(raw.get("volume24hr", 0) or 0),
                total_volume=float(raw.get("volume", 0) or 0),
                liquidity=float(raw.get("liquidity", 0) or 0),
                end_date=end_date,
                slug=raw.get("slug", ""),
                active=bool(raw.get("active", False)),
            )
        except Exception as e:
            self.log.debug(f"Failed to parse market: {e}")
            return None
    
    def fetch_order_book(self, token_id: str) -> Optional[OrderBook]:
        """Fetch order book from CLOB API (no auth needed for reads)."""
        try:
            r = self.session.get(
                f"{self.config.clob_api}/book",
                params={"token_id": token_id},
                timeout=10
            )
            r.raise_for_status()
            data = r.json()
            
            bids = [OrderBookLevel(float(b["price"]), float(b["size"])) 
                    for b in data.get("bids", [])]
            asks = [OrderBookLevel(float(a["price"]), float(a["size"])) 
                    for a in data.get("asks", [])]
            
            best_bid = bids[0].price if bids else 0
            best_ask = asks[0].price if asks else 1.0
            
            return OrderBook(
                token_id=token_id,
                bids=bids,
                asks=asks,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=best_ask - best_bid,
                depth_bid=sum(b.size for b in bids),
                depth_ask=sum(a.size for a in asks),
            )
        except Exception as e:
            self.log.debug(f"Failed to fetch order book for {token_id}: {e}")
            return None
    
    def fetch_price(self, token_id: str) -> Optional[float]:
        """Fetch midpoint price from CLOB API."""
        try:
            r = self.session.get(
                f"{self.config.clob_api}/midpoint",
                params={"token_id": token_id},
                timeout=10
            )
            r.raise_for_status()
            data = r.json()
            return float(data.get("mid", 0))
        except Exception as e:
            self.log.debug(f"Failed to fetch price for {token_id}: {e}")
            return None


# ============================================================================
# MODULE 2: MATH ENGINE (from polymarket_bot.py)
# ============================================================================

class MathEngine:
    """All the core math: EV, Kelly, Bayesian updates."""
    
    @staticmethod
    def expected_value(p_true: float, market_price: float) -> float:
        """EV per share = p_true - market_price."""
        return p_true - market_price
    
    @staticmethod
    def ev_per_dollar(p_true: float, market_price: float) -> float:
        """EV per dollar invested."""
        if market_price <= 0:
            return 0
        return (p_true - market_price) / market_price
    
    @staticmethod
    def kelly_full(p_true: float, market_price: float) -> float:
        """Full Kelly fraction (don't use directly — too aggressive)."""
        if market_price <= 0 or market_price >= 1 or p_true <= market_price:
            return 0.0
        b = (1.0 - market_price) / market_price
        q = 1.0 - p_true
        return max((b * p_true - q) / b, 0.0)
    
    @staticmethod
    def kelly_quarter(p_true: float, market_price: float) -> float:
        """Quarter-Kelly — empirically validated sweet spot."""
        return MathEngine.kelly_full(p_true, market_price) * 0.25
    
    @staticmethod
    def position_size(p_true: float, market_price: float, 
                      bankroll: float, config: Config,
                      book_depth: float = float('inf')) -> float:
        """Final position size in USD with all safety caps."""
        kelly_pct = MathEngine.kelly_quarter(p_true, market_price)
        kelly_pct = min(kelly_pct, config.max_single_position_pct)
        size = kelly_pct * bankroll
        size = min(size, book_depth * config.max_book_depth_pct)
        if size < 5.0:
            return 0.0
        return round(size, 2)
    
    @staticmethod
    def bayesian_shrink(estimate: float, base_rate: float = 0.5, 
                        shrinkage: float = 0.20) -> float:
        """Pull estimate toward base rate to combat overconfidence."""
        return (1.0 - shrinkage) * estimate + shrinkage * base_rate
    
    @staticmethod
    def bayesian_update(prior: float, likelihood_ratio: float) -> float:
        """Update probability given new evidence."""
        if prior <= 0 or prior >= 1:
            return prior
        prior_odds = prior / (1.0 - prior)
        posterior_odds = prior_odds * likelihood_ratio
        posterior = posterior_odds / (1.0 + posterior_odds)
        return max(0.01, min(0.99, posterior))


# ============================================================================
# MODULE 2.5: CRYPTO PROBABILITY MODEL (Black-Scholes on Binance/Deribit data)
# ============================================================================

@dataclass
class CryptoQuery:
    """Parsed crypto price question data."""
    asset: str                          # e.g. "bitcoin"
    binance_symbol: str                 # e.g. "BTCUSDT"
    deribit_currency: Optional[str]     # e.g. "BTC" or None
    direction: str                      # "above", "below", "between"
    strike: float                       # primary strike price
    strike_high: Optional[float] = None # upper bound for "between" queries
    target_date: Optional[datetime] = None


class CryptoModel:
    """
    Uses Binance spot price + historical vol and Deribit implied vol
    to compute probabilities for crypto price markets via Black-Scholes.
    """

    BINANCE_BASE = "https://api.binance.com"
    DERIBIT_BASE = "https://www.deribit.com/api/v2"
    CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self.log = logging.getLogger("CryptoModel")
        self._cache: dict[str, tuple[float, any]] = {}  # key -> (timestamp, data)

    def try_estimate(self, market: Market) -> Optional[tuple[float, float, str]]:
        """
        Main entry: parse question → fetch price/vol → Black-Scholes → probability.
        Returns (p_true, confidence, reasoning) or None if not a crypto market.
        """
        query = self._parse_crypto_question(market.question)
        if query is None:
            return None

        # Fetch current spot price
        spot = self._fetch_spot_price(query.binance_symbol)
        if spot is None:
            self.log.debug(f"CryptoModel: failed to fetch spot for {query.binance_symbol}")
            return None

        # Compute time to expiry in years
        # Prefer market end_date over parsed question date when available
        now = datetime.now(timezone.utc)
        expiry = query.target_date
        if market.end_date and expiry:
            # If parsed date is way beyond market end_date, use market end_date
            if expiry > market.end_date + timedelta(days=7):
                expiry = market.end_date
        elif market.end_date and not expiry:
            expiry = market.end_date

        if expiry:
            dt = (expiry - now).total_seconds()
            if dt <= 0:
                return None
            T = dt / (365.25 * 24 * 3600)
        else:
            # No date at all — default to 30 days
            T = 30.0 / 365.25

        # Fetch volatility (blended implied + historical)
        vol = self._fetch_blended_vol(query.binance_symbol, query.deribit_currency)
        if vol is None or vol <= 0:
            self.log.debug(f"CryptoModel: failed to fetch vol for {query.asset}")
            return None

        # Black-Scholes probability
        if query.direction == "above":
            p = self._prob_above(spot, query.strike, vol, T)
        elif query.direction == "below":
            p = 1.0 - self._prob_above(spot, query.strike, vol, T)
        elif query.direction == "between":
            p_above_low = self._prob_above(spot, query.strike, vol, T)
            p_above_high = self._prob_above(spot, query.strike_high, vol, T)
            p = p_above_low - p_above_high
        else:
            return None

        p = max(0.02, min(0.98, p))
        confidence = self._compute_confidence(spot, query.strike, vol, T,
                                               query.deribit_currency is not None)

        fmt_strike = f"${query.strike:,.2f}" if query.strike < 10 else f"${query.strike:,.0f}"
        fmt_high = ""
        if query.strike_high:
            fmt_high = f"-${query.strike_high:,.2f}" if query.strike_high < 10 else f"-${query.strike_high:,.0f}"
        reasoning = (
            f"CryptoModel: {query.asset} {query.direction} {fmt_strike}{fmt_high}"
            f", spot=${spot:,.2f}, vol={vol:.1%}, T={T:.3f}y, p={p:.3f}"
        )
        self.log.info(reasoning)
        return (p, confidence, reasoning)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_crypto_question(self, question: str) -> Optional[CryptoQuery]:
        """Detect crypto price markets and extract parameters."""
        q = question.lower().strip()

        # Must mention "price" or known crypto asset in a price context
        # Pattern: "Will the price of ASSET be above/below/between $X..."
        # Also: "Will ASSET reach $X..."
        # Also: "Will ASSET be above/below $X..."

        # Try to identify asset
        asset_name = None
        binance_sym = None
        deribit_cur = None

        for name, (bsym, dcur) in CRYPTO_ASSET_MAP.items():
            # Match asset name as whole word
            if re.search(r'\b' + re.escape(name) + r'\b', q):
                asset_name = name
                binance_sym = bsym
                deribit_cur = dcur
                break

        if asset_name is None:
            return None

        # Extract strike price(s) — look for dollar amounts
        # "above $74,000" / "below $0.90" / "between $70,000 and $74,000" / "reach $100,000"
        # Also handle decimals and commas

        # Between pattern
        m = re.search(
            r'between\s+\$?([\d,]+(?:\.\d+)?)\s*(?:and|to|-)\s*\$?([\d,]+(?:\.\d+)?)',
            q
        )
        if m:
            strike_low = float(m.group(1).replace(",", ""))
            strike_high = float(m.group(2).replace(",", ""))
            target_date = self._extract_date(q)
            return CryptoQuery(
                asset=asset_name, binance_symbol=binance_sym,
                deribit_currency=deribit_cur, direction="between",
                strike=strike_low, strike_high=strike_high,
                target_date=target_date,
            )

        # Above/below/reach pattern
        m = re.search(
            r'(?:above|over|exceed|higher than|more than|at least|reach|hit|top)\s+'
            r'\$?([\d,]+(?:\.\d+)?)',
            q
        )
        if m:
            strike = float(m.group(1).replace(",", ""))
            target_date = self._extract_date(q)
            return CryptoQuery(
                asset=asset_name, binance_symbol=binance_sym,
                deribit_currency=deribit_cur, direction="above",
                strike=strike, target_date=target_date,
            )

        m = re.search(
            r'(?:below|under|less than|lower than|at most|drop below|fall below)\s+'
            r'\$?([\d,]+(?:\.\d+)?)',
            q
        )
        if m:
            strike = float(m.group(1).replace(",", ""))
            target_date = self._extract_date(q)
            return CryptoQuery(
                asset=asset_name, binance_symbol=binance_sym,
                deribit_currency=deribit_cur, direction="below",
                strike=strike, target_date=target_date,
            )

        # Generic: "be $X or higher" / "$X or lower"
        m = re.search(
            r'\$?([\d,]+(?:\.\d+)?)\s+or\s+(higher|lower|more|less)',
            q
        )
        if m:
            strike = float(m.group(1).replace(",", ""))
            direction = "above" if m.group(2) in ("higher", "more") else "below"
            target_date = self._extract_date(q)
            return CryptoQuery(
                asset=asset_name, binance_symbol=binance_sym,
                deribit_currency=deribit_cur, direction=direction,
                strike=strike, target_date=target_date,
            )

        return None

    def _extract_date(self, text: str) -> Optional[datetime]:
        """Extract a date from question text."""
        now = datetime.now(timezone.utc)

        # "by end of 2026" / "by end of year"
        m = re.search(r'by\s+(?:the\s+)?end\s+of\s+(\d{4})', text)
        if m:
            year = int(m.group(1))
            return datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)

        # "on March 17" / "on March 17, 2026"
        m = re.search(r'on\s+(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)', text)
        if m:
            date_str = m.group(1).strip().rstrip(",")
            for fmt in ["%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y", "%B %d", "%b %d"]:
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    if "%Y" not in fmt:
                        parsed = parsed.replace(year=now.year)
                        if parsed.replace(tzinfo=timezone.utc) < now - timedelta(days=1):
                            parsed = parsed.replace(year=now.year + 1)
                    return parsed.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

        # "by March 17" / "before April 1"
        m = re.search(r'(?:by|before)\s+(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)', text)
        if m:
            date_str = m.group(1).strip().rstrip(",")
            for fmt in ["%B %d %Y", "%B %d, %Y", "%B %d", "%b %d"]:
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    if "%Y" not in fmt:
                        parsed = parsed.replace(year=now.year)
                        if parsed.replace(tzinfo=timezone.utc) < now - timedelta(days=1):
                            parsed = parsed.replace(year=now.year + 1)
                    return parsed.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

        return None

    # ------------------------------------------------------------------
    # API Fetching
    # ------------------------------------------------------------------

    def _get_cached(self, key: str):
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self.CACHE_TTL:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data):
        self._cache[key] = (time.time(), data)

    def _fetch_spot_price(self, symbol: str) -> Optional[float]:
        """Fetch current spot price from Binance."""
        cache_key = f"spot_{symbol}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            r = requests.get(
                f"{self.BINANCE_BASE}/api/v3/ticker/price",
                params={"symbol": symbol},
                timeout=10,
            )
            r.raise_for_status()
            price = float(r.json()["price"])
            self._set_cache(cache_key, price)
            return price
        except Exception as e:
            self.log.debug(f"Binance spot price error for {symbol}: {e}")
            return None

    def _fetch_historical_vol(self, symbol: str, hours: int = 168) -> Optional[float]:
        """
        Compute annualized historical volatility from Binance hourly klines.
        Default: 7 days of hourly data.
        """
        cache_key = f"histvol_{symbol}_{hours}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            r = requests.get(
                f"{self.BINANCE_BASE}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": "1h",
                    "limit": min(hours, 1000),
                },
                timeout=15,
            )
            r.raise_for_status()
            klines = r.json()

            if len(klines) < 24:
                return None

            # Close prices
            closes = [float(k[4]) for k in klines]

            # Log returns
            log_returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    log_returns.append(math.log(closes[i] / closes[i - 1]))

            if len(log_returns) < 20:
                return None

            # Annualized vol: std of hourly returns * sqrt(8760 hours/year)
            mean_r = sum(log_returns) / len(log_returns)
            var = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
            hourly_std = math.sqrt(var)
            annual_vol = hourly_std * math.sqrt(8760)

            self._set_cache(cache_key, annual_vol)
            return annual_vol

        except Exception as e:
            self.log.debug(f"Binance klines error for {symbol}: {e}")
            return None

    def _fetch_deribit_iv(self, currency: str) -> Optional[float]:
        """
        Fetch implied volatility from Deribit public API.
        Returns annualized IV as a decimal (e.g. 0.65 for 65%).
        """
        if currency is None:
            return None

        cache_key = f"deribit_iv_{currency}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            r = requests.get(
                f"{self.DERIBIT_BASE}/public/get_historical_volatility",
                params={"currency": currency},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()

            # Response: {"result": [[timestamp, vol], ...]}
            # vol is in percentage (e.g. 65.5 = 65.5%)
            result = data.get("result", [])
            if not result:
                return None

            # Use most recent IV value
            latest_iv = float(result[-1][1]) / 100.0
            self._set_cache(cache_key, latest_iv)
            return latest_iv

        except Exception as e:
            self.log.debug(f"Deribit IV error for {currency}: {e}")
            return None

    def _fetch_blended_vol(self, binance_symbol: str,
                            deribit_currency: Optional[str]) -> Optional[float]:
        """
        Blend implied vol (Deribit) and historical vol (Binance).
        70% implied + 30% historical when both available.
        Falls back to historical-only.
        """
        hist_vol = self._fetch_historical_vol(binance_symbol)
        impl_vol = self._fetch_deribit_iv(deribit_currency)

        if impl_vol is not None and hist_vol is not None:
            return 0.70 * impl_vol + 0.30 * hist_vol
        elif hist_vol is not None:
            return hist_vol
        elif impl_vol is not None:
            return impl_vol
        return None

    # ------------------------------------------------------------------
    # Black-Scholes Probability
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Standard normal CDF using math.erf."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def _prob_above(self, spot: float, strike: float,
                    vol: float, T: float) -> float:
        """
        P(S_T > K) under Black-Scholes (risk-neutral, no drift for prediction markets).
        d2 = (ln(S/K) - 0.5 * sigma^2 * T) / (sigma * sqrt(T))
        P(S > K) = N(d2)
        """
        if spot <= 0 or strike <= 0 or vol <= 0 or T <= 0:
            return 0.5

        sqrt_T = math.sqrt(T)
        d2 = (math.log(spot / strike) - 0.5 * vol * vol * T) / (vol * sqrt_T)
        return self._norm_cdf(d2)

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _compute_confidence(self, spot: float, strike: float,
                            vol: float, T: float,
                            has_implied_vol: bool) -> float:
        """
        Confidence based on:
        - Time horizon (shorter = more confident)
        - Distance from strike (farther = more confident in direction)
        - Vol source quality (implied > historical)
        """
        # Time factor: confidence drops for long horizons
        time_factor = math.exp(-0.5 * T)  # halves roughly every 1.4 years
        time_factor = max(0.3, min(1.0, time_factor))

        # Distance factor: how many sigmas away is the strike?
        if vol > 0 and T > 0:
            sigmas = abs(math.log(spot / strike)) / (vol * math.sqrt(T))
            distance_factor = min(1.0, 0.4 + 0.2 * sigmas)
        else:
            distance_factor = 0.4

        # Vol source quality
        vol_factor = 0.85 if has_implied_vol else 0.65

        confidence = time_factor * distance_factor * vol_factor
        return max(0.15, min(0.90, confidence))


class ProbabilityEstimator:
    """
    Crypto-focused probability estimator.

    Uses Black-Scholes model with Binance spot prices and Deribit implied volatility
    to estimate probabilities for crypto price prediction markets.

    Falls back to structural arbitrage detection for other markets.
    """

    def __init__(self, config: Config):
        self.config = config
        self.crypto_model = CryptoModel()
        self.log = logging.getLogger("ProbEstimator")

    def estimate(self, market: Market) -> Optional[tuple[float, float, str]]:
        """
        Estimate true probability for a market.

        Returns: (p_true, confidence, reasoning) or None if no edge.

        Pipeline:
        1. Crypto (Black-Scholes on Binance/Deribit data)
        2. Arbitrage (structural mispricing)
        """

        # Strategy 1: Crypto model (Black-Scholes)
        try:
            crypto_result = self.crypto_model.try_estimate(market)
            if crypto_result is not None:
                return crypto_result
        except Exception:
            pass

        # Strategy 2: Arbitrage check — YES + NO should = 1.00
        price_sum = market.yes_price + market.no_price
        if price_sum < 0.97:
            gap = 1.0 - price_sum
            return (
                market.yes_price + gap/2,
                0.9,
                f"Structural arbitrage: YES+NO={price_sum:.3f}, gap={gap:.3f}"
            )

        if price_sum > 1.03:
            gap = price_sum - 1.0
            return (
                market.yes_price - gap/2,
                0.9,
                f"Reverse arb: YES+NO={price_sum:.3f}, gap={gap:.3f}"
            )

        return None


# ============================================================================
# MODULE 4: EDGE SCANNER
# ============================================================================

class EdgeScanner:
    """Combines market data + probability estimates to find trade signals."""
    
    def __init__(self, config: Config, estimator: ProbabilityEstimator):
        self.config = config
        self.estimator = estimator
        self.log = logging.getLogger("EdgeScanner")
    
    def scan(self, markets: list[Market], bankroll: float) -> list[Signal]:
        """Scan all markets and return ranked trade signals."""
        signals = []
        
        for market in markets:
            # Filter: skip near-resolved markets (penny markets / near-$1)
            if market.yes_price < 0.03 or market.yes_price > 0.97:
                continue
            # Filter: minimum liquidity and volume
            if market.volume_24h < self.config.min_volume_24h:
                continue
            if market.liquidity < self.config.min_liquidity:
                continue
            
            # Get probability estimate
            estimate = self.estimator.estimate(market)
            if estimate is None:
                continue
            
            p_true, confidence, reasoning = estimate
            
            # Apply Bayesian shrinkage (combat overconfidence)
            p_true = MathEngine.bayesian_shrink(p_true, 0.5, 0.20)
            
            # Determine side
            yes_edge = p_true - market.yes_price
            no_edge = (1.0 - p_true) - market.no_price
            
            if yes_edge > no_edge and yes_edge > 0:
                side = Side.YES
                edge = yes_edge
                mkt_price = market.yes_price
                p_for_side = p_true
            elif no_edge > 0:
                side = Side.NO
                edge = no_edge
                mkt_price = market.no_price
                p_for_side = 1.0 - p_true
            else:
                continue
            
            # Minimum edge filter
            if edge < self.config.min_edge:
                continue
            
            # Calculate all math
            ev = MathEngine.expected_value(p_for_side, mkt_price)
            ev_dollar = MathEngine.ev_per_dollar(p_for_side, mkt_price)
            
            if ev_dollar < self.config.min_ev_per_dollar:
                continue
            
            kelly_f = MathEngine.kelly_full(p_for_side, mkt_price)
            kelly_q = MathEngine.kelly_quarter(p_for_side, mkt_price)
            size = MathEngine.position_size(
                p_for_side, mkt_price, bankroll, 
                self.config, market.liquidity
            )
            
            if size <= 0:
                continue
            
            signal = Signal(
                market=market,
                side=side,
                p_true=p_for_side,
                market_price=mkt_price,
                edge=edge,
                ev_per_share=ev,
                ev_per_dollar=ev_dollar,
                kelly_full=kelly_f,
                kelly_quarter=kelly_q,
                position_size_usd=size,
                confidence=confidence,
                reasoning=reasoning,
            )
            signals.append(signal)
        
        # Rank by EV per dollar (best first)
        signals.sort(key=lambda s: s.ev_per_dollar, reverse=True)
        
        self.log.info(f"Found {len(signals)} tradeable signals from {len(markets)} markets")
        return signals


# ============================================================================
# MODULE 5: RISK MANAGER
# ============================================================================

class RiskManager:
    """Enforces all risk rules before allowing trades."""
    
    def __init__(self, config: Config):
        self.config = config
        self.log = logging.getLogger("RiskManager")
    
    def check(self, signal: Signal, positions: list[PaperPosition],
              bankroll: float, daily_pnl: float) -> tuple[bool, str]:
        """Returns (approved, reason)."""
        
        # Daily drawdown circuit breaker
        if daily_pnl < 0 and abs(daily_pnl) / bankroll >= self.config.daily_drawdown_limit:
            return False, f"Daily drawdown limit ({self.config.daily_drawdown_limit:.0%})"
        
        # Max positions
        open_positions = [p for p in positions if not p.closed]
        if len(open_positions) >= self.config.max_positions:
            return False, f"Max positions ({self.config.max_positions})"
        
        # Total exposure
        total_exposure = sum(p.size_usd for p in open_positions)
        new_exposure = (total_exposure + signal.position_size_usd) / bankroll
        if new_exposure > self.config.max_total_exposure_pct:
            return False, f"Exposure limit ({new_exposure:.0%} > {self.config.max_total_exposure_pct:.0%})"
        
        # Already in this market?
        for p in open_positions:
            if p.market_id == signal.market.market_id:
                return False, "Already positioned in this market"
        
        # Wide spread check
        if signal.market.spread > 0.06:
            return False, f"Spread too wide ({signal.market.spread:.3f})"
        
        return True, "Approved"


# ============================================================================
# MODULE 6: TRADE LOGGER (SQLite)
# ============================================================================

class TradeDB:
    """SQLite database for logging all signals and paper trades."""
    
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self.log = logging.getLogger("TradeDB")
    
    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_id TEXT,
                question TEXT,
                side TEXT,
                p_true REAL,
                market_price REAL,
                edge REAL,
                ev_per_share REAL,
                ev_per_dollar REAL,
                kelly_quarter REAL,
                position_size REAL,
                confidence REAL,
                reasoning TEXT,
                approved INTEGER,
                rejection_reason TEXT
            );
            
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                timestamp TEXT NOT NULL,
                market_id TEXT,
                question TEXT,
                side TEXT,
                entry_price REAL,
                shares REAL,
                size_usd REAL,
                p_true REAL,
                closed INTEGER DEFAULT 0,
                exit_price REAL DEFAULT 0,
                exit_timestamp TEXT,
                pnl REAL DEFAULT 0,
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            );
            
            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                bankroll REAL,
                signals_found INTEGER,
                trades_taken INTEGER,
                open_positions INTEGER,
                daily_pnl REAL,
                total_pnl REAL,
                brier_score REAL
            );

            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                question TEXT,
                p_true REAL NOT NULL,
                market_price REAL,
                side TEXT,
                source TEXT,
                resolved INTEGER DEFAULT 0,
                outcome REAL,
                resolved_timestamp TEXT
            );
        """)
        self.conn.commit()
    
    def log_signal(self, signal: Signal, approved: bool, reason: str = "") -> int:
        cur = self.conn.execute("""
            INSERT INTO signals 
            (timestamp, market_id, question, side, p_true, market_price, edge,
             ev_per_share, ev_per_dollar, kelly_quarter, position_size,
             confidence, reasoning, approved, rejection_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.timestamp.isoformat(),
            signal.market.market_id,
            signal.market.question[:200],
            signal.side.value,
            signal.p_true,
            signal.market_price,
            signal.edge,
            signal.ev_per_share,
            signal.ev_per_dollar,
            signal.kelly_quarter,
            signal.position_size_usd,
            signal.confidence,
            signal.reasoning,
            int(approved),
            reason,
        ))
        self.conn.commit()
        return cur.lastrowid
    
    def log_paper_trade(self, signal_id: int, signal: Signal) -> int:
        shares = signal.position_size_usd / signal.market_price
        cur = self.conn.execute("""
            INSERT INTO paper_trades
            (signal_id, timestamp, market_id, question, side, entry_price,
             shares, size_usd, p_true)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id,
            datetime.now(timezone.utc).isoformat(),
            signal.market.market_id,
            signal.market.question[:200],
            signal.side.value,
            signal.market_price,
            shares,
            signal.position_size_usd,
            signal.p_true,
        ))
        self.conn.commit()
        return cur.lastrowid
    
    def get_open_trades(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM paper_trades WHERE closed = 0"
        ).fetchall()
        return [dict(r) for r in rows]
    
    def close_trade(self, trade_id: int, exit_price: float, pnl: float):
        self.conn.execute("""
            UPDATE paper_trades 
            SET closed = 1, exit_price = ?, exit_timestamp = ?, pnl = ?
            WHERE id = ?
        """, (exit_price, datetime.now(timezone.utc).isoformat(), pnl, trade_id))
        self.conn.commit()
    
    def get_stats(self) -> dict:
        """Get overall performance stats."""
        total_trades = self.conn.execute(
            "SELECT COUNT(*) FROM paper_trades"
        ).fetchone()[0]
        
        closed_trades = self.conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE closed = 1"
        ).fetchone()[0]
        
        total_pnl = self.conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM paper_trades WHERE closed = 1"
        ).fetchone()[0]
        
        wins = self.conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE closed = 1 AND pnl > 0"
        ).fetchone()[0]
        
        signals_total = self.conn.execute(
            "SELECT COUNT(*) FROM signals"
        ).fetchone()[0]
        
        signals_approved = self.conn.execute(
            "SELECT COUNT(*) FROM signals WHERE approved = 1"
        ).fetchone()[0]
        
        return {
            "total_signals": signals_total,
            "approved_signals": signals_approved,
            "total_trades": total_trades,
            "closed_trades": closed_trades,
            "total_pnl": total_pnl,
            "win_rate": wins / closed_trades if closed_trades > 0 else 0,
            "open_positions": total_trades - closed_trades,
        }

    # ------------------------------------------------------------------
    # Forecast / Brier Score Tracking
    # ------------------------------------------------------------------

    def log_forecast(self, market_id: str, question: str, p_true: float,
                     market_price: float, side: str, source: str = "crypto"):
        """Record a probability forecast for later Brier score evaluation."""
        # Avoid duplicate forecasts for the same market in the same scan
        existing = self.conn.execute(
            "SELECT id FROM forecasts WHERE market_id = ? AND resolved = 0",
            (market_id,)
        ).fetchone()
        if existing:
            return
        self.conn.execute("""
            INSERT INTO forecasts
            (timestamp, market_id, question, p_true, market_price, side, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            market_id, question[:200], p_true, market_price, side, source,
        ))
        self.conn.commit()

    def resolve_forecast(self, market_id: str, outcome: float):
        """
        Resolve a forecast with the actual outcome.
        outcome: 1.0 = YES resolved, 0.0 = NO resolved.
        """
        self.conn.execute("""
            UPDATE forecasts
            SET resolved = 1, outcome = ?, resolved_timestamp = ?
            WHERE market_id = ? AND resolved = 0
        """, (outcome, datetime.now(timezone.utc).isoformat(), market_id))
        self.conn.commit()

    def get_unresolved_forecasts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM forecasts WHERE resolved = 0"
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_brier_score(self) -> dict:
        """
        Compute Brier score and calibration stats for all resolved forecasts.

        Brier score = mean( (p_true - outcome)^2 )
        Lower is better. 0.0 = perfect, 0.25 = coin-flip baseline.
        """
        rows = self.conn.execute(
            "SELECT p_true, outcome, market_price, side FROM forecasts WHERE resolved = 1"
        ).fetchall()

        if not rows:
            return {"n": 0, "brier_score": None, "baseline_brier": None,
                    "skill_score": None, "calibration": []}

        n = len(rows)
        brier_sum = 0.0
        baseline_sum = 0.0
        # Calibration bins: 0-10%, 10-20%, ..., 90-100%
        bins = {i: {"predicted_sum": 0.0, "outcome_sum": 0.0, "count": 0}
                for i in range(10)}

        for row in rows:
            p = row["p_true"]
            outcome = row["outcome"]
            mkt_p = row["market_price"]

            brier_sum += (p - outcome) ** 2
            baseline_sum += (mkt_p - outcome) ** 2

            bin_idx = min(int(p * 10), 9)
            bins[bin_idx]["predicted_sum"] += p
            bins[bin_idx]["outcome_sum"] += outcome
            bins[bin_idx]["count"] += 1

        brier = brier_sum / n
        baseline = baseline_sum / n
        skill = 1.0 - (brier / baseline) if baseline > 0 else 0.0

        calibration = []
        for i in range(10):
            b = bins[i]
            if b["count"] > 0:
                calibration.append({
                    "bin": f"{i*10}-{(i+1)*10}%",
                    "avg_predicted": b["predicted_sum"] / b["count"],
                    "avg_outcome": b["outcome_sum"] / b["count"],
                    "count": b["count"],
                })

        return {
            "n": n,
            "brier_score": brier,
            "baseline_brier": baseline,
            "skill_score": skill,
            "calibration": calibration,
        }


# ============================================================================
# MODULE 7: PAPER TRADING ENGINE
# ============================================================================

class PaperTrader:
    """Simulates order execution and tracks paper P&L."""
    
    def __init__(self, config: Config, db: TradeDB):
        self.config = config
        self.db = db
        self.bankroll = config.initial_bankroll
        self.positions: list[PaperPosition] = []
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.next_id = 1
        self.log = logging.getLogger("PaperTrader")
    
    def execute(self, signal: Signal, signal_id: int):
        """Paper-execute a trade."""
        shares = signal.position_size_usd / signal.market_price

        pos = PaperPosition(
            id=self.next_id,
            market_id=signal.market.market_id,
            question=signal.market.question,
            side=signal.side,
            entry_price=signal.market_price,
            shares=shares,
            size_usd=signal.position_size_usd,
            p_true=signal.p_true,
            entry_time=datetime.now(timezone.utc),
            yes_token_id=signal.market.yes_token_id,
            no_token_id=signal.market.no_token_id,
        )
        self.positions.append(pos)
        self.next_id += 1
        
        trade_id = self.db.log_paper_trade(signal_id, signal)
        
        self.log.info(
            f"📝 PAPER TRADE #{trade_id}: {signal.side.value} "
            f"{signal.market.question[:50]} | "
            f"{shares:.1f} shares @ ${signal.market_price:.2f} = "
            f"${signal.position_size_usd:.2f} | Edge: {signal.edge:.3f}"
        )
    
    def update_positions(self, fetcher: MarketFetcher):
        """Update unrealized P&L for all open positions."""
        for pos in self.positions:
            if pos.closed:
                continue

            # Use the correct token ID for the side we're holding
            if pos.side == Side.YES:
                token_id = pos.yes_token_id
            else:
                token_id = pos.no_token_id

            if not token_id:
                continue

            new_price = fetcher.fetch_price(token_id)
            if new_price is not None:
                pos.current_price = new_price
                pos.unrealized_pnl = (new_price - pos.entry_price) * pos.shares
    
    def get_open_positions(self) -> list[PaperPosition]:
        return [p for p in self.positions if not p.closed]


# ============================================================================
# MODULE 7B: LIVE TRADER (Phase 3)
# ============================================================================

class LiveTrader:
    """
    Executes real trades on Polymarket using the CLOB API.

    Safety features:
    - Maker-only orders (never cross the spread)
    - Position tracking and reconciliation
    - Order timeout and cancellation
    - Real-time P&L tracking
    """

    def __init__(self, config: Config, db: TradeDB):
        self.config = config
        self.db = db
        self.log = logging.getLogger("LiveTrader")

        if not HAS_CLOB_CLIENT:
            raise ImportError(
                "Live trading requires py-clob-client. Install with: pip install py-clob-client"
            )

        if not config.private_key:
            raise ValueError(
                "Live trading requires POLYMARKET_PRIVATE_KEY environment variable"
            )

        # Initialize CLOB client
        try:
            self.client = ClobClient(
                host=config.clob_api,
                key=config.private_key,
                chain_id=config.chain_id,
                signature_type=config.signature_type,
                funder=config.funder_address if config.funder_address else None,
            )
            self.log.info("✅ CLOB client initialized successfully")

            # Test connection
            self.client.get_tick_size()
            self.log.info("✅ CLOB API connection verified")

        except Exception as e:
            self.log.error(f"Failed to initialize CLOB client: {e}")
            raise

        # Load initial bankroll from config
        self.bankroll = config.initial_bankroll
        self.positions: list[PaperPosition] = []  # Reuse PaperPosition for tracking
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.next_id = 1

        # Order tracking
        self.pending_orders = {}  # order_id -> (signal, timestamp)

        self.log.warning("⚠️  LIVE TRADING MODE ENABLED ⚠️")
        self.log.warning(f"   Bankroll: ${self.bankroll:,.2f}")
        self.log.warning(f"   Chain: Polygon ({config.chain_id})")

    def execute(self, signal: Signal, signal_id: int):
        """
        Execute a real trade on Polymarket.

        Strategy: Place a limit order slightly better than current market price
        to avoid crossing the spread (maker-only strategy).
        """
        try:
            # Determine which token to buy (YES or NO)
            if signal.side == Side.YES:
                token_id = signal.market.yes_token_id
                # Place limit buy slightly below market ask (maker order)
                limit_price = min(signal.market_price - 0.01, signal.market_price * 0.99)
            else:
                token_id = signal.market.no_token_id
                limit_price = min(signal.market_price - 0.01, signal.market_price * 0.99)

            # Ensure price is within valid range [0.01, 0.99]
            limit_price = max(0.01, min(0.99, round(limit_price, 2)))

            # Calculate shares to buy
            size = round(signal.position_size_usd / limit_price, 2)

            self.log.info(
                f"🔴 PLACING LIVE ORDER: {signal.side.value} "
                f"{signal.market.question[:40]}... | "
                f"{size} shares @ ${limit_price:.2f} = ${signal.position_size_usd:.2f}"
            )

            # Create limit order
            order = OrderArgs(
                price=limit_price,
                size=size,
                side=BUY,  # Always buying (YES or NO tokens)
                token_id=token_id,
            )

            # Submit order
            response = self.client.create_order(order)

            if response and "orderID" in response:
                order_id = response["orderID"]
                self.log.info(f"✅ Order placed successfully: {order_id}")

                # Track pending order
                self.pending_orders[order_id] = {
                    "signal": signal,
                    "signal_id": signal_id,
                    "timestamp": datetime.now(timezone.utc),
                    "token_id": token_id,
                    "limit_price": limit_price,
                    "size": size,
                }

                # Log to database
                self.db.log_paper_trade(signal_id, signal)  # Reuse paper trade logging

            else:
                self.log.error(f"Order submission failed: {response}")

        except Exception as e:
            self.log.error(f"Failed to execute trade: {e}", exc_info=True)

    def update_positions(self, fetcher: MarketFetcher):
        """
        Update positions by checking order fills and current prices.
        Also cancels stale orders (older than 5 minutes).
        """
        # Check pending orders
        filled_orders = []
        now = datetime.now(timezone.utc)

        for order_id, order_info in list(self.pending_orders.items()):
            try:
                # Check order status
                order_status = self.client.get_order(order_id)

                if order_status and order_status.get("status") == "MATCHED":
                    # Order filled!
                    signal = order_info["signal"]
                    filled_price = float(order_status.get("price", order_info["limit_price"]))
                    filled_size = float(order_status.get("size", order_info["size"]))

                    self.log.info(
                        f"✅ ORDER FILLED: {order_id[:8]}... | "
                        f"{filled_size:.1f} shares @ ${filled_price:.2f}"
                    )

                    # Create position
                    pos = PaperPosition(
                        id=self.next_id,
                        market_id=signal.market.market_id,
                        question=signal.market.question,
                        side=signal.side,
                        entry_price=filled_price,
                        shares=filled_size,
                        size_usd=filled_price * filled_size,
                        p_true=signal.p_true,
                        entry_time=now,
                        yes_token_id=signal.market.yes_token_id,
                        no_token_id=signal.market.no_token_id,
                    )
                    self.positions.append(pos)
                    self.next_id += 1

                    filled_orders.append(order_id)

                elif order_status and order_status.get("status") in ["CANCELLED", "EXPIRED"]:
                    self.log.warning(f"Order {order_id[:8]}... was cancelled/expired")
                    filled_orders.append(order_id)

                else:
                    # Check if order is stale (older than 5 minutes)
                    order_age = (now - order_info["timestamp"]).total_seconds()
                    if order_age > 300:  # 5 minutes
                        self.log.warning(f"Cancelling stale order {order_id[:8]}... (age: {order_age:.0f}s)")
                        try:
                            self.client.cancel(order_id)
                            filled_orders.append(order_id)
                        except Exception as e:
                            self.log.error(f"Failed to cancel order {order_id}: {e}")

            except Exception as e:
                self.log.error(f"Error checking order {order_id}: {e}")

        # Remove filled/cancelled orders
        for order_id in filled_orders:
            self.pending_orders.pop(order_id, None)

        # Update existing positions with current prices
        for pos in self.positions:
            if pos.closed:
                continue

            # Use the correct token ID for the side we're holding
            if pos.side == Side.YES:
                token_id = pos.yes_token_id
            else:
                token_id = pos.no_token_id

            if not token_id:
                continue

            new_price = fetcher.fetch_price(token_id)
            if new_price is not None:
                pos.current_price = new_price
                pos.unrealized_pnl = (new_price - pos.entry_price) * pos.shares

    def get_open_positions(self) -> list[PaperPosition]:
        """Return all open positions."""
        return [p for p in self.positions if not p.closed]

    def get_total_exposure(self) -> float:
        """Calculate total capital at risk in open positions."""
        return sum(p.size_usd for p in self.positions if not p.closed)


# ============================================================================
# MODULE 8: MAIN BOT
# ============================================================================

class PolymarketBot:
    """
    Main bot that ties everything together.

    Loop: Fetch markets → Estimate probabilities → Scan for edge →
          Risk check → Trade (paper or live) → Log → Sleep → Repeat
    """

    def __init__(self, config: Config):
        self.config = config
        self.fetcher = MarketFetcher(config)
        self.estimator = ProbabilityEstimator(config)
        self.scanner = EdgeScanner(config, self.estimator)
        self.risk_mgr = RiskManager(config)
        self.db = TradeDB(config.db_path)

        # Choose trader mode based on credentials
        if config.private_key and not config.paper_trading:
            self.log = logging.getLogger("PolyBot")
            self.log.warning("=" * 70)
            self.log.warning("🔴 LIVE TRADING MODE ENABLED 🔴")
            self.log.warning("=" * 70)
            self.trader = LiveTrader(config, self.db)
            self.is_live = True
        else:
            self.log = logging.getLogger("PolyBot")
            self.log.info("📝 Paper trading mode (safe mode)")
            self.trader = PaperTrader(config, self.db)
            self.is_live = False

        # Maintain backward compatibility
        self.paper_trader = self.trader
    
    def run_once(self):
        """Run a single scan cycle."""
        self.log.info("=" * 60)
        self.log.info("Starting scan cycle...")
        
        # 1. Fetch markets
        markets = self.fetcher.fetch_all_active_markets()
        if not markets:
            self.log.warning("No markets fetched. Retrying next cycle.")
            return
        
        # 2. Scan for edge
        signals = self.scanner.scan(markets, self.trader.bankroll)

        # 3. Process signals through risk manager
        trades_taken = 0
        for signal in signals:
            # Log forecast for Brier score tracking
            self.db.log_forecast(
                market_id=signal.market.market_id,
                question=signal.market.question,
                p_true=signal.p_true,
                market_price=signal.market_price,
                side=signal.side.value,
                source=(
                    "crypto" if "CryptoModel" in signal.reasoning
                    else "arbitrage" if "arb" in signal.reasoning.lower()
                    else "other"
                ),
            )

            approved, reason = self.risk_mgr.check(
                signal,
                self.trader.positions,
                self.trader.bankroll,
                self.trader.daily_pnl,
            )

            signal_id = self.db.log_signal(signal, approved, reason)

            if approved:
                self.trader.execute(signal, signal_id)
                trades_taken += 1
            else:
                self.log.debug(f"Rejected: {signal.market.question[:40]} — {reason}")

        # 3.5. Update positions (check fills for live trading, prices for paper)
        self.trader.update_positions(self.fetcher)

        # 3.6. Try resolving expired markets
        self.resolve_expired_markets(markets)

        # 4. Summary
        stats = self.db.get_stats()
        open_count = len(self.trader.get_open_positions())

        self.log.info(f"Cycle complete: {len(signals)} signals, {trades_taken} trades taken")
        self.log.info(
            f"Portfolio: ${self.trader.bankroll:,.2f} bankroll | "
            f"{open_count} open positions | "
            f"Total P&L: ${stats['total_pnl']:,.2f} | "
            f"Win rate: {stats['win_rate']:.0%}"
        )
    
    def run_loop(self, cycles: int = 0):
        """
        Run the bot in a continuous loop.
        cycles=0 means run forever.
        """
        self.log.info("=" * 60)
        self.log.info("POLYMARKET PAPER TRADING BOT — STARTING")
        self.log.info(f"Bankroll: ${self.config.initial_bankroll:,.2f}")
        self.log.info(f"Min edge: {self.config.min_edge:.0%}")
        self.log.info(f"Kelly fraction: {self.config.kelly_fraction}")
        self.log.info(f"Scan interval: {self.config.scan_interval_seconds}s")
        self.log.info("=" * 60)
        
        # Health check
        if not self.fetcher.health_check():
            self.log.error("API health check failed. Exiting.")
            return
        
        cycle = 0
        while True:
            try:
                self.run_once()
                cycle += 1
                
                if cycles > 0 and cycle >= cycles:
                    self.log.info(f"Completed {cycles} cycles. Stopping.")
                    break
                
                self.log.info(f"Sleeping {self.config.scan_interval_seconds}s until next scan...")
                time.sleep(self.config.scan_interval_seconds)
                
            except KeyboardInterrupt:
                self.log.info("Interrupted by user. Shutting down.")
                break
            except Exception as e:
                self.log.error(f"Error in scan cycle: {e}", exc_info=True)
                time.sleep(30)  # Back off on errors
    
    def resolve_expired_markets(self, markets: list[Market]):
        """
        Check unresolved forecasts against current market data.
        If a market's end_date has passed or price is near 0/1 (resolved),
        record the outcome for Brier score tracking and close paper trades.
        """
        unresolved = self.db.get_unresolved_forecasts()
        if not unresolved:
            return

        # Build lookup of current market data
        market_map = {m.market_id: m for m in markets}

        resolved_count = 0
        for fc in unresolved:
            mkt = market_map.get(fc["market_id"])
            if mkt is None:
                continue

            # Detect resolution: price near 0 or 1, or past end_date
            is_resolved = False
            outcome = None

            if mkt.yes_price >= 0.95:
                is_resolved = True
                outcome = 1.0  # YES won
            elif mkt.yes_price <= 0.05:
                is_resolved = True
                outcome = 0.0  # NO won
            elif mkt.end_date and datetime.now(timezone.utc) > mkt.end_date + timedelta(hours=2):
                # Market past end date — use current price as proxy
                is_resolved = True
                outcome = 1.0 if mkt.yes_price > 0.5 else 0.0

            if is_resolved and outcome is not None:
                self.db.resolve_forecast(fc["market_id"], outcome)
                resolved_count += 1

                # Also close any paper trades for this market
                open_trades = self.db.get_open_trades()
                for trade in open_trades:
                    if trade["market_id"] == fc["market_id"]:
                        if trade["side"] == "YES":
                            pnl = (outcome - trade["entry_price"]) * trade["shares"]
                        else:
                            pnl = ((1.0 - outcome) - trade["entry_price"]) * trade["shares"]
                        self.db.close_trade(trade["id"], outcome, pnl)
                        self.paper_trader.total_pnl += pnl
                        self.paper_trader.daily_pnl += pnl
                        self.paper_trader.bankroll += pnl
                        self.log.info(
                            f"Resolved: {fc['question'][:50]} -> "
                            f"{'YES' if outcome == 1.0 else 'NO'}, PnL: ${pnl:+.2f}"
                        )

        if resolved_count > 0:
            self.log.info(f"Resolved {resolved_count} forecasts this cycle")

    def print_report(self):
        """Print a summary report of all activity (reads from DB, not memory)."""
        stats = self.db.get_stats()
        open_trades = self.db.get_open_trades()

        print("\n" + "=" * 70)
        print("POLYMARKET BOT — PERFORMANCE REPORT")
        print("=" * 70)
        print(f"  Total Signals:     {stats['total_signals']}")
        print(f"  Approved:          {stats['approved_signals']}")
        print(f"  Trades Taken:      {stats['total_trades']}")
        print(f"  Closed:            {stats['closed_trades']}")
        print(f"  Open:              {stats['open_positions']}")
        print(f"  Total P&L:         ${stats['total_pnl']:,.2f}")
        print(f"  Win Rate:          {stats['win_rate']:.1%}")
        print()

        if open_trades:
            print("  OPEN POSITIONS:")
            print("  " + "-" * 66)
            for t in open_trades:
                print(
                    f"  {t['side']:3s} {t['question'][:45]:45s} | "
                    f"{t['shares']:6.1f} @ ${t['entry_price']:.2f} = ${t['size_usd']:7.2f}"
                )
        print("=" * 70)

    def print_brier_report(self):
        """Print Brier score calibration report."""
        brier = self.db.compute_brier_score()
        unresolved = self.db.get_unresolved_forecasts()

        print("\n" + "=" * 70)
        print("BRIER SCORE — FORECAST CALIBRATION REPORT")
        print("=" * 70)

        print(f"  Unresolved forecasts:  {len(unresolved)}")
        print(f"  Resolved forecasts:    {brier['n']}")

        if brier["n"] == 0:
            print("\n  No resolved forecasts yet. Run scans and wait for markets")
            print("  to resolve, then run: python3 phase1_bot.py --brier")
            print("=" * 70)
            return

        print(f"\n  Your Brier Score:      {brier['brier_score']:.4f}")
        print(f"  Market Baseline:       {brier['baseline_brier']:.4f}")
        print(f"  Skill Score:           {brier['skill_score']:+.4f}")
        print()

        if brier["skill_score"] > 0:
            print("  >>> Your model BEATS the market <<<")
        elif brier["skill_score"] < -0.05:
            print("  >>> Your model is WORSE than the market <<<")
        else:
            print("  >>> Roughly equal to market (no clear edge yet) <<<")

        print(f"\n  CALIBRATION (predicted vs actual):")
        print(f"  {'Bin':>12s} | {'Avg Pred':>9s} | {'Avg Actual':>10s} | {'Count':>5s}")
        print(f"  {'-'*12}-+-{'-'*9}-+-{'-'*10}-+-{'-'*5}")
        for row in brier["calibration"]:
            print(
                f"  {row['bin']:>12s} | {row['avg_predicted']:>9.3f} | "
                f"{row['avg_outcome']:>10.3f} | {row['count']:>5d}"
            )

        if unresolved:
            print(f"\n  PENDING FORECASTS ({len(unresolved)}):")
            print(f"  {'-'*66}")
            for fc in unresolved[:10]:
                print(f"  p={fc['p_true']:.2f}  mkt={fc['market_price']:.2f}  {fc['question'][:50]}")
            if len(unresolved) > 10:
                print(f"  ... and {len(unresolved) - 10} more")

        print("=" * 70)


# ============================================================================
# ============================================================================
# CRYPTO MODEL SMOKE TEST
# ============================================================================

def test_crypto():
    """Smoke test for the CryptoModel with sample questions."""
    setup_logging(logging.DEBUG)
    model = CryptoModel()

    now = datetime.now(timezone.utc)
    d1 = (now + timedelta(days=2)).strftime("%B %d")
    d2 = (now + timedelta(days=7)).strftime("%B %d")

    test_questions = [
        f"Will the price of Bitcoin be above $74,000 on {d1}?",
        f"Will the price of Ethereum be above $2,300 on {d2}?",
        "Will the price of Bitcoin be between $70,000 and $74,000?",
        "Will the price of XRP be less than $0.90?",
        "Will Bitcoin reach $100,000 by end of 2026?",
        f"Will the price of Solana be above $150 on {d1}?",
        "Will Dogecoin be above $0.20?",
        # Non-crypto questions (should return None)
        "Will it rain in Seattle tomorrow?",
        "Will the Fed raise interest rates in April?",
    ]

    print("\n" + "=" * 70)
    print("CRYPTO MODEL SMOKE TEST")
    print("=" * 70)

    for q in test_questions:
        print(f"\nQ: {q}")
        fake_market = Market(
            market_id="test", condition_id="test", question=q,
            category="crypto", yes_token_id="t1", no_token_id="t2",
            yes_price=0.50, no_price=0.50, volume_24h=50000,
            total_volume=500000, liquidity=20000, end_date=None,
            slug="test", active=True,
        )
        try:
            result = model.try_estimate(fake_market)
            if result is None:
                print("   -> Not a crypto market (returned None)")
            else:
                p, conf, reasoning = result
                print(f"   -> p_true={p:.3f}, confidence={conf:.3f}")
                print(f"   -> {reasoning}")
        except Exception as e:
            print(f"   -> ERROR: {e}")

    print("\n" + "=" * 70)
    print("CRYPTO SMOKE TEST COMPLETE")
    print("=" * 70)


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Paper Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SETUP STEPS:
  1. pip install requests websockets
  2. (For live trading) pip install py-clob-client
  3. python phase1_bot.py --scan          # Run one scan cycle (paper trading)
  4. python phase1_bot.py --loop          # Run continuously (paper trading)
  5. python phase1_bot.py --report        # Print performance report

ENVIRONMENT VARIABLES:
  POLYMARKET_PRIVATE_KEY       Your wallet private key (required for live trading)
  POLYMARKET_FUNDER_ADDRESS    Funder address (for proxy wallets, optional)
  POLYMARKET_SIGNATURE_TYPE    0=EOA, 1=email/Magic (default: 0)
  POLYMARKET_BANKROLL          Starting bankroll (default: 10000)

EXAMPLES:
  # Paper trading (safe mode - default)
  python phase1_bot.py --scan
  python phase1_bot.py --loop --interval 120

  # Scan with lower edge threshold (more signals, less quality)
  python phase1_bot.py --scan --min-edge 0.03

  # LIVE TRADING (⚠️  real money at risk!)
  export POLYMARKET_PRIVATE_KEY="0xYourPrivateKeyHere"
  python phase1_bot.py --live --loop --interval 300 --bankroll 500

  # Check performance
  python phase1_bot.py --report
  python phase1_bot.py --brier
        """
    )
    
    parser.add_argument("--scan", action="store_true", help="Run a single scan cycle")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--report", action="store_true", help="Print performance report")
    parser.add_argument("--brier", action="store_true", help="Print Brier score calibration report")
    parser.add_argument("--test-crypto", action="store_true", help="Run crypto model smoke test")
    parser.add_argument("--live", action="store_true", help="⚠️  Enable LIVE trading (requires private key)")
    parser.add_argument("--cycles", type=int, default=0, help="Number of cycles (0=infinite)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between scans")
    parser.add_argument("--min-edge", type=float, default=0.05, help="Minimum edge threshold")
    parser.add_argument("--bankroll", type=float, default=10000, help="Starting bankroll")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--db", type=str,
                        default=os.getenv("POLYBOT_DB_PATH", "polybot_trades.db"),
                        help="Database file path")
    
    args = parser.parse_args()

    # Setup
    setup_logging(logging.DEBUG if args.debug else logging.INFO)

    config = Config.from_env()
    config.scan_interval_seconds = args.interval
    config.min_edge = args.min_edge
    config.initial_bankroll = args.bankroll
    config.db_path = args.db
    config.paper_trading = not args.live  # Disable paper trading if --live flag is set
    
    bot = PolymarketBot(config)
    
    if args.test_crypto:
        test_crypto()
        return

    if args.scan:
        bot.run_once()
        bot.print_report()
    elif args.loop:
        bot.run_loop(cycles=args.cycles)
        bot.print_report()
    elif args.brier:
        bot.print_brier_report()
    elif args.report:
        bot.print_report()
    else:
        parser.print_help()
        print("\n  Quick start: python3 phase1_bot.py --scan")


if __name__ == "__main__":
    main()
