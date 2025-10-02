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
                                Market.USA
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

        # Iterate through all crypto-stock pairs
        for crypto_symbol, stock_symbol in self.spread_manager.get_all_pairs():

            # Check if both symbols have tick data
            if not (data.Ticks.ContainsKey(crypto_symbol) and
                    data.Ticks.ContainsKey(stock_symbol)):
                continue

            # Get tick lists
            crypto_ticks = data.Ticks[crypto_symbol]
            stock_ticks = data.Ticks[stock_symbol]

            # Extract the latest QuoteTick (orderbook data)
            crypto_quote = None
            for tick in crypto_ticks:
                if tick.TickType == TickType.Quote:
                    crypto_quote = tick

            stock_quote = None
            for tick in stock_ticks:
                if tick.TickType == TickType.Quote:
                    stock_quote = tick

            # Skip if no QuoteTicks available
            if not crypto_quote or not stock_quote:
                continue

            # Calculate bidirectional spread (4 prices: bid/ask for both)
            spread_pct = self.spread_manager.calculate_spread_pct(
                crypto_quote.BidPrice,  # token_bid
                crypto_quote.AskPrice,  # token_ask
                stock_quote.BidPrice,   # stock_bid
                stock_quote.AskPrice    # stock_ask
            )

            # Determine arbitrage direction
            direction = "SHORT_TOKEN" if spread_pct > 0 else "LONG_TOKEN"

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
