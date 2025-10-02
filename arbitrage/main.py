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
                for crypto, equity in trade_pairs[:5]:
                    try:
                        self.add_crypto(crypto)
                        if not self.spread_manager.is_equity_subscribed(equity):
                            self.add_equity(equity)
                        # Register the pair in SpreadManager
                        self.spread_manager.add_pair(crypto, equity)
                    except Exception as e:
                        self.debug(f"Failed to subscribe to {crypto.Symbol.Value}/{equity.Symbol.Value}: {str(e)}")

            except Exception as e:
                self.debug(f"Error initializing {exchange} data source: {str(e)}")

        self.debug(f"Successfully subscribed to {len(self.spread_manager.pairs)} crypto-stock pairs")
        self.debug(f"  Crypto tokens: {len(self.spread_manager.cryptos)}")
        self.debug(f"  Underlying stocks: {len(self.spread_manager.stocks)}")

    def on_data(self, data: Slice):
        """
        Process incoming data and calculate spreads between crypto tokens and stocks

        Phase 1: Monitor and log spread data only (no trading)
        Phase 2: Execute trades based on spread thresholds

        Args:
            data: Slice object containing tick data for both crypto and stocks
        """
        self.tick_count += 1

        # Iterate through all crypto-stock pairs
        for crypto_symbol, stock_symbol in self.spread_manager.get_all_pairs():

            # Check if we have data for both crypto and stock
            if not (data.ContainsKey(crypto_symbol) and data.ContainsKey(stock_symbol)):
                continue

            # Get crypto data
            crypto_data = data[crypto_symbol]
            if isinstance(crypto_data, list) and len(crypto_data) > 0:
                crypto_tick = crypto_data[-1]
            else:
                crypto_tick = crypto_data

            # Get stock data
            stock_data = data[stock_symbol]
            if isinstance(stock_data, list) and len(stock_data) > 0:
                stock_tick = stock_data[-1]
            else:
                stock_tick = stock_data

            # Extract prices
            crypto_price = getattr(crypto_tick, 'Price', None)
            stock_price = getattr(stock_tick, 'Price', None)

            if crypto_price is None or stock_price is None:
                continue

            # Calculate spread percentage
            spread_pct = self.spread_manager.calculate_spread_pct(crypto_price, stock_price)

            # Store data for monitoring
            pair_key = f"{crypto_symbol.Value}_{stock_symbol.Value}"
            self.orderbook_data[pair_key] = {
                'time': self.Time,
                'crypto_symbol': crypto_symbol.Value,
                'stock_symbol': stock_symbol.Value,
                'crypto_price': crypto_price,
                'stock_price': stock_price,
                'spread_pct': spread_pct
            }

            # Log every 100 ticks
            if self.tick_count % 100 == 0:
                self.debug(f"[{crypto_symbol.Value} <-> {stock_symbol.Value}] Tick #{self.tick_count}")
                self.debug(f"  Time: {self.Time}")
                self.debug(f"  Crypto: ${crypto_price:.2f} | Stock: ${stock_price:.2f}")
                self.debug(f"  Spread: {spread_pct:.2f}%")

                # Phase 2: Trading logic would go here
                # if spread_pct > threshold:
                #     # Open position: short crypto, long stock
                # elif spread_pct < -threshold:
                #     # Close position

    def on_end_of_algorithm(self):
        """Summary when algorithm ends"""
        self.debug("=" * 60)
        self.debug("Arbitrage Algorithm Summary")
        self.debug(f"Total ticks received: {self.tick_count}")
        self.debug(f"Crypto-Stock pairs: {len(self.spread_manager.pairs)}")
        self.debug(f"Crypto tokens: {len(self.spread_manager.cryptos)}")
        self.debug(f"Underlying stocks: {len(self.spread_manager.stocks)}")

        # Display final spreads
        if self.orderbook_data:
            self.debug("\nFinal Spreads:")
            for pair_key, data in self.orderbook_data.items():
                self.debug(f"  {data['crypto_symbol']} <-> {data['stock_symbol']}: {data['spread_pct']:.2f}%")

        self.debug("=" * 60)
