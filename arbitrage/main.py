# region imports
from AlgorithmImports import *
import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import KrakenSymbolManager
from SpreadManager import SpreadManager
# endregion

class Arbitrage(QCAlgorithm):
    """
    Arbitrage algorithm for trading crypto stock tokens vs underlying stocks

    Strategy: Monitor spread between Kraken xStocks and IBKR stocks
    Phase 1: Subscription and data monitoring only (no trading)
    Phase 2: Trading logic based on spread thresholds
    """

    def initialize(self):
        """Initialize algorithm with dual brokerage (Kraken + IBKR) settings"""
        # Set start date for live trading
        self.set_start_date(2025, 1, 1)
        self.set_cash(100000)

        # Initialize data sources
        self.sources = {
            "kraken": KrakenSymbolManager()
        }

        # Initialize SpreadManager for managing crypto-stock pairs
        self.spread_manager = SpreadManager(self)

        # Data storage for monitoring
        self.orderbook_data = {}
        self.tick_count = 0

        # Cache for latest quotes (to handle asynchronous tick arrivals)
        self.latest_quotes = {}

        # Fetch and subscribe to trading pairs from all data sources
        self.debug("Initializing data sources and fetching trading pairs...")

        for exchange, manager in self.sources.items():
            try:
                # Fetch tokenized stocks from exchange
                self.debug(f"Fetching tokenized stocks from {exchange}...")
                manager.get_tokenize_stocks()

                # Get trading pairs
                trade_pairs = manager.get_trade_pairs()
                self.debug(f"Found {len(trade_pairs)} trading pairs from {exchange}")

                # Subscribe to each pair (limit to 5 for testing)
                for crypto_symbol, equity_symbol in trade_pairs[:5]:
                    try:
                        # Subscribe to Tick resolution to get orderbook (bid/ask) data
                        crypto_security = self.add_crypto(
                            crypto_symbol.value,
                            Resolution.Tick,
                            Market.Kraken
                        )

                        # Check if stock is already subscribed
                        if equity_symbol in self.securities:
                            equity_security = self.securities[equity_symbol]
                        else:
                            equity_security = self.add_equity(
                                equity_symbol.value,
                                Resolution.Tick,
                                Market.USA,
                                extended_market_hours=True
                            )

                        # Register the pair in SpreadManager
                        self.spread_manager.add_pair(crypto_security, equity_security)
                    except Exception as e:
                        self.debug(f"Failed to subscribe to {crypto_symbol.value}/{equity_symbol.value}: {str(e)}")

            except Exception as e:
                self.debug(f"Error initializing {exchange} data source: {str(e)}")

        self.debug(f"Successfully subscribed to {len(self.spread_manager.pairs)} crypto-stock pairs")
        self.debug(f"  Crypto tokens: {len(self.spread_manager.cryptos)}")
        self.debug(f"  Underlying stocks: {len(self.spread_manager.stocks)}")

    def on_data(self, data: Slice):
        """
        Process incoming tick data and calculate bidirectional spreads

        Phase 1: Monitor and log spread data only (no trading)
        Phase 2: Execute trades based on spread thresholds

        Args:
            data: Slice object containing tick data for both crypto and stocks
        """
        # Check if we have tick data
        if not data.Ticks or len(data.Ticks) == 0:
            return

        self.tick_count += 1

        # Debug: Log incoming tick symbols every 50 ticks
        if self.tick_count % 50 == 0:
            tick_symbols = [str(symbol.Value) for symbol in data.Ticks.Keys]
            self.debug(f"Tick #{self.tick_count} - Received ticks from: {', '.join(tick_symbols)}")

            # Log registered pairs
            pairs_str = [f"{c.Value}<->{s.Value}" for c, s in self.spread_manager.get_all_pairs()]
            self.debug(f"Registered pairs: {', '.join(pairs_str)}")

        # First, update cache with incoming quotes
        for symbol in data.Ticks.Keys:
            ticks = data.Ticks[symbol]
            for tick in ticks:
                if tick.TickType == TickType.Quote:
                    # Cache the latest quote for this symbol
                    self.latest_quotes[symbol] = tick

        # Iterate through all crypto-stock pairs
        for crypto_symbol, stock_symbol in self.spread_manager.get_all_pairs():
            # Get quotes from cache (not from current data slice)
            crypto_quote = self.latest_quotes.get(crypto_symbol)
            stock_quote = self.latest_quotes.get(stock_symbol)

            # Skip if we don't have both quotes cached yet
            if not crypto_quote or not stock_quote:
                # Debug: Log first 30 times when we skip due to missing quotes
                if self.tick_count <= 30:
                    has_crypto = crypto_quote is not None
                    has_stock = stock_quote is not None
                    self.debug(f"Tick #{self.tick_count}: Skipping {crypto_symbol.Value}<->{stock_symbol.Value} - Cached quotes: crypto={has_crypto}, stock={has_stock}")
                continue

            # Debug: Log first successful spread calculation
            if self.tick_count <= 5:
                self.debug(f"✅ Tick #{self.tick_count}: SUCCESS! {crypto_symbol.Value}<->{stock_symbol.Value} - Both quotes available in cache")

            # Calculate bidirectional spread (4 prices: bid/ask for both)
            spread_pct = self.spread_manager.calculate_spread_pct(
                crypto_quote.BidPrice,  # token_bid
                crypto_quote.AskPrice,  # token_ask
                stock_quote.BidPrice,   # stock_bid
                stock_quote.AskPrice    # stock_ask
            )

            # Determine arbitrage direction
            direction = "SHORT_TOKEN" if spread_pct > 0 else "LONG_TOKEN"

            # Debug: Log first 3 successful spread calculations immediately
            if self.tick_count <= 3:
                self.debug("=" * 60)
                self.debug(f"🎯 SPREAD CALCULATED! Tick #{self.tick_count}")
                self.debug(f"Pair: {crypto_symbol.Value} <-> {stock_symbol.Value}")
                self.debug(f"Time: {self.Time}")
                self.debug(f"Crypto: Bid=${crypto_quote.BidPrice:.4f}, Ask=${crypto_quote.AskPrice:.4f}")
                self.debug(f"Stock:  Bid=${stock_quote.BidPrice:.4f}, Ask=${stock_quote.AskPrice:.4f}")
                self.debug(f"Spread: {spread_pct:.4f}% ({direction})")
                self.debug("=" * 60)

            # Store monitoring data
            pair_key = f"{crypto_symbol.Value}_{stock_symbol.Value}"
            self.orderbook_data[pair_key] = {
                'time': self.Time,
                'crypto_symbol': crypto_symbol.Value,
                'stock_symbol': stock_symbol.Value,
                'crypto_bid': crypto_quote.BidPrice,
                'crypto_ask': crypto_quote.AskPrice,
                'stock_bid': stock_quote.BidPrice,
                'stock_ask': stock_quote.AskPrice,
                'spread_pct': spread_pct,
                'direction': direction
            }

            # Log every 100 ticks
            if self.tick_count % 100 == 0:
                self.debug("=" * 60)
                self.debug(f"[{crypto_symbol.Value} <-> {stock_symbol.Value}] Tick #{self.tick_count}")
                self.debug(f"Time: {self.Time}")
                self.debug(f"Crypto: Bid=${crypto_quote.BidPrice:.4f}, Ask=${crypto_quote.AskPrice:.4f}")
                self.debug(f"Stock:  Bid=${stock_quote.BidPrice:.4f}, Ask=${stock_quote.AskPrice:.4f}")
                self.debug(f"Spread: {spread_pct:.4f}% ({direction})")

                # Phase 2: Trading logic would go here
                # if spread_pct > threshold:
                #     # Open position based on direction
                # elif spread_pct < -threshold:
                #     # Close position

    def on_end_of_algorithm(self):
        """Display detailed arbitrage monitoring summary"""
        self.debug("=" * 60)
        self.debug("ARBITRAGE ALGORITHM SUMMARY")
        self.debug("=" * 60)
        self.debug(f"Total ticks received: {self.tick_count}")
        self.debug(f"Crypto-Stock pairs: {len(self.spread_manager.pairs)}")
        self.debug(f"Crypto tokens: {len(self.spread_manager.cryptos)}")
        self.debug(f"Underlying stocks: {len(self.spread_manager.stocks)}")

        # Display final spreads with orderbook data
        if self.orderbook_data:
            self.debug("\nFinal Spreads (with Orderbook):")
            for pair_key, d in self.orderbook_data.items():
                self.debug(f"\n{d['crypto_symbol']} <-> {d['stock_symbol']}:")
                self.debug(f"  Time: {d['time']}")
                self.debug(f"  Crypto: Bid=${d['crypto_bid']:.4f}, Ask=${d['crypto_ask']:.4f}")
                self.debug(f"  Stock:  Bid=${d['stock_bid']:.4f}, Ask=${d['stock_ask']:.4f}")
                self.debug(f"  Spread: {d['spread_pct']:.4f}% ({d['direction']})")

        self.debug("=" * 60)
