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
# CITY COORDINATES (for weather model geocoding)
# ============================================================================

CITY_COORDINATES = {
    # US Major Cities
    "new york": (40.71, -74.01), "los angeles": (34.05, -118.24),
    "chicago": (41.88, -87.63), "houston": (29.76, -95.37),
    "phoenix": (33.45, -112.07), "philadelphia": (39.95, -75.17),
    "san antonio": (29.42, -98.49), "san diego": (32.72, -117.16),
    "dallas": (32.78, -96.80), "san jose": (37.34, -121.89),
    "austin": (30.27, -97.74), "jacksonville": (30.33, -81.66),
    "fort worth": (32.76, -97.33), "columbus": (39.96, -82.99),
    "charlotte": (35.23, -80.84), "indianapolis": (39.77, -86.16),
    "san francisco": (37.77, -122.42), "seattle": (47.61, -122.33),
    "denver": (39.74, -104.98), "washington": (38.91, -77.04),
    "nashville": (36.16, -86.78), "oklahoma city": (35.47, -97.52),
    "el paso": (31.76, -106.44), "boston": (42.36, -71.06),
    "portland": (45.51, -122.68), "las vegas": (36.17, -115.14),
    "memphis": (35.15, -90.05), "louisville": (38.25, -85.76),
    "baltimore": (39.29, -76.61), "milwaukee": (43.04, -87.91),
    "albuquerque": (35.09, -106.65), "tucson": (32.22, -110.93),
    "fresno": (36.74, -119.77), "mesa": (33.41, -111.83),
    "sacramento": (38.58, -121.49), "atlanta": (33.75, -84.39),
    "kansas city": (39.10, -94.58), "colorado springs": (38.83, -104.82),
    "omaha": (41.26, -95.94), "raleigh": (35.78, -78.64),
    "miami": (25.76, -80.19), "tampa": (27.95, -82.46),
    "minneapolis": (44.98, -93.27), "new orleans": (29.95, -90.07),
    "cleveland": (41.50, -81.69), "pittsburgh": (40.44, -79.99),
    "st. louis": (38.63, -90.20), "detroit": (42.33, -83.05),
    "honolulu": (21.31, -157.86), "anchorage": (61.22, -149.90),
    # International
    "london": (51.51, -0.13), "paris": (48.86, 2.35),
    "tokyo": (35.68, 139.69), "sydney": (-33.87, 151.21),
    "toronto": (43.65, -79.38), "mexico city": (19.43, -99.13),
    "seoul": (37.57, 126.98),
    # Polymarket-specific location names
    "new york's central park": (40.78, -73.97),
    "central park": (40.78, -73.97),
}


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
# SPORTS LEAGUE MAP (keyword → The Odds API sport key)
# ============================================================================

SPORTS_LEAGUE_MAP = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
    "mls": "soccer_usa_mls",
    "premier league": "soccer_epl",
    "epl": "soccer_epl",
    "la liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie a": "soccer_italy_serie_a",
    "ligue 1": "soccer_france_ligue_one",
    "champions league": "soccer_uefa_champs_league",
    "ucl": "soccer_uefa_champs_league",
    "wnba": "basketball_wnba",
    "ncaa": "basketball_ncaab",
    "college basketball": "basketball_ncaab",
    "college football": "americanfootball_ncaaf",
    "ufc": "mma_mixed_martial_arts",
    "mma": "mma_mixed_martial_arts",
}


# ============================================================================
# TEAM ALIASES (common nicknames → full team names for fuzzy matching)
# ============================================================================

TEAM_ALIASES = {
    # NBA
    "cavs": "cleveland cavaliers", "cavaliers": "cleveland cavaliers",
    "celtics": "boston celtics", "lakers": "los angeles lakers",
    "warriors": "golden state warriors", "dubs": "golden state warriors",
    "knicks": "new york knicks", "nets": "brooklyn nets",
    "sixers": "philadelphia 76ers", "76ers": "philadelphia 76ers",
    "heat": "miami heat", "bucks": "milwaukee bucks",
    "nuggets": "denver nuggets", "suns": "phoenix suns",
    "thunder": "oklahoma city thunder", "okc": "oklahoma city thunder",
    "mavs": "dallas mavericks", "mavericks": "dallas mavericks",
    "rockets": "houston rockets", "spurs": "san antonio spurs",
    "timberwolves": "minnesota timberwolves", "wolves": "minnesota timberwolves",
    "grizzlies": "memphis grizzlies", "pelicans": "new orleans pelicans",
    "hawks": "atlanta hawks", "bulls": "chicago bulls",
    "pacers": "indiana pacers", "magic": "orlando magic",
    "raptors": "toronto raptors", "wizards": "washington wizards",
    "hornets": "charlotte hornets", "pistons": "detroit pistons",
    "kings": "sacramento kings", "blazers": "portland trail blazers",
    "trail blazers": "portland trail blazers", "jazz": "utah jazz",
    "clippers": "los angeles clippers",
    # NFL
    "chiefs": "kansas city chiefs", "eagles": "philadelphia eagles",
    "bills": "buffalo bills", "ravens": "baltimore ravens",
    "bengals": "cincinnati bengals", "cowboys": "dallas cowboys",
    "niners": "san francisco 49ers", "49ers": "san francisco 49ers",
    "lions": "detroit lions", "dolphins": "miami dolphins",
    "steelers": "pittsburgh steelers", "packers": "green bay packers",
    "chargers": "los angeles chargers", "broncos": "denver broncos",
    "vikings": "minnesota vikings", "seahawks": "seattle seahawks",
    "jaguars": "jacksonville jaguars", "jags": "jacksonville jaguars",
    "commanders": "washington commanders", "texans": "houston texans",
    "bears": "chicago bears", "giants": "new york giants",
    "jets": "new york jets", "colts": "indianapolis colts",
    "browns": "cleveland browns", "raiders": "las vegas raiders",
    "saints": "new orleans saints", "falcons": "atlanta falcons",
    "panthers": "carolina panthers", "bucs": "tampa bay buccaneers",
    "buccaneers": "tampa bay buccaneers", "titans": "tennessee titans",
    "patriots": "new england patriots", "pats": "new england patriots",
    "rams": "los angeles rams", "cardinals": "arizona cardinals",
    # MLB
    "yankees": "new york yankees", "dodgers": "los angeles dodgers",
    "red sox": "boston red sox", "mets": "new york mets",
    "astros": "houston astros", "braves": "atlanta braves",
    "phillies": "philadelphia phillies", "padres": "san diego padres",
    "cubs": "chicago cubs", "white sox": "chicago white sox",
    "guardians": "cleveland guardians", "twins": "minnesota twins",
    "mariners": "seattle mariners", "orioles": "baltimore orioles",
    "blue jays": "toronto blue jays",
    # NHL
    "bruins": "boston bruins", "maple leafs": "toronto maple leafs",
    "canadiens": "montreal canadiens", "habs": "montreal canadiens",
    "rangers": "new york rangers", "penguins": "pittsburgh penguins",
    "blackhawks": "chicago blackhawks", "red wings": "detroit red wings",
    "avalanche": "colorado avalanche", "oilers": "edmonton oilers",
    "flames": "calgary flames", "canucks": "vancouver canucks",
    "lightning": "tampa bay lightning", "panthers (nhl)": "florida panthers",
    "hurricanes": "carolina hurricanes", "wild": "minnesota wild",
    "predators": "nashville predators", "blues": "st. louis blues",
    "sharks": "san jose sharks", "kraken": "seattle kraken",
    "golden knights": "vegas golden knights",
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
# MODULE 2.5: WEATHER PROBABILITY MODEL
# ============================================================================

@dataclass
class WeatherQuery:
    """Parsed weather question data."""
    query_type: str            # "temp_bucket", "temp_threshold", "precip"
    city: str
    target_date: datetime
    metric: str                # "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"
    bucket_low: Optional[float] = None   # For bucket queries: e.g. 70
    bucket_high: Optional[float] = None  # For bucket queries: e.g. 80
    threshold: Optional[float] = None    # For threshold/precip queries
    direction: str = "above"   # "above" or "below"
    unit: str = "fahrenheit"


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


@dataclass
class SportsQuery:
    """Parsed sports question data."""
    sport_key: str              # The Odds API sport key, e.g. "basketball_nba"
    team_or_player: str         # team/player name to look up
    event_type: str             # "championship", "game_winner", "award"
    opponent: Optional[str] = None
    league: str = ""            # human readable league name


class WeatherModel:
    """
    Uses Open-Meteo GFS Ensemble API (31 members, free, no key) to compute
    probabilities for Polymarket weather markets.
    """

    ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
    CACHE_TTL = 600  # 10 minutes

    def __init__(self):
        self.log = logging.getLogger("WeatherModel")
        self._cache: dict[str, tuple[float, list]] = {}  # key -> (timestamp, data)

    def try_estimate(self, market: Market) -> Optional[tuple[float, float, str]]:
        """
        Main entry: parse question -> geocode -> fetch ensemble -> compute prob.
        Returns (p_true, confidence, reasoning) or None if not a weather market.
        """
        query = self._parse_weather_question(market.question)
        if query is None:
            return None

        coords = self._get_coordinates(query.city)
        if coords is None:
            self.log.debug(f"WeatherModel: unknown city '{query.city}'")
            return None

        lat, lon = coords
        now = datetime.now(timezone.utc)
        days_ahead = (query.target_date - now).days

        if days_ahead < 0:
            self.log.debug("WeatherModel: target date is in the past")
            return None
        if days_ahead > 16:
            self.log.debug("WeatherModel: target date >16 days out, skipping")
            return None

        if query.query_type == "temp_bucket":
            members = self._fetch_temperature_forecast(lat, lon, query.target_date, query.metric)
            if members is None or len(members) == 0:
                return None
            p = self._compute_temp_bucket_probability(members, query.bucket_low, query.bucket_high)
        elif query.query_type == "temp_threshold":
            members = self._fetch_temperature_forecast(lat, lon, query.target_date, query.metric)
            if members is None or len(members) == 0:
                return None
            p = self._compute_temp_threshold_probability(members, query.threshold, query.direction)
        elif query.query_type == "precip":
            member_totals = self._fetch_precipitation_forecast(lat, lon, query.target_date, query.target_date)
            if member_totals is None or len(member_totals) == 0:
                return None
            p = self._compute_precip_probability(member_totals, query.threshold)
        else:
            return None

        # Clamp to [0.02, 0.98]
        p = max(0.02, min(0.98, p))
        confidence = self._compute_confidence(
            members if query.query_type != "precip" else member_totals,
            days_ahead, p
        )

        reasoning = (
            f"WeatherModel: {query.query_type} for {query.city} on "
            f"{query.target_date.strftime('%Y-%m-%d')}, "
            f"{len(members) if query.query_type != 'precip' else len(member_totals)} "
            f"ensemble members, p={p:.3f}, days_ahead={days_ahead}"
        )
        self.log.info(reasoning)
        return (p, confidence, reasoning)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_weather_question(self, question: str) -> Optional[WeatherQuery]:
        """Regex patterns to detect weather markets and extract parameters."""
        q = question.lower().strip()

        # ---- Polymarket actual format ----
        # "Will the high temperature in New York's Central Park be 60 degrees F or higher on November 2, 2021?"
        # "Will the highest temperature in Seoul be between 50°F and 59°F on March 17?"
        m = re.search(
            r'(?:will\s+the\s+)?(?:high(?:est)?|max)\s+temp(?:erature)?\s+in\s+(.+?)\s+'
            r'(?:be\s+)?([-\d.]+)\s*(?:degrees?\s*f?|°\s*f)\s*(?:or\s+)?'
            r'(higher|lower|or\s+higher|or\s+lower|above|below)\s+'
            r'(?:on\s+)?(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            city = m.group(1).strip().rstrip("'s")
            threshold = float(m.group(2))
            direction_word = m.group(3)
            date_str = m.group(4)
            direction = "above" if "higher" in direction_word or "above" in direction_word else "below"
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_threshold", city, target_date,
                                    "temperature_2m_max", threshold=threshold, direction=direction)

        # "Will the highest temperature in CITY be between X°F and Y°F on DATE?"
        m = re.search(
            r'(?:will\s+the\s+)?(?:high(?:est)?|max)\s+temp(?:erature)?\s+in\s+(.+?)\s+'
            r'(?:be\s+)?(?:between|from)\s+([-\d.]+)\s*(?:°\s*f?|degrees?\s*f?)?\s*'
            r'(?:and|to|-)\s*([-\d.]+)\s*(?:°\s*f?|degrees?\s*f?)?\s+'
            r'(?:on\s+)?(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            city = m.group(1).strip().rstrip("'s")
            low, high = float(m.group(2)), float(m.group(3))
            date_str = m.group(4)
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_bucket", city, target_date,
                                    "temperature_2m_max", bucket_low=low, bucket_high=high)

        # --- High temp bucket: "Will the high temperature in Chicago on March 20 be between 40°F and 50°F?" ---
        m = re.search(
            r'(?:high|max)\s+temp(?:erature)?\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)\s+'
            r'(?:be\s+)?(?:between|from)\s+([-\d.]+)\s*°?\s*[fF]?\s*(?:and|to|-)\s*([-\d.]+)',
            q
        )
        if m:
            city, date_str, low, high = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_bucket", city.strip(), target_date,
                                    "temperature_2m_max", bucket_low=low, bucket_high=high)

        # Low temp bucket
        m = re.search(
            r'(?:low(?:est)?|min(?:imum)?)\s+temp(?:erature)?\s+in\s+(.+?)\s+'
            r'(?:be\s+)?(?:between|from)\s+([-\d.]+)\s*(?:°\s*f?|degrees?\s*f?)?\s*'
            r'(?:and|to|-)\s*([-\d.]+)\s*(?:°\s*f?|degrees?\s*f?)?\s+'
            r'(?:on\s+)?(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            city = m.group(1).strip().rstrip("'s")
            low, high = float(m.group(2)), float(m.group(3))
            date_str = m.group(4)
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_bucket", city, target_date,
                                    "temperature_2m_min", bucket_low=low, bucket_high=high)

        m = re.search(
            r'(?:low|min(?:imum)?)\s+temp(?:erature)?\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)\s+'
            r'(?:be\s+)?(?:between|from)\s+([-\d.]+)\s*°?\s*[fF]?\s*(?:and|to|-)\s*([-\d.]+)',
            q
        )
        if m:
            city, date_str, low, high = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_bucket", city.strip(), target_date,
                                    "temperature_2m_min", bucket_low=low, bucket_high=high)

        # Generic temp bucket: "temperature in X on DATE between A and B"
        m = re.search(
            r'temp(?:erature)?\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)\s+'
            r'(?:be\s+)?(?:between|from)\s+([-\d.]+)\s*°?\s*[fF]?\s*(?:and|to|-)\s*([-\d.]+)',
            q
        )
        if m:
            city, date_str, low, high = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_bucket", city.strip(), target_date,
                                    "temperature_2m_max", bucket_low=low, bucket_high=high)

        # --- Temperature threshold: "high temp in CITY on DATE above/below X" ---
        m = re.search(
            r'(?:high|max)\s+temp(?:erature)?\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)\s+'
            r'(?:be\s+|reach\s+|exceed\s+|go\s+)?'
            r'(above|below|over|under|at least|at most|exceed)\s*([-\d.]+)',
            q
        )
        if m:
            city = m.group(1).strip()
            date_str = m.group(2)
            direction_word = m.group(3)
            threshold = float(m.group(4))
            direction = "above" if direction_word in ("above", "over", "at least", "exceed") else "below"
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_threshold", city, target_date,
                                    "temperature_2m_max", threshold=threshold, direction=direction)

        m = re.search(
            r'(?:low|min(?:imum)?)\s+temp(?:erature)?\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)\s+'
            r'(?:be\s+|reach\s+|drop\s+)?'
            r'(above|below|over|under|at least|at most)\s*([-\d.]+)',
            q
        )
        if m:
            city = m.group(1).strip()
            date_str = m.group(2)
            direction_word = m.group(3)
            threshold = float(m.group(4))
            direction = "above" if direction_word in ("above", "over", "at least") else "below"
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_threshold", city, target_date,
                                    "temperature_2m_min", threshold=threshold, direction=direction)

        # Generic threshold: "Will it be above X°F in CITY on DATE?"
        m = re.search(
            r'(?:will\s+it\s+be|will\s+the\s+temperature\s+be)\s+'
            r'(above|below|over|under)\s*([-\d.]+)\s*°?\s*[fF]?\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            direction_word = m.group(1)
            threshold = float(m.group(2))
            city = m.group(3).strip()
            date_str = m.group(4)
            direction = "above" if direction_word in ("above", "over") else "below"
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("temp_threshold", city, target_date,
                                    "temperature_2m_max", threshold=threshold, direction=direction)

        # --- Precipitation: "more than X inches of rain/precipitation" ---
        m = re.search(
            r'(?:more\s+than|over|at\s+least|exceed)\s+([-\d.]+)\s*(?:inches?|in\.?|mm)\s+'
            r'(?:of\s+)?(?:rain|precipitation|precip|snow)\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            threshold = float(m.group(1))
            city = m.group(2).strip()
            date_str = m.group(3)
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("precip", city, target_date,
                                    "precipitation_sum", threshold=threshold)

        # "Will it rain/snow in CITY on DATE?"
        m = re.search(
            r'will\s+it\s+(?:rain|snow|precipitat)\w*\s+in\s+(.+?)\s+on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            city = m.group(1).strip()
            date_str = m.group(2)
            target_date = self._parse_date(date_str)
            if target_date:
                return WeatherQuery("precip", city, target_date,
                                    "precipitation_sum", threshold=0.01)

        # "Will it be sunny in CITY at noon on DATE?"
        m = re.search(
            r'will\s+it\s+be\s+sunny\s+in\s+(.+?)\s+(?:at\s+\w+\s+)?on\s+'
            r'(\w+\s+\d{1,2}(?:[\s,]+\d{4})?)',
            q
        )
        if m:
            city = m.group(1).strip()
            date_str = m.group(2)
            target_date = self._parse_date(date_str)
            if target_date:
                # Sunny = no precipitation — threshold 0.01 inch, invert
                return WeatherQuery("precip", city, target_date,
                                    "precipitation_sum", threshold=0.01)

        return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date strings like 'March 20', 'March 20, 2026', 'Mar 20'."""
        date_str = date_str.strip().rstrip(",")
        now = datetime.now(timezone.utc)
        formats = [
            "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
            "%B %d", "%b %d",
        ]
        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                if "%Y" not in fmt:
                    parsed = parsed.replace(year=now.year)
                    # If date already passed this year, assume next year
                    if parsed.replace(tzinfo=timezone.utc) < now - timedelta(days=1):
                        parsed = parsed.replace(year=now.year + 1)
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------

    def _get_coordinates(self, city: str) -> Optional[tuple[float, float]]:
        """Lookup city in CITY_COORDINATES with substring matching."""
        city_lower = city.lower().strip()
        # Exact match first
        if city_lower in CITY_COORDINATES:
            return CITY_COORDINATES[city_lower]
        # Substring match
        for name, coords in CITY_COORDINATES.items():
            if name in city_lower or city_lower in name:
                return coords
        return None

    # ------------------------------------------------------------------
    # API Fetching
    # ------------------------------------------------------------------

    def _cache_key(self, lat: float, lon: float, date: datetime, variable: str) -> str:
        return f"{lat:.2f},{lon:.2f},{date.strftime('%Y-%m-%d')},{variable}"

    def _get_cached(self, key: str) -> Optional[list]:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self.CACHE_TTL:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: list):
        self._cache[key] = (time.time(), data)

    def _fetch_temperature_forecast(self, lat: float, lon: float,
                                     date: datetime, metric: str) -> Optional[list[float]]:
        """Fetch ensemble temperature forecast. Returns list of 31 member values."""
        cache_key = self._cache_key(lat, lon, date, metric)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        date_str = date.strftime("%Y-%m-%d")
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "daily": metric,
                "temperature_unit": "fahrenheit",
                "start_date": date_str,
                "end_date": date_str,
                "models": "gfs_seamless",
            }
            r = requests.get(self.ENSEMBLE_URL, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            daily = data.get("daily", {})
            # Ensemble members come as metric_member01, metric_member02, ... metric_member31
            # or as a single list depending on API response format
            members = []
            # Try individual member keys
            for i in range(1, 32):
                key = f"{metric}_member{i:02d}"
                if key in daily and daily[key]:
                    members.append(float(daily[key][0]))

            # If no individual members, the API may return them differently
            if not members and metric in daily and isinstance(daily[metric], list):
                members = [float(v) for v in daily[metric] if v is not None]

            if members:
                self._set_cache(cache_key, members)
                self.log.debug(f"Fetched {len(members)} temp members for {lat},{lon} on {date_str}")
                return members

            self.log.debug(f"No ensemble members found in response for {metric}")
            return None

        except Exception as e:
            self.log.debug(f"Weather API error (temp): {e}")
            return None

    def _fetch_precipitation_forecast(self, lat: float, lon: float,
                                       start: datetime, end: datetime) -> Optional[list[float]]:
        """Fetch ensemble precipitation forecast. Returns list of member daily totals."""
        cache_key = self._cache_key(lat, lon, start, "precipitation_sum")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "daily": "precipitation_sum",
                "precipitation_unit": "inch",
                "start_date": start_str,
                "end_date": end_str,
                "models": "gfs_seamless",
            }
            r = requests.get(self.ENSEMBLE_URL, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            daily = data.get("daily", {})
            members = []
            for i in range(1, 32):
                key = f"precipitation_sum_member{i:02d}"
                if key in daily and daily[key]:
                    members.append(float(daily[key][0]))

            if not members and "precipitation_sum" in daily:
                val = daily["precipitation_sum"]
                if isinstance(val, list):
                    members = [float(v) for v in val if v is not None]

            if members:
                self._set_cache(cache_key, members)
                self.log.debug(f"Fetched {len(members)} precip members for {lat},{lon}")
                return members

            return None

        except Exception as e:
            self.log.debug(f"Weather API error (precip): {e}")
            return None

    # ------------------------------------------------------------------
    # Probability Computation
    # ------------------------------------------------------------------

    def _compute_temp_bucket_probability(self, members: list[float],
                                          low: float, high: float) -> float:
        """
        Fraction of ensemble members in [low, high].
        Applies Gaussian kernel smoothing to avoid jagged probabilities.
        """
        n = len(members)
        if n == 0:
            return 0.5

        # Simple count
        count = sum(1 for v in members if low <= v <= high)
        raw_p = count / n

        # Gaussian kernel smoothing: each member contributes a soft vote
        # Bandwidth = max(2.0, std/3) to smooth over forecast uncertainty
        mean_val = sum(members) / n
        variance = sum((v - mean_val) ** 2 for v in members) / n
        std = math.sqrt(variance) if variance > 0 else 2.0
        bandwidth = max(2.0, std / 3.0)

        smooth_count = 0.0
        for v in members:
            # Probability that a Gaussian centered at v falls in [low, high]
            p_low = 0.5 * (1 + math.erf((v - low) / (bandwidth * math.sqrt(2))))
            p_high = 0.5 * (1 + math.erf((v - high) / (bandwidth * math.sqrt(2))))
            smooth_count += (p_low - p_high)

        smooth_p = smooth_count / n

        # Blend raw and smoothed (weight raw more when ensemble agrees)
        agreement = 1.0 - (std / 20.0)  # Higher agreement when std is low
        agreement = max(0.2, min(0.8, agreement))
        blended = agreement * raw_p + (1 - agreement) * smooth_p

        return max(0.0, min(1.0, blended))

    def _compute_temp_threshold_probability(self, members: list[float],
                                             threshold: float, direction: str) -> float:
        """Fraction of ensemble members above/below threshold with smoothing."""
        n = len(members)
        if n == 0:
            return 0.5

        mean_val = sum(members) / n
        variance = sum((v - mean_val) ** 2 for v in members) / n
        std = math.sqrt(variance) if variance > 0 else 2.0
        bandwidth = max(1.5, std / 3.0)

        smooth_count = 0.0
        for v in members:
            # Probability that Gaussian centered at v is above/below threshold
            z = (threshold - v) / (bandwidth * math.sqrt(2))
            p_below = 0.5 * (1 + math.erf(z))
            if direction == "above":
                smooth_count += (1.0 - p_below)
            else:
                smooth_count += p_below

        return max(0.0, min(1.0, smooth_count / n))

    def _compute_precip_probability(self, member_totals: list[float],
                                     threshold: float) -> float:
        """Fraction of ensemble members exceeding precipitation threshold."""
        n = len(member_totals)
        if n == 0:
            return 0.5
        count = sum(1 for v in member_totals if v >= threshold)
        return count / n

    def _compute_confidence(self, members: list[float], days_ahead: int,
                            p: float) -> float:
        """
        Confidence score based on:
        - Forecast horizon (exponential decay)
        - Ensemble agreement (lower spread = higher confidence)
        - Sample quality (more members = higher confidence)
        """
        # Horizon decay: confidence halves every 5 days
        horizon_factor = math.exp(-0.14 * days_ahead)

        # Ensemble agreement: how tightly clustered are the members?
        n = len(members)
        if n > 1:
            mean_val = sum(members) / n
            variance = sum((v - mean_val) ** 2 for v in members) / n
            std = math.sqrt(variance)
            # Lower spread = higher agreement; normalize by typical temp spread ~10°F
            agreement_factor = max(0.3, 1.0 - std / 15.0)
        else:
            agreement_factor = 0.3

        # Sample quality: 31 members is full, less is worse
        sample_factor = min(1.0, n / 20.0)

        # Probability extremeness penalty: very certain forecasts get slight confidence boost
        # but middling forecasts (near 0.5) are less useful
        extremeness = abs(p - 0.5) * 2  # 0 at p=0.5, 1 at p=0 or p=1
        extremeness_factor = 0.7 + 0.3 * extremeness

        confidence = horizon_factor * agreement_factor * sample_factor * extremeness_factor
        return max(0.1, min(0.95, confidence))


# ============================================================================
# MODULE 2.6: CRYPTO PROBABILITY MODEL (Black-Scholes on Binance/Deribit data)
# ============================================================================

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
        self._cache: dict[str, tuple[float, any]] = {}

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
        if query.target_date:
            now = datetime.now(timezone.utc)
            dt = (query.target_date - now).total_seconds()
            if dt <= 0:
                return None
            T = dt / (365.25 * 24 * 3600)
        else:
            # No date specified — default to 30 days
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


# ============================================================================
# MODULE 2.7: SPORTS PROBABILITY MODEL (The Odds API bookmaker consensus)
# ============================================================================

class SportsModel:
    """
    Uses The Odds API to fetch bookmaker odds, de-vigs them,
    and computes consensus probabilities for sports markets.

    Gracefully returns None if no ODDS_API_KEY is set.
    """

    ODDS_API_BASE = "https://api.the-odds-api.com/v4"
    CACHE_TTL = 1800  # 30 minutes
    REQUEST_BUDGET = 450  # leave headroom under 500/month free tier

    def __init__(self):
        self.log = logging.getLogger("SportsModel")
        self.api_key = os.getenv("ODDS_API_KEY", "")
        self._cache: dict[str, tuple[float, any]] = {}
        self._request_count = 0

    def try_estimate(self, market: Market) -> Optional[tuple[float, float, str]]:
        """
        Main entry: parse question → fetch odds → de-vig → consensus prob.
        Returns (p_true, confidence, reasoning) or None.
        """
        if not self.api_key:
            return None

        query = self._parse_sports_question(market.question)
        if query is None:
            return None

        if self._request_count >= self.REQUEST_BUDGET:
            self.log.warning("SportsModel: request budget exhausted, skipping")
            return None

        # Fetch odds for this sport
        odds_data = self._fetch_odds(query.sport_key)
        if not odds_data:
            return None

        # Find the relevant event/team
        result = self._find_team_odds(odds_data, query)
        if result is None:
            return None

        prob, n_books, event_name = result
        prob = max(0.02, min(0.98, prob))

        confidence = self._compute_confidence(n_books, query.event_type)

        reasoning = (
            f"SportsModel: {query.league.upper()} {query.event_type} — "
            f"{query.team_or_player} in '{event_name}', "
            f"consensus p={prob:.3f} from {n_books} bookmakers"
        )
        self.log.info(reasoning)
        return (prob, confidence, reasoning)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_sports_question(self, question: str) -> Optional[SportsQuery]:
        """Detect sports markets and extract parameters."""
        q = question.lower().strip()

        # Detect league
        detected_league = None
        sport_key = None
        for kw, skey in SPORTS_LEAGUE_MAP.items():
            if kw in q:
                detected_league = kw
                sport_key = skey
                break

        # If no league keyword found, try to detect from team names
        if sport_key is None:
            resolved = self._resolve_team(q)
            if resolved is None:
                return None
            team_name, detected_league, sport_key = resolved
        else:
            team_name = None

        # Determine event type
        event_type = "game_winner"  # default

        championship_words = [
            "win the", "champion", "finals", "world series",
            "super bowl", "stanley cup", "title",
        ]
        award_words = ["mvp", "rookie of the year", "dpoy", "defensive player"]

        for w in championship_words:
            if w in q:
                event_type = "championship"
                break
        for w in award_words:
            if w in q:
                event_type = "award"
                break

        # "TEAM vs TEAM" or "TEAM - Winner"
        if " vs " in q or " vs. " in q or " v " in q:
            event_type = "game_winner"

        # Extract team/player name
        if team_name is None:
            team_name = self._extract_team_from_question(q)
            if team_name is None:
                return None

        # Extract opponent if head-to-head
        opponent = None
        m = re.search(r'(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)(?:\s*[-–—]\s*|\s*\?)', q)
        if m:
            t1 = m.group(1).strip()
            t2 = m.group(2).strip()
            # Determine which is our team
            t1_resolved = self._resolve_single_team(t1)
            t2_resolved = self._resolve_single_team(t2)
            if t1_resolved:
                team_name = t1_resolved
                opponent = t2_resolved or t2
            elif t2_resolved:
                team_name = t2_resolved
                opponent = t1_resolved or t1

        return SportsQuery(
            sport_key=sport_key,
            team_or_player=team_name,
            event_type=event_type,
            opponent=opponent,
            league=detected_league or "",
        )

    def _resolve_team(self, text: str) -> Optional[tuple[str, str, str]]:
        """Try to find a team alias in text and return (full_name, league, sport_key)."""
        for alias, full_name in TEAM_ALIASES.items():
            if re.search(r'\b' + re.escape(alias) + r'\b', text):
                # Guess the league from the full team name
                league, sport_key = self._guess_league(full_name)
                if sport_key:
                    return (full_name, league, sport_key)
        return None

    def _resolve_single_team(self, name: str) -> Optional[str]:
        """Resolve a single team name/alias to full name."""
        name_l = name.lower().strip()
        if name_l in TEAM_ALIASES:
            return TEAM_ALIASES[name_l]
        # Check if name_l is a substring of any alias
        for alias, full_name in TEAM_ALIASES.items():
            if alias in name_l or name_l in full_name:
                return full_name
        return None

    def _guess_league(self, team_name: str) -> tuple[str, str]:
        """Guess league from a full team name by checking known teams."""
        # NBA teams
        nba_cities = [
            "celtics", "nets", "knicks", "76ers", "raptors", "bulls",
            "cavaliers", "pistons", "pacers", "bucks", "hawks", "hornets",
            "heat", "magic", "wizards", "nuggets", "timberwolves",
            "thunder", "trail blazers", "jazz", "warriors", "clippers",
            "lakers", "suns", "kings", "mavericks", "rockets", "grizzlies",
            "pelicans", "spurs",
        ]
        nfl_teams = [
            "chiefs", "eagles", "bills", "ravens", "bengals", "cowboys",
            "49ers", "lions", "dolphins", "steelers", "packers", "chargers",
            "broncos", "vikings", "seahawks", "jaguars", "commanders",
            "texans", "bears", "giants", "jets", "colts", "browns",
            "raiders", "saints", "falcons", "panthers", "buccaneers",
            "titans", "patriots", "rams", "cardinals",
        ]
        for t in nba_cities:
            if t in team_name:
                return ("nba", "basketball_nba")
        for t in nfl_teams:
            if t in team_name:
                return ("nfl", "americanfootball_nfl")
        return ("", "")

    def _extract_team_from_question(self, q: str) -> Optional[str]:
        """Try to extract a team name from the question text."""
        # Check all aliases
        for alias, full_name in TEAM_ALIASES.items():
            if re.search(r'\b' + re.escape(alias) + r'\b', q):
                return full_name
        # Check for full team names directly
        for full_name in set(TEAM_ALIASES.values()):
            if full_name in q:
                return full_name
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

    def _fetch_odds(self, sport_key: str) -> Optional[list]:
        """Fetch odds from The Odds API for a sport."""
        cache_key = f"odds_{sport_key}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            r = requests.get(
                f"{self.ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey": self.api_key,
                    "regions": "us,eu",
                    "markets": "h2h,outrights",
                    "oddsFormat": "american",
                },
                timeout=15,
            )
            self._request_count += 1

            if r.status_code == 401:
                self.log.warning("SportsModel: invalid API key")
                return None
            if r.status_code == 429:
                self.log.warning("SportsModel: rate limited")
                return None

            r.raise_for_status()
            data = r.json()

            # Track remaining requests from headers
            remaining = r.headers.get("x-requests-remaining")
            if remaining:
                self.log.debug(f"Odds API requests remaining: {remaining}")

            self._set_cache(cache_key, data)
            return data

        except Exception as e:
            self.log.debug(f"Odds API error for {sport_key}: {e}")
            return None

    # ------------------------------------------------------------------
    # Odds Processing
    # ------------------------------------------------------------------

    def _find_team_odds(self, events: list, query: SportsQuery
                        ) -> Optional[tuple[float, int, str]]:
        """
        Find the team in the odds data and compute consensus probability.
        Returns (probability, n_bookmakers, event_name) or None.
        """
        team = query.team_or_player.lower()

        for event in events:
            home = (event.get("home_team") or "").lower()
            away = (event.get("away_team") or "").lower()
            event_name = f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}"

            # Check if our team is in this event
            team_found = False
            our_team_name = None
            if self._team_matches(team, home):
                team_found = True
                our_team_name = event.get("home_team", "")
            elif self._team_matches(team, away):
                team_found = True
                our_team_name = event.get("away_team", "")

            if not team_found:
                continue

            # Collect implied probabilities from all bookmakers
            probs = []
            bookmakers = event.get("bookmakers", [])
            for bookie in bookmakers:
                for mkt in bookie.get("markets", []):
                    if mkt.get("key") not in ("h2h", "outrights"):
                        continue
                    outcomes = mkt.get("outcomes", [])
                    # De-vig this bookmaker's line
                    devigged = self._devig_outcomes(outcomes, our_team_name)
                    if devigged is not None:
                        probs.append(devigged)

            if not probs:
                continue

            # Consensus: average across bookmakers
            consensus = sum(probs) / len(probs)
            return (consensus, len(probs), event_name)

        # Also check outrights (championship/MVP markets)
        if query.event_type in ("championship", "award"):
            return self._find_outright_odds(events, team, query)

        return None

    def _find_outright_odds(self, events: list, team: str,
                            query: SportsQuery) -> Optional[tuple[float, int, str]]:
        """Search outright/futures markets for the team."""
        for event in events:
            bookmakers = event.get("bookmakers", [])
            for bookie in bookmakers:
                for mkt in bookie.get("markets", []):
                    if mkt.get("key") != "outrights":
                        continue
                    outcomes = mkt.get("outcomes", [])
                    for outcome in outcomes:
                        name = (outcome.get("name") or "").lower()
                        if self._team_matches(team, name):
                            # Found it — collect from all bookmakers
                            return self._collect_outright_probs(
                                events, team,
                                event.get("sport_title", query.league),
                            )
        return None

    def _collect_outright_probs(self, events: list, team: str,
                                event_name: str) -> Optional[tuple[float, int, str]]:
        """Collect outright probabilities from all bookmakers."""
        probs = []
        for event in events:
            for bookie in event.get("bookmakers", []):
                for mkt in bookie.get("markets", []):
                    if mkt.get("key") != "outrights":
                        continue
                    outcomes = mkt.get("outcomes", [])
                    devigged = self._devig_outright(outcomes, team)
                    if devigged is not None:
                        probs.append(devigged)

        if not probs:
            return None

        consensus = sum(probs) / len(probs)
        return (consensus, len(probs), event_name)

    def _team_matches(self, query_team: str, candidate: str) -> bool:
        """Fuzzy match team names."""
        if not query_team or not candidate:
            return False
        qt = query_team.lower()
        ct = candidate.lower()
        if qt == ct:
            return True
        # Check if one contains the other
        if qt in ct or ct in qt:
            return True
        # Check last word (team nickname)
        qt_parts = qt.split()
        ct_parts = ct.split()
        if qt_parts and ct_parts and qt_parts[-1] == ct_parts[-1]:
            return True
        return False

    @staticmethod
    def _american_to_prob(odds: float) -> float:
        """Convert American odds to implied probability."""
        if odds > 0:
            return 100.0 / (odds + 100.0)
        else:
            return abs(odds) / (abs(odds) + 100.0)

    def _devig_outcomes(self, outcomes: list, our_team: str) -> Optional[float]:
        """
        De-vig a set of H2H outcomes and return the fair probability for our team.
        Multiplicative de-vig: divide each implied prob by the sum of all implied probs.
        """
        implied = {}
        for o in outcomes:
            name = o.get("name", "")
            price = o.get("price")
            if price is None:
                continue
            implied[name.lower()] = self._american_to_prob(float(price))

        if not implied:
            return None

        total = sum(implied.values())
        if total <= 0:
            return None

        # Find our team
        our_key = None
        for name in implied:
            if self._team_matches(our_team.lower(), name):
                our_key = name
                break

        if our_key is None:
            return None

        return implied[our_key] / total

    def _devig_outright(self, outcomes: list, team: str) -> Optional[float]:
        """De-vig an outright market for a specific team."""
        implied = {}
        for o in outcomes:
            name = o.get("name", "")
            price = o.get("price")
            if price is None:
                continue
            implied[name.lower()] = self._american_to_prob(float(price))

        if not implied:
            return None

        total = sum(implied.values())
        if total <= 0:
            return None

        for name, prob in implied.items():
            if self._team_matches(team, name):
                return prob / total

        return None

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _compute_confidence(self, n_bookmakers: int, event_type: str) -> float:
        """
        Confidence based on number of bookmakers and event type.
        More bookmakers = more reliable consensus.
        H2H > championship > award (decreasing reliability).
        """
        # Bookmaker count factor
        book_factor = min(1.0, 0.4 + 0.1 * n_bookmakers)

        # Event type factor
        type_factors = {
            "game_winner": 0.85,
            "championship": 0.70,
            "award": 0.55,
        }
        type_factor = type_factors.get(event_type, 0.60)

        confidence = book_factor * type_factor
        return max(0.20, min(0.90, confidence))


# ============================================================================
# MODULE 3: PROBABILITY ESTIMATOR (Placeholder — you build your edge here)
# ============================================================================

class ProbabilityEstimator:
    """
    THIS IS WHERE YOUR EDGE LIVES.
    
    The default implementation uses a simple "contrarian fade" strategy:
    - Markets near 50/50 are skipped (no informational edge)
    - Markets with extreme prices (>85¢ or <15¢) are checked for
      overconfidence/underconfidence using base rates
    
    You should replace this with your own models:
    - Weather: NOAA API probabilities
    - Crypto: Implied vol from Binance/Deribit options
    - Politics: Polling aggregation with Bayesian shrinkage
    - Economics: Fed funds futures implied probabilities
    
    The key insight: your p_true must be BETTER than the market's.
    If you can't articulate WHY you have an edge, you don't have one.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.weather_model = WeatherModel()
        self.crypto_model = CryptoModel()
        self.sports_model = SportsModel()
        self.log = logging.getLogger("ProbEstimator")

    def estimate(self, market: Market) -> Optional[tuple[float, float, str]]:
        """
        Estimate true probability for a market.

        Returns: (p_true, confidence, reasoning) or None if no edge.

        Pipeline order:
        1. Weather (ensemble forecast)
        2. Crypto (Black-Scholes on Binance/Deribit data)
        3. Sports (bookmaker consensus via The Odds API)
        4. Arbitrage (structural mispricing)
        """

        # Strategy 0: Weather model (ensemble forecast)
        try:
            weather_result = self.weather_model.try_estimate(market)
            if weather_result is not None:
                return weather_result
        except Exception:
            pass

        # Strategy 1: Crypto model (Black-Scholes)
        try:
            crypto_result = self.crypto_model.try_estimate(market)
            if crypto_result is not None:
                return crypto_result
        except Exception:
            pass

        # Strategy 2: Sports model (bookmaker consensus)
        try:
            sports_result = self.sports_model.try_estimate(market)
            if sports_result is not None:
                return sports_result
        except Exception:
            pass

        # Strategy 3: Arbitrage check — YES + NO should = 1.00
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
                     market_price: float, side: str, source: str = "weather"):
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
# MODULE 8: MAIN BOT
# ============================================================================

class PolymarketBot:
    """
    Main bot that ties everything together.
    
    Loop: Fetch markets → Estimate probabilities → Scan for edge → 
          Risk check → Paper trade → Log → Sleep → Repeat
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.fetcher = MarketFetcher(config)
        self.estimator = ProbabilityEstimator(config)
        self.scanner = EdgeScanner(config, self.estimator)
        self.risk_mgr = RiskManager(config)
        self.db = TradeDB(config.db_path)
        self.paper_trader = PaperTrader(config, self.db)
        self.log = logging.getLogger("PolyBot")
    
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
        signals = self.scanner.scan(markets, self.paper_trader.bankroll)
        
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
                    "weather" if "WeatherModel" in signal.reasoning
                    else "crypto" if "CryptoModel" in signal.reasoning
                    else "sports" if "SportsModel" in signal.reasoning
                    else "heuristic"
                ),
            )

            approved, reason = self.risk_mgr.check(
                signal,
                self.paper_trader.positions,
                self.paper_trader.bankroll,
                self.paper_trader.daily_pnl,
            )

            signal_id = self.db.log_signal(signal, approved, reason)

            if approved:
                self.paper_trader.execute(signal, signal_id)
                trades_taken += 1
            else:
                self.log.debug(f"Rejected: {signal.market.question[:40]} — {reason}")

        # 3.5. Try resolving expired markets
        self.resolve_expired_markets(markets)

        # 4. Summary
        stats = self.db.get_stats()
        open_count = len(self.paper_trader.get_open_positions())
        
        self.log.info(f"Cycle complete: {len(signals)} signals, {trades_taken} trades taken")
        self.log.info(
            f"Portfolio: ${self.paper_trader.bankroll:,.2f} bankroll | "
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
# WEATHER MODEL SMOKE TEST
# ============================================================================

def test_weather():
    """Smoke test for the WeatherModel with sample questions."""
    setup_logging(logging.DEBUG)
    model = WeatherModel()

    # Generate dates a few days from now for realistic testing
    now = datetime.now(timezone.utc)
    d1 = (now + timedelta(days=2)).strftime("%B %d")
    d2 = (now + timedelta(days=3)).strftime("%B %d")
    d3 = (now + timedelta(days=5)).strftime("%B %d")

    test_questions = [
        # Temperature bucket questions
        f"Will the high temperature in Chicago on {d1} be between 40°F and 60°F?",
        f"Will the high temperature in New York on {d2} be between 50°F and 70°F?",
        f"Will the low temperature in Miami on {d1} be between 60°F and 75°F?",
        # Temperature threshold questions
        f"Will the high temperature in Phoenix on {d3} be above 90°F?",
        f"Will the high temperature in Denver on {d2} be below 50°F?",
        f"Will it be above 80°F in Houston on {d1}?",
        # Precipitation questions
        f"Will there be more than 0.1 inches of rain in Seattle on {d2}?",
        f"Will it rain in Los Angeles on {d3}?",
        # Non-weather questions (should return None)
        "Will Bitcoin reach $100,000 by end of 2026?",
        "Will the Fed raise interest rates in April?",
        "Who will win the 2026 World Series?",
    ]

    print("\n" + "=" * 70)
    print("WEATHER MODEL SMOKE TEST")
    print("=" * 70)

    for q in test_questions:
        print(f"\nQ: {q}")
        fake_market = Market(
            market_id="test", condition_id="test", question=q,
            category="weather", yes_token_id="t1", no_token_id="t2",
            yes_price=0.50, no_price=0.50, volume_24h=10000,
            total_volume=100000, liquidity=5000, end_date=None,
            slug="test", active=True,
        )
        try:
            result = model.try_estimate(fake_market)
            if result is None:
                print("   -> Not a weather market (returned None)")
            else:
                p, conf, reasoning = result
                print(f"   -> p_true={p:.3f}, confidence={conf:.3f}")
                print(f"   -> {reasoning}")
        except Exception as e:
            print(f"   -> ERROR: {e}")

    print("\n" + "=" * 70)
    print("SMOKE TEST COMPLETE")
    print("=" * 70)


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
# SPORTS MODEL SMOKE TEST
# ============================================================================

def test_sports():
    """Smoke test for the SportsModel with sample questions."""
    setup_logging(logging.DEBUG)
    model = SportsModel()

    if not model.api_key:
        print("\n" + "=" * 70)
        print("SPORTS MODEL SMOKE TEST")
        print("=" * 70)
        print("\n  ODDS_API_KEY not set — skipping sports model test.")
        print("  Get a free key at: https://the-odds-api.com/")
        print("  Then: export ODDS_API_KEY='your-key-here'")
        print("\n" + "=" * 70)
        return

    test_questions = [
        "Will the Cleveland Cavaliers win the 2026 NBA Finals?",
        "Will Devin Booker win the 2025-2026 NBA MVP?",
        "Will the Kansas City Chiefs win Super Bowl LXI?",
        "Will the New York Yankees win the 2026 World Series?",
        # Non-sports questions (should return None)
        "Will Bitcoin reach $100,000?",
        "Will it rain in Seattle?",
    ]

    print("\n" + "=" * 70)
    print("SPORTS MODEL SMOKE TEST")
    print("=" * 70)

    for q in test_questions:
        print(f"\nQ: {q}")
        fake_market = Market(
            market_id="test", condition_id="test", question=q,
            category="sports", yes_token_id="t1", no_token_id="t2",
            yes_price=0.50, no_price=0.50, volume_24h=50000,
            total_volume=500000, liquidity=20000, end_date=None,
            slug="test", active=True,
        )
        try:
            result = model.try_estimate(fake_market)
            if result is None:
                print("   -> Not a sports market or no odds found (returned None)")
            else:
                p, conf, reasoning = result
                print(f"   -> p_true={p:.3f}, confidence={conf:.3f}")
                print(f"   -> {reasoning}")
        except Exception as e:
            print(f"   -> ERROR: {e}")

    print("\n" + "=" * 70)
    print("SPORTS SMOKE TEST COMPLETE")
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
  2. (Optional for live trading later) pip install py-clob-client
  3. python phase1_bot.py --scan          # Run one scan cycle
  4. python phase1_bot.py --loop          # Run continuously
  5. python phase1_bot.py --report        # Print performance report

ENVIRONMENT VARIABLES:
  POLYMARKET_PRIVATE_KEY       Your wallet private key (live trading only)
  POLYMARKET_FUNDER_ADDRESS    Funder address (for proxy wallets)
  POLYMARKET_SIGNATURE_TYPE    0=EOA, 1=email/Magic
  POLYMARKET_BANKROLL          Starting bankroll (default: 10000)
  ODDS_API_KEY                 The Odds API key for sports model (free at the-odds-api.com)

EXAMPLES:
  # Quick test — fetch markets and scan for opportunities
  python phase1_bot.py --scan

  # Run continuously, scanning every 2 minutes  
  python phase1_bot.py --loop --interval 120

  # Scan with lower edge threshold (more signals, less quality)
  python phase1_bot.py --scan --min-edge 0.03
        """
    )
    
    parser.add_argument("--scan", action="store_true", help="Run a single scan cycle")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--report", action="store_true", help="Print performance report")
    parser.add_argument("--brier", action="store_true", help="Print Brier score calibration report")
    parser.add_argument("--test-weather", action="store_true", help="Run weather model smoke test")
    parser.add_argument("--test-crypto", action="store_true", help="Run crypto model smoke test")
    parser.add_argument("--test-sports", action="store_true", help="Run sports model smoke test")
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
    
    bot = PolymarketBot(config)
    
    if args.test_weather:
        test_weather()
        return
    if args.test_crypto:
        test_crypto()
        return
    if args.test_sports:
        test_sports()
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
