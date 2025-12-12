# region imports
from AlgorithmImports import *
from QuantConnect.Algorithm import AQCAlgorithm
from QuantConnect.Algorithm.Framework.Alphas import ArbitrageAlphaModel
from QuantConnect.Algorithm.Framework.Portfolio import ArbitragePortfolioConstructionModel
from QuantConnect.Algorithm.Framework.Execution import ArbitrageExecutionModel, MatchingStrategy
from QuantConnect.Configuration import Config

import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import GateSymbolManager
# endregion


class Arbitrage(AQCAlgorithm):
    """
    Multi-Account Arbitrage Algorithm with Framework Integration

    - Data Source: Gate tokenized stock futures + USA stocks
    - Accounts:
      * Gate Account: Trades crypto (Market.Gate) - Margin mode with auto-leverage
      * IBKR Account: Trades stocks (Market.USA) - Margin mode with auto-leverage
    - Framework: ArbitrageAlphaModel + ArbitragePortfolioConstructionModel + ArbitrageExecutionModel
    - Pair Type: crypto_stock only (auto-configures grid levels)
    """

    def initialize(self):
        """Initialize algorithm with framework integration"""

        # === 1. Basic setup ===
        self.set_start_date(2025, 1, 1)
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # Read configuration
        extended_raw = Config.Get("extended-market-hours", "false")
        self.extended_market_hours = extended_raw.lower() == "true" if isinstance(extended_raw, str) else bool(extended_raw)

        self.debug("=" * 60)
        self.debug("INITIALIZING ARBITRAGE ALGORITHM (Framework)")
        self.debug("=" * 60)

        # === 2. Initialize data source ===
        self.debug("📊 Initializing data sources...")
        self.sources = {
            "gate": GateSymbolManager()
        }

        # === 3. FRAMEWORK SETUP - CRITICAL ORDER ===
        self.debug("CONFIGURING FRAMEWORK")
        self.debug("=" * 60)

        # Step 3a: Create and set Alpha model FIRST (before AddPair)
        alpha = ArbitrageAlphaModel(
            insightPeriod=timedelta(minutes=5),
            confidence=1.0,
            requireValidPrices=True
        )
        self.SetAlpha(alpha)
        self.debug("✅ ArbitrageAlphaModel configured")
        self.debug("  Auto-configuration enabled for crypto_stock pairs")
        self.debug("  Grid template: LONG_SPREAD (-2%/+1%, 50%) + SHORT_SPREAD (+3%/-0.5%, 50%)")

        # Step 3b: Subscribe trading pairs
        self._subscribe_trading_pairs()

        # Step 3c: Portfolio Construction
        pcm = ArbitragePortfolioConstructionModel()
        self.SetArbitragePortfolioConstruction(pcm)
        self.debug("✅ ArbitragePortfolioConstructionModel configured")

        # Step 3d: Execution
        execution = ArbitrageExecutionModel(
            asynchronous=True,
            preferredStrategy=MatchingStrategy.AutoDetect
        )
        self.SetArbitrageExecution(execution)
        self.debug("✅ ArbitrageExecutionModel configured (Async, AutoDetect)")

        self.debug("=" * 60)
        self.debug("✅ INITIALIZATION COMPLETE")
        self.debug(f"Trading Pairs: {self.TradingPairs.Count}")
        self.debug(f"Securities: {len(self.Securities)}")
        self.debug("=" * 60)

    def _subscribe_trading_pairs(self):
        """Subscribe crypto_stock pairs using framework"""

        for exchange, manager in self.sources.items():
            try:
                # Get tokenized stock pairs with liquidity filtering
                trade_pairs = manager.get_tokenized_stock_pairs(
                    asset_type='future',
                    min_volume_usdt=300000
                )
                self.debug(f"Found {len(trade_pairs)} liquid futures pairs from {exchange}")

                # Register symbol properties at runtime
                registered_count = manager.register_symbol_properties_runtime(self, trade_pairs)
                self.debug(f"Registered {registered_count} symbols to LEAN runtime")

                # Subscribe each pair
                for crypto_symbol, equity_symbol in trade_pairs:
                    try:
                        # Use correct Add method based on SecurityType
                        if crypto_symbol.SecurityType == SecurityType.Crypto:
                            crypto_sec = self.AddCrypto(
                                crypto_symbol.Value,
                                Resolution.ORDERBOOK,
                                Market.Gate
                            )
                            pair_type = "crypto_stock"
                        elif crypto_symbol.SecurityType == SecurityType.CryptoFuture:
                            crypto_sec = self.AddCryptoFuture(
                                crypto_symbol.Value,
                                Resolution.ORDERBOOK,
                                Market.Gate
                            )
                            pair_type = "cryptofuture_stock"
                        else:
                            self.debug(f"❌ Unsupported SecurityType: {crypto_symbol.SecurityType}")
                            continue

                        stock_sec = self.AddEquity(
                            equity_symbol.Value,
                            Resolution.TICK,
                            Market.USA,
                            extendedMarketHours=self.extended_market_hours
                        )

                        # Add to framework with correct pair type
                        pair = self.TradingPairs.AddPair(
                            crypto_sec.Symbol,
                            stock_sec.Symbol,
                            pair_type
                        )

                        self.debug(f"✅ Added {pair_type} pair: {crypto_symbol.Value} ↔ {equity_symbol.Value}")

                    except Exception as e:
                        self.debug(f"❌ Failed to subscribe {crypto_symbol}/{equity_symbol}: {e}")

            except Exception as e:
                self.debug(f"❌ Error with {exchange} data source: {e}")

    def on_data(self, data: Slice):
        """Framework handles data processing automatically"""
        # CRITICAL: Call base class to trigger framework pipeline
        super().OnData(data)

        # Framework pipeline:
        # 1. Updates TradingPairs with latest prices
        # 2. ArbitrageAlphaModel.Update() generates Insights
        # 3. ArbitragePortfolioConstructionModel creates PortfolioTargets
        # 4. ArbitrageExecutionModel executes orders

    def on_order_event(self, order_event: OrderEvent):
        """Handle order events"""
        # Log invalid orders and terminate
        if order_event.Status == OrderStatus.Invalid:
            order = self.Transactions.GetOrderById(order_event.OrderId)
            order_value = order.GetValue(self.Securities[order_event.Symbol])

            error_msg = (
                f"❌ Order {order_event.OrderId} Invalid | "
                f"Symbol: {order_event.Symbol.Value} | "
                f"Direction: {order.Direction} | "
                f"Quantity: {order.Quantity} | "
                f"Value: ${abs(order_value):,.2f} | "
                f"Message: {order_event.Message}"
            )

            self.Error(error_msg)
            # self.Quit(f"Terminating due to invalid order: {order_event.OrderId}")

    def on_end_of_algorithm(self):
        """Output final statistics"""
        self.debug("")
        self.debug("=" * 60)
        self.debug("ALGORITHM COMPLETE")
        self.debug("=" * 60)

        # Insights summary
        self.debug(f"Total Insights Generated: {self.Insights.TotalCount}")

        # Trading pairs summary
        self.debug("")
        self.debug("TradingPair Summary:")
        for pair in self.TradingPairs:
            self.debug(f"  {pair.Key}:")
            self.debug(f"    Theoretical Spread: {pair.TheoreticalSpread:.4%}")
            self.debug(f"    Active Positions: {pair.ActivePositionCount}")
            self.debug(f"    Grid Levels: {len(list(pair.LevelPairs))}")

        # Multi-account summary
        if hasattr(self.portfolio, 'GetAccount'):
            self.debug("")
            self.debug("Multi-Account Summary:")
            try:
                ibkr = self.portfolio.GetAccount("IBKR")
                gate = self.portfolio.GetAccount("Gate")

                self.debug(f"  IBKR: ${ibkr.TotalPortfolioValue:,.2f} | Margin: ${ibkr.TotalMarginUsed:,.2f}")
                self.debug(f"  Gate: ${gate.TotalPortfolioValue:,.2f} | Margin: ${gate.TotalMarginUsed:,.2f}")
            except Exception as e:
                self.debug(f"  Error accessing accounts: {e}")

        self.debug("=" * 60)
