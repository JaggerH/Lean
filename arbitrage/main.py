# region imports
from AlgorithmImports import *
import sys
import os
sys.path.append(os.path.dirname(__file__))
from utils import get_xstocks_from_kraken
from QuantConnect.Brokerages.Kraken import KrakenSymbolMapper
# endregion

class Arbitrage(QCAlgorithm):
    """
    Arbitrage algorithm monitoring Kraken xStocks orderbook data in real-time
    """

    def initialize(self):
        """Initialize algorithm with live trading settings"""
        # Set start date for live trading
        self.set_start_date(2025, 1, 1)
        self.set_cash(100000)

        # Initialize Kraken symbol mapper
        self.kraken_mapper = KrakenSymbolMapper()

        # Fetch xStocks assets from Kraken
        self.debug("Fetching xStocks from Kraken API...")
        try:
            xstocks_data = get_xstocks_from_kraken()
        except Exception as e:
            self.debug(f"Error fetching Kraken data: {str(e)}")
            return

        # Store symbols and their subscriptions
        self.symbols = {}
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
                    # Subscribe using the known symbol
                    crypto = self.add_crypto(lean_symbol_str, Resolution.TICK, Market.KRAKEN)
                    self.symbols[pair_name] = crypto.symbol
                    self.debug(f"Subscribed to {pair_name} as {lean_symbol_str}")
                else:
                    self.debug(f"Symbol {lean_symbol_str} not in Kraken symbol database, skipping {pair_name}")

            except Exception as e:
                self.debug(f"Failed to subscribe to {pair_name}: {str(e)}")

        self.debug(f"Successfully subscribed to {len(self.symbols)} symbols")
        self.tick_count = 0

    def on_data(self, data: Slice):
        """
        Process incoming orderbook data (quotes) for subscribed symbols
        Arguments:
            data: Slice object containing tick data with bid/ask prices
        """
        self.tick_count += 1

        # Process each symbol's tick data
        for pair_name, symbol in self.symbols.items():
            if data.contains_key(symbol):
                ticks = data[symbol]

                # data[symbol] returns a list of ticks, get the latest one
                if isinstance(ticks, list) and len(ticks) > 0:
                    tick = ticks[-1]
                else:
                    tick = ticks

                # Store orderbook data (top of book: best bid/ask)
                self.orderbook_data[pair_name] = {
                    'time': tick.time,
                    'bid': tick.bid_price if hasattr(tick, 'bid_price') else None,
                    'ask': tick.ask_price if hasattr(tick, 'ask_price') else None,
                    'bid_size': tick.bid_size if hasattr(tick, 'bid_size') else None,
                    'ask_size': tick.ask_size if hasattr(tick, 'ask_size') else None,
                    'last_price': tick.price if hasattr(tick, 'price') else None,
                    'volume': tick.quantity if hasattr(tick, 'quantity') else None
                }

                # Log every 100 ticks
                if self.tick_count % 100 == 0:
                    ob = self.orderbook_data[pair_name]
                    if ob['bid'] and ob['ask']:
                        spread = ob['ask'] - ob['bid']
                        mid_price = (ob['bid'] + ob['ask']) / 2

                        self.debug(f"[{pair_name}] Tick #{self.tick_count}")
                        self.debug(f"  Time: {ob['time']}")
                        self.debug(f"  Bid: ${ob['bid']:.2f} (size: {ob['bid_size']})")
                        self.debug(f"  Ask: ${ob['ask']:.2f} (size: {ob['ask_size']})")
                        self.debug(f"  Mid: ${mid_price:.2f} | Spread: ${spread:.2f}")

    def on_end_of_algorithm(self):
        """Summary when algorithm ends"""
        self.debug("=" * 60)
        self.debug("Arbitrage Algorithm Summary")
        self.debug(f"Total ticks received: {self.tick_count}")
        self.debug(f"Monitored symbols: {len(self.symbols)}")
        self.debug("=" * 60)
