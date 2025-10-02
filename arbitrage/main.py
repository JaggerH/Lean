# region imports
from AlgorithmImports import *
import sys
import os
sys.path.append(os.path.dirname(__file__))
from utils import get_xstocks_from_kraken
from QuantConnect.Brokerages.Kraken import KrakenSymbolMapper
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

        # Initialize SpreadManager for managing crypto-stock pairs
        self.spread_manager = SpreadManager(self)

        # Initialize Kraken symbol mapper
        self.kraken_mapper = KrakenSymbolMapper()

        # Fetch xStocks assets from Kraken
        self.debug("Fetching xStocks from Kraken API...")
        try:
            xstocks_data = get_xstocks_from_kraken()
        except Exception as e:
            self.debug(f"Error fetching Kraken data: {str(e)}")
            return

        # Data storage for monitoring
        self.orderbook_data = {}

        # Subscribe to first few xStocks for testing (limit to avoid overwhelming)
        xstocks = list(xstocks_data.keys())[:5]

        self.debug(f"Found {len(xstocks_data)} xStocks, subscribing to {len(xstocks)}...")

        for pair_name in xstocks:
            try:
                # Try to create LEAN symbol and check if it's in the mapper
                lean_symbol_str = pair_name.replace('x', '').replace('/', '')
                lean_symbol = Symbol.Create(lean_symbol_str, SecurityType.Crypto, Market.Kraken)

                # Check if this symbol is known by the mapper
                if self.kraken_mapper.IsKnownLeanSymbol(lean_symbol):
                    # Subscribe to crypto and corresponding stock using SpreadManager
                    self.subscribe_crypto(lean_symbol_str, Market.KRAKEN)
                else:
                    self.debug(f"Symbol {lean_symbol_str} not in Kraken symbol database, skipping {pair_name}")

            except Exception as e:
                self.debug(f"Failed to subscribe to {pair_name}: {str(e)}")

        self.debug(f"Successfully subscribed to {len(self.spread_manager.pairs)} crypto-stock pairs")
        self.debug(f"  Crypto tokens: {len(self.spread_manager.cryptos)}")
        self.debug(f"  Underlying stocks: {len(self.spread_manager.stocks)}")
        self.tick_count = 0

    def subscribe_crypto(self, crypto_symbol: str, market: str):
        """
        Subscribe to a crypto token and automatically subscribe to its underlying stock

        Args:
            crypto_symbol: Crypto symbol string (e.g., "TSLAxUSD", "AAPLUSD")
            market: Market string (e.g., Market.KRAKEN)

        Side Effects:
            - Subscribes to crypto via AddCrypto
            - Subscribes to underlying stock via SpreadManager (with deduplication)
            - Registers the pair in SpreadManager
        """
        try:
            # Subscribe to crypto token
            crypto = self.add_crypto(crypto_symbol, Resolution.TICK, market)
            self.debug(f"Subscribed to crypto: {crypto.Symbol}")

            # Subscribe to corresponding stock (SpreadManager handles deduplication)
            stock = self.spread_manager.subscribe_stock_by_crypto(crypto)
            self.debug(f"  Paired with stock: {stock.Symbol}")

            # Register the crypto-stock pair
            self.spread_manager.add_pair(crypto, stock)

        except Exception as e:
            self.debug(f"Error in subscribe_crypto for {crypto_symbol}: {str(e)}")

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
