# Migration Guide: SpreadManager → SubscriptionHelper + TradingPairs

**Date:** 2025-11-20
**Status:** ⚠️ SpreadManager is deprecated

## Overview

The arbitrage architecture has been refactored to leverage LEAN's native TradingPair infrastructure, eliminating ~750 lines of redundant Python code and providing better performance through event-driven design.

## What Changed

### Architecture Changes

| Component | OLD | NEW |
|-----------|-----|-----|
| **Subscription** | `SpreadManager.subscribe_trading_pair()` | `SubscriptionHelper.subscribe_pair()` |
| **Pair Registration** | Manual observer pattern | `TradingPairs.CollectionChanged` event |
| **Spread Calculation** | Python `calculate_spread_pct()` | C# `TradingPair.Update()` (automatic) |
| **Spread Access** | `spread_manager.on_data()` + observers | `self.TradingPairs` in OnData |
| **State Management** | Python dicts (`pair_mappings`) | `algorithm.TradingPairs` collection |

### Key Improvements

1. ✅ **Unified Subscription Logic** - Single `_subscribe_leg()` method handles all security types
2. ✅ **Event-Driven** - LEAN standard `CollectionChanged` event for initialization
3. ✅ **Direct Access** - Access `TradingPairs` directly from `Slice` in OnData
4. ✅ **No Manual Updates** - `TradingPairManager.UpdateAll()` called automatically by AlgorithmManager
5. ✅ **Less Code** - 900 lines → 160 lines

## Migration Steps

### Step 1: Update Imports

**OLD:**
```python
from spread_manager import SpreadManager
```

**NEW:**
```python
from subscription_helper import SubscriptionHelper
from System.Collections.Specialized import NotifyCollectionChangedAction
from dataclasses import dataclass
from typing import Tuple, Optional
```

### Step 2: Replace SpreadManager with SubscriptionHelper

**OLD:**
```python
def initialize(self):
    # Create SpreadManager
    self.spread_manager = SpreadManager(algorithm=self)

    # Register observers
    self.spread_manager.register_pair_observer(monitor.write_pair_mapping)
    self.spread_manager.register_observer(monitor.write_spread)
    self.spread_manager.register_observer(self.strategy.on_spread_update)

    # Subscribe pairs
    futures_sec, spot_sec = self.spread_manager.subscribe_trading_pair(
        pair_symbol=(futures_symbol, spot_symbol),
        extended_market_hours=False
    )

    # Initialize strategy
    self.strategy.initialize_pair((futures_sec.Symbol, spot_sec.Symbol))
```

**NEW:**
```python
def initialize(self):
    # Create SubscriptionHelper
    self.subscription_helper = SubscriptionHelper(algorithm=self)

    # Subscribe to TradingPairs collection event
    self.TradingPairs.CollectionChanged += self._on_trading_pairs_changed

    # Subscribe pairs (triggers CollectionChanged event)
    futures_sec, spot_sec = self.subscription_helper.subscribe_pair(
        leg1_symbol=futures_symbol,
        leg2_symbol=spot_symbol,
        pair_type="spot_future"  # REQUIRED parameter
    )
    # Note: Strategy initialization moved to event handler

def _on_trading_pairs_changed(self, sender, e):
    """Handle TradingPair collection changes"""
    if e.Action == NotifyCollectionChangedAction.Add:
        for pair in e.NewItems:
            # Initialize monitor
            if self.strategy.monitoring_context:
                monitor = self.strategy.monitoring_context.get_spread_monitor()
                if monitor:
                    monitor.write_pair_mapping(
                        pair.Leg1Security,
                        pair.Leg2Security
                    )

            # Initialize strategy
            self.strategy.initialize_pair(
                (pair.Leg1Symbol, pair.Leg2Symbol)
            )
```

### Step 3: Update OnData Method

**OLD:**
```python
def on_data(self, data: Slice):
    self.strategy.on_data(data)

    # Manual spread calculation and observer notification
    self.spread_manager.on_data(data)
```

**NEW:**
```python
def on_data(self, data: Slice):
    """
    TradingPairManager.UpdateAll() is automatically called by AlgorithmManager
    Access spread data directly from self.TradingPairs
    """
    self.strategy.on_data(data)

    # Access TradingPairs directly from algorithm
    if hasattr(self, 'TradingPairs') and self.TradingPairs is not None:
        for pair in self.TradingPairs:
            if pair.HasValidPrices:
                # Monitoring
                if self.strategy.monitoring_context:
                    monitor = self.strategy.monitoring_context.get_spread_monitor()
                    if monitor:
                        monitor.write_spread(
                            self._adapt_to_spread_signal(pair)
                        )

                # Strategy notification (only for arbitrage opportunities)
                if pair.ExecutableSpread is not None:
                    self.strategy.on_spread_update(
                        self._adapt_to_spread_signal(pair)
                    )

def _adapt_to_spread_signal(self, trading_pair):
    """Temporary adapter for backward compatibility"""
    @dataclass
    class SpreadSignal:
        pair_symbol: Tuple[Symbol, Symbol]
        market_state: MarketState
        theoretical_spread: float
        executable_spread: Optional[float]
        direction: Optional[str]

    return SpreadSignal(
        pair_symbol=(trading_pair.Leg1Symbol, trading_pair.Leg2Symbol),
        market_state=trading_pair.MarketState,
        theoretical_spread=float(trading_pair.TheoreticalSpread),
        executable_spread=float(trading_pair.ExecutableSpread) if trading_pair.ExecutableSpread else None,
        direction=trading_pair.Direction
    )
```

### Step 4: SubscriptionHelper API Changes

**Key Differences:**

1. **Explicit pair_type** - Must specify `pair_type` parameter (no auto-detection)
2. **No auto-flip** - Returns securities in the order you pass them
3. **Named parameters** - Use `leg1_symbol`, `leg2_symbol` instead of `pair_symbol` tuple

**OLD:**
```python
self.spread_manager.subscribe_trading_pair(
    pair_symbol=(symbol1, symbol2),  # Tuple
    extended_market_hours=False
)
```

**NEW:**
```python
self.subscription_helper.subscribe_pair(
    leg1_symbol=symbol1,           # Explicit parameter
    leg2_symbol=symbol2,           # Explicit parameter
    pair_type="spot_future",       # REQUIRED - explicit type
    extended_market_hours=False
)
```

## API Reference

### SubscriptionHelper.subscribe_pair()

```python
def subscribe_pair(
    leg1_symbol: Symbol,
    leg2_symbol: Symbol,
    pair_type: str,  # REQUIRED: "spot_future", "crypto_stock", "cryptofuture_stock"
    resolution: Tuple[Resolution, Resolution] = (Resolution.TICK, Resolution.TICK),
    fee_model: Tuple = None,
    leverage: Tuple[float, float] = (5.0, 5.0),
    extended_market_hours: bool = False
) -> Tuple[Security, Security]
```

**Parameters:**
- `leg1_symbol`: First leg Symbol
- `leg2_symbol`: Second leg Symbol
- `pair_type`: **REQUIRED** - Pair type string
- `resolution`: Tuple of resolutions for (leg1, leg2)
- `fee_model`: Tuple of fee models or None
- `leverage`: Tuple of leverage values
- `extended_market_hours`: For Equity only

**Returns:** `(leg1_security, leg2_security)` in the order passed

### TradingPair Properties (C#)

Access these properties directly from `algorithm.TradingPairs`:

```python
pair = self.TradingPairs[(leg1_symbol, leg2_symbol)]

# Price properties
pair.Leg1BidPrice
pair.Leg1AskPrice
pair.Leg2BidPrice
pair.Leg2AskPrice

# Spread properties
pair.TheoreticalSpread      # Continuous spread for monitoring
pair.ExecutableSpread       # Non-null only when arbitrage opportunity exists
pair.ShortSpread           # Spread for short direction
pair.LongSpread            # Spread for long direction

# State properties
pair.MarketState           # Crossed, LimitOpportunity, NoOpportunity, Unknown
pair.Direction             # "SHORT_SPREAD", "LONG_SPREAD", or "none"
pair.HasValidPrices        # Data validity check

# Metadata
pair.Key                   # String representation (e.g., "BTCUSDT-BTCUSDT")
pair.PairType             # "spot_future", "crypto_stock", etc.
```

## Examples

### Example 1: Spot-Future Arbitrage

See `arbitrage/spot_future_arbitrage.py` for the complete migrated example.

### Example 2: Crypto-Stock Arbitrage

**OLD:**
```python
crypto_sec, stock_sec = self.spread_manager.subscribe_trading_pair(
    pair_symbol=(crypto_symbol, stock_symbol),
    extended_market_hours=True
)
```

**NEW:**
```python
crypto_sec, stock_sec = self.subscription_helper.subscribe_pair(
    leg1_symbol=crypto_symbol,
    leg2_symbol=stock_symbol,
    pair_type="crypto_stock",
    extended_market_hours=True
)
```

## Breaking Changes

### 1. No Auto-Detection of Pair Type
**OLD:** Automatically detected based on SecurityType
**NEW:** Must explicitly specify `pair_type` parameter

### 2. No Auto-Flip for Spot-Future
**OLD:** Automatically flipped to ensure (spot, future) order
**NEW:** Returns securities in the order you pass them

### 3. No Observer Pattern
**OLD:** `register_observer()` / `register_pair_observer()`
**NEW:** Subscribe to `TradingPairs.CollectionChanged` event

### 4. No Manual spread_manager.on_data() Call
**OLD:** Must call `spread_manager.on_data(data)` in OnData
**NEW:** Spread updates automatic, access via `self.TradingPairs`

## Testing Strategy

1. **Keep spread_manager.py** - Marked as deprecated but functional
2. **Migrate main algorithms** - Update production algorithms first
3. **Update tests gradually** - Migrate integration tests as needed
4. **Validate behavior** - Ensure numerical results match
5. **Delete spread_manager** - Once all code migrated and validated

## Rollback Plan

If issues arise, simply:
1. Revert imports back to `from spread_manager import SpreadManager`
2. Restore SpreadManager initialization and observer registration
3. Restore manual `spread_manager.on_data()` call

The deprecated `spread_manager.py` remains functional for backward compatibility.

## Questions?

See the reference implementation in `arbitrage/spot_future_arbitrage.py` or contact the development team.
