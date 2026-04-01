# Live Trading Setup Guide

⚠️ **WARNING**: Live trading involves real money and real risk. Only proceed if you understand prediction markets and are prepared to lose your entire bankroll.

---

## Prerequisites

Before enabling live trading, you **MUST** have:

1. ✅ **4+ weeks of paper trading data** showing consistent positive results
2. ✅ **Brier score showing your model beats the market** (`--brier` report)
3. ✅ **Win rate above 50%** and positive total P&L in paper trading
4. ✅ **Understanding of Polymarket** - how markets resolve, fees, liquidity
5. ✅ **A Polymarket account** with USDC on Polygon network

---

## Step 1: Install Live Trading Dependencies

```bash
cd /home/dias/polymarket-bot
pip install py-clob-client
```

Verify installation:
```bash
python3 -c "from py_clob_client.client import ClobClient; print('✅ CLOB client installed')"
```

---

## Step 2: Get Your Polymarket Private Key

### Method A: Export from Polymarket Website (Recommended)

1. Go to https://polymarket.com
2. Log in to your account
3. Click your profile → **Settings**
4. Navigate to **Export Private Key**
5. Complete authentication (Magic Link or email)
6. Copy the private key (starts with `0x`)

⚠️ **CRITICAL**:
- NEVER share this key with anyone
- NEVER commit it to git
- NEVER paste it in plain text files
- Store it securely (password manager recommended)

### Method B: Export from MetaMask (if you control the wallet)

1. Open MetaMask
2. Click the 3 dots → **Account Details**
3. Click **Show Private Key**
4. Enter your MetaMask password
5. Copy the private key

---

## Step 3: Fund Your Wallet

Your Polymarket wallet needs USDC on Polygon network:

1. **Bridge USDC to Polygon**:
   - Use https://wallet.polygon.technology/
   - Or transfer directly from an exchange (Coinbase, Binance) that supports Polygon

2. **Recommended starting bankroll**: $100 - $500
   - Start small to validate live trading performance
   - Scale up only after 2-4 weeks of profitable live trading

3. **Gas fees**: Keep a small amount of MATIC (~$5) for transaction fees

---

## Step 4: Set Environment Variables

**Option A: Docker (recommended for your NAS setup)**

Edit your `docker-compose.yml`:

```yaml
services:
  polybot:
    build: .
    container_name: polymarket-bot
    restart: unless-stopped
    volumes:
      - polybot-data:/data
    environment:
      # Live trading credentials
      - POLYMARKET_PRIVATE_KEY=0xYourPrivateKeyHere
      - POLYMARKET_BANKROLL=500
      # Optional - only if using proxy wallet
      - POLYMARKET_FUNDER_ADDRESS=
      - POLYMARKET_SIGNATURE_TYPE=0
      # Sports model (optional)
      - ODDS_API_KEY=
    command: ["--live", "--loop", "--interval", "300", "--min-edge", "0.04", "--db", "/data/polybot_trades.db"]
```

**Option B: Local environment**

```bash
export POLYMARKET_PRIVATE_KEY="0xYourPrivateKeyHere"
export POLYMARKET_BANKROLL="500"
```

---

## Step 5: Test the Connection (Dry Run)

Before placing real orders, test the connection:

```bash
# This will initialize the CLOB client but won't place orders (paper trading mode)
python3 phase1_bot.py --scan --bankroll 500
```

You should see:
```
📝 Paper trading mode (safe mode)
```

---

## Step 6: Enable Live Trading

### ⚠️ FINAL SAFETY CHECK ⚠️

Before you proceed, confirm:

- [ ] My paper trading Brier score is **better than baseline**
- [ ] My paper trading win rate is **above 50%**
- [ ] My paper trading total P&L is **positive** over 4+ weeks
- [ ] I'm starting with a **small bankroll** I can afford to lose
- [ ] I've **tested the connection** successfully
- [ ] My private key is stored **securely**
- [ ] I understand that **maker orders may not fill** immediately
- [ ] I understand **markets can resolve unexpectedly**

### Start Live Trading

**Docker deployment:**
```bash
cd /home/dias/polymarket-bot
docker-compose down
docker-compose up -d
docker logs -f polymarket-bot
```

You should see:
```
======================================================================
🔴 LIVE TRADING MODE ENABLED 🔴
======================================================================
⚠️  LIVE TRADING MODE ENABLED ⚠️
   Bankroll: $500.00
   Chain: Polygon (137)
✅ CLOB client initialized successfully
✅ CLOB API connection verified
```

**Local deployment:**
```bash
export POLYMARKET_PRIVATE_KEY="0xYourKey"
python3 phase1_bot.py --live --loop --interval 300 --bankroll 500 --min-edge 0.04 --db /data/polybot_trades.db
```

---

## Step 7: Monitor Your Bot

### Watch the logs
```bash
docker logs -f polymarket-bot
```

Look for:
- `🔴 PLACING LIVE ORDER:` - Order submitted
- `✅ Order placed successfully:` - Order accepted by exchange
- `✅ ORDER FILLED:` - Order executed

### Check performance daily
```bash
docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db
```

### Monitor Brier score weekly
```bash
docker exec polymarket-bot python3 phase1_bot.py --brier --db /data/polybot_trades.db
```

---

## Understanding Live Trading Behavior

### Order Execution Strategy

The bot uses a **maker-only** strategy:
- Places limit orders slightly **below** market price
- Waits for fills (doesn't cross the spread)
- Cancels stale orders after 5 minutes
- Never takes liquidity (no market orders)

**Why maker-only?**
- Avoids overpaying due to spread
- Gets better prices
- May result in missed trades if market moves away

### What to Expect

**First 24 hours:**
- Fewer trades than paper trading (orders must fill)
- Some orders may not fill
- Monitor closely

**First week:**
- Compare live P&L to paper trading expectations
- Expect 10-20% lower fill rate
- Adjust `min_edge` if needed

**First month:**
- Validate that Brier score remains good
- Check that win rate stays above 50%
- If profitable, consider increasing bankroll by 20-50%

---

## Safety Features Built Into LiveTrader

1. **Maker-only orders** - Never crosses spread
2. **Position limits** - Respects Kelly sizing and risk limits
3. **Stale order cancellation** - Auto-cancels after 5 minutes
4. **Order tracking** - Monitors fills in real-time
5. **Database logging** - All trades logged for analysis

---

## Troubleshooting

### "Live trading requires py-clob-client"
```bash
pip install py-clob-client
```

### "Live trading requires POLYMARKET_PRIVATE_KEY"
```bash
export POLYMARKET_PRIVATE_KEY="0xYourKey"
```

### "Order submission failed"
- Check wallet has USDC balance
- Check wallet has MATIC for gas
- Check Polygon network is not congested
- Check order size is reasonable (>$1, <$10,000)

### "No orders filling"
- This is normal - maker orders wait for fills
- Market may be moving against you
- Consider slightly higher limit prices (but reduces edge)
- Be patient - orders can take 1-5 minutes to fill

### "Performance worse than paper trading"
Expected differences:
- **Fill rate**: 70-90% (vs 100% in paper)
- **Prices**: Slightly better (maker rebate)
- **Execution time**: 1-5 minutes (vs instant)

If performance is **significantly worse**:
- Check Brier score is still good
- Verify markets are liquid (>$10k volume)
- Increase `min_edge` threshold
- Reduce `scan_interval` for fresher prices

---

## Scaling Up Safely

**Month 1**: $100-500 bankroll
**Month 2**: $500-1000 (if positive P&L and good Brier)
**Month 3**: $1000-2000 (if consistent profitability)
**Month 6+**: Scale linearly with proven track record

**Never exceed**:
- 5% of your total liquid net worth
- Money you can't afford to lose
- Your risk tolerance

---

## When to Stop

**Immediately stop live trading if:**
- Daily drawdown exceeds -10%
- Brier score turns negative (worse than market)
- Win rate drops below 45% for 2+ weeks
- You feel emotional about trades
- Market conditions change significantly

**How to stop:**
```bash
docker-compose down
```

Or remove the `--live` flag and restart in paper mode.

---

## Next Steps After Live Trading

1. **Week 1**: Monitor closely, validate fills
2. **Week 2-4**: Compare to paper trading, adjust if needed
3. **Month 2**: If profitable, scale up 20-50%
4. **Month 3+**: Consider:
   - Building better probability models (weather, crypto, sports)
   - Adding more data sources
   - Implementing position closing strategies
   - Setting up alerts (Telegram, Discord)

---

## Support

- **Code issues**: Open issue on GitHub
- **Polymarket questions**: https://docs.polymarket.com
- **Trading questions**: Research prediction market strategies

---

## Disclaimer

This software is provided "as is" without warranty. Trading prediction markets involves substantial risk of loss. Past performance (even in paper trading) does not guarantee future results. Only trade with money you can afford to lose. The authors are not responsible for any financial losses.

**Remember**: Most traders lose money. Trade responsibly.
