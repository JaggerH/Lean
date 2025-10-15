"""
Unit tests for SpreadManager using AlgorithmImports
"""
from multiprocessing import Value
import unittest
import sys
from pathlib import Path

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import AlgorithmImports (will be available when run via PythonTestRunner)
from AlgorithmImports import QCAlgorithm, Symbol, Security, Market, SecurityType
from spread_manager import SpreadManager


class TestAlgorithm(QCAlgorithm):
    """Simple test algorithm for SpreadManager testing"""

    def __init__(self):
        super().__init__()
        self._debug_messages = []

    def Debug(self, message):
        """Capture debug messages for testing"""
        self._debug_messages.append(message)
        print(f"[DEBUG] {message}")

    def get_debug_messages(self):
        """Get all captured debug messages"""
        return self._debug_messages

    def clear_debug_messages(self):
        """Clear debug message history"""
        self._debug_messages = []


class TestSpreadManagerInit(unittest.TestCase):
    """Test SpreadManager initialization"""

    def test_init(self):
        """Test SpreadManager initialization"""
        # Create test algorithm instance
        algo = TestAlgorithm()

        # Initialize SpreadManager (no strategy parameter needed)
        manager = SpreadManager(algo)

        # Verify initialization state
        self.assertIsNotNone(manager)
        self.assertEqual(manager.algorithm, algo)
        self.assertEqual(len(manager._spread_observers), 0)

        # Verify empty data structures
        self.assertEqual(len(manager.pairs), 0)
        self.assertEqual(len(manager.stock_to_cryptos), 0)
        self.assertEqual(len(manager.stocks), 0)
        self.assertEqual(len(manager.cryptos), 0)

        print("SpreadManager initialization test passed")

    def test_init_with_monitor_adapter(self):
        """Test initialization with monitor adapter"""
        algo = TestAlgorithm()

        # Create a mock monitor adapter
        class MockMonitor:
            pass

        monitor = MockMonitor()
        manager = SpreadManager(algo, monitor_adapter=monitor)

        self.assertEqual(manager.monitor, monitor)
        print("Monitor adapter initialization test passed")

    def test_add_pair(self):
        """Test adding trading pair"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # Create Symbol objects
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # Create mock securities
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        crypto = MockSecurity(crypto_symbol)
        stock = MockSecurity(stock_symbol)

        # Add trading pair
        manager.add_pair(crypto, stock)

        # Verify
        self.assertEqual(len(manager.pairs), 1)
        self.assertEqual(manager.pairs[crypto.Symbol], stock.Symbol)
        self.assertEqual(len(manager.stock_to_cryptos[stock.Symbol]), 1)
        self.assertIn(crypto, manager.cryptos)
        self.assertIn(stock, manager.stocks)

        print("Add pair test passed")

    def test_get_all_pairs(self):
        """Test getting all trading pairs"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # Create mock security helper
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        # Create two trading pairs
        crypto1 = MockSecurity(Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken))
        stock1 = MockSecurity(Symbol.Create("TSLA", SecurityType.Equity, Market.USA))

        crypto2 = MockSecurity(Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken))
        stock2 = MockSecurity(Symbol.Create("AAPL", SecurityType.Equity, Market.USA))

        manager.add_pair(crypto1, stock1)
        manager.add_pair(crypto2, stock2)

        # Get all pairs
        pairs = manager.get_all_pairs()

        # Verify
        self.assertEqual(len(pairs), 2)
        self.assertIn((crypto1.Symbol, stock1.Symbol), pairs)
        self.assertIn((crypto2.Symbol, stock2.Symbol), pairs)

        print("Get all pairs test passed")

    def test_calculate_spread_pct(self):
        """Test spread percentage calculation"""
        # Static method, doesn't need algorithm instance

        # Test scenario 1: token higher than stock
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.5,
            token_ask=150.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # Should return positive value (short token, long stock)
        self.assertGreater(spread, 0)

        # Test scenario 2: token lower than stock
        spread = SpreadManager.calculate_spread_pct(
            token_bid=149.5,
            token_ask=149.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # Should return negative value (long token, short stock)
        self.assertLess(spread, 0)

        print("Calculate spread percentage test passed")

    def test_get_cryptos_for_stock(self):
        """Test getting all cryptos for a stock"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # Create mock security helper
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        # Create one stock with multiple cryptos
        stock = MockSecurity(Symbol.Create("TSLA", SecurityType.Equity, Market.USA))
        crypto1 = MockSecurity(Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken))
        crypto2 = MockSecurity(Symbol.Create("TSLAON", SecurityType.Crypto, Market.Kraken))

        manager.add_pair(crypto1, stock)
        manager.add_pair(crypto2, stock)

        # Get all cryptos for this stock
        cryptos = manager.get_cryptos_for_stock(stock.Symbol)

        # Verify
        self.assertEqual(len(cryptos), 2)
        self.assertIn(crypto1.Symbol, cryptos)
        self.assertIn(crypto2.Symbol, cryptos)

        print("Get cryptos for stock test passed")


class TestSpreadManagerCalculations(unittest.TestCase):
    """Test spread calculation edge cases"""

    def test_calculate_spread_pct_zero_token_bid(self):
        """Test edge case with token bid = 0"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=0.0,
            token_ask=150.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # When token_bid is 0, should return 0
        self.assertEqual(spread, 0.0)
        print("Zero token bid test passed")

    def test_calculate_spread_pct_zero_token_ask(self):
        """Test edge case with token ask = 0"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.0,
            token_ask=0.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # When token_ask is 0, should return 0
        self.assertEqual(spread, 0.0)
        print("Zero token ask test passed")

    def test_calculate_spread_pct_equal_prices(self):
        """Test all prices equal"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.0,
            token_ask=150.0,
            stock_bid=150.0,
            stock_ask=150.0
        )

        # When prices are equal, spread should be 0
        self.assertEqual(spread, 0.0)
        print("Equal prices test passed")

    def test_calculate_spread_pct_large_positive_spread(self):
        """Test large positive spread (token significantly higher than stock)"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=200.0,
            token_ask=201.0,
            stock_bid=150.0,
            stock_ask=151.0
        )

        # Should return positive value, and large
        self.assertGreater(spread, 0.2)  # Over 20%
        print(f"Large positive spread test passed (spread={spread:.4f})")

    def test_calculate_spread_pct_large_negative_spread(self):
        """Test large negative spread (token significantly lower than stock)"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=100.0,
            token_ask=101.0,
            stock_bid=150.0,
            stock_ask=151.0
        )

        # Should return negative value, and large
        self.assertLess(spread, -0.3)  # Below -30%
        print(f"Large negative spread test passed (spread={spread:.4f})")

    def test_calculate_spread_pct_chooses_larger_absolute(self):
        """Test choosing larger absolute spread value"""
        # Scenario: short token spread = 0.2%, long token spread = 0.4%
        # Should choose 0.4%
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.5,
            token_ask=150.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # Scenario 1: (150.5 - 150.1) / 150.5 = 0.266%
        # Scenario 2: (150.6 - 150.0) / 150.6 = 0.398%
        # Should return Scenario 2 (larger absolute value)
        self.assertAlmostEqual(spread, 0.00398, places=5)
        print(f"Larger absolute value selection test passed (spread={spread:.5f})")


class TestSpreadManagerObserverPattern(unittest.TestCase):
    """Test observer pattern functionality"""

    def test_register_observer(self):
        """Test registering spread observer"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # Create mock callback
        calls = []

        def mock_callback(pair_symbol, spread_pct):
            calls.append({'pair': pair_symbol, 'spread': spread_pct})

        # Register observer
        manager.register_observer(mock_callback)

        # Verify
        self.assertEqual(len(manager._spread_observers), 1)
        self.assertIn(mock_callback, manager._spread_observers)

        print("Register observer test passed")

    def test_unregister_observer(self):
        """Test unregistering spread observer"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        def mock_callback(pair_symbol, spread_pct):
            pass

        # Register then unregister
        manager.register_observer(mock_callback)
        manager.unregister_observer(mock_callback)

        # Verify
        self.assertEqual(len(manager._spread_observers), 0)

        print("Unregister observer test passed")

    def test_notify_observers(self):
        """Test notifying observers"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        calls = []

        def mock_callback(pair_symbol, spread_pct):
            calls.append({
                'crypto': pair_symbol[0],
                'stock': pair_symbol[1],
                'spread': spread_pct
            })

        # Register observer
        manager.register_observer(mock_callback)

        # Create test data
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # Notify observers
        manager._notify_observers(pair_symbol, 0.05)

        # Verify callback was called
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['crypto'], crypto_symbol)
        self.assertEqual(calls[0]['stock'], stock_symbol)
        self.assertAlmostEqual(calls[0]['spread'], 0.05)

        print("Notify observers test passed")

    def test_multiple_observers(self):
        """Test multiple observers receive notifications"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        calls1 = []
        calls2 = []

        def callback1(pair_symbol, spread_pct):
            calls1.append(spread_pct)

        def callback2(pair_symbol, spread_pct):
            calls2.append(spread_pct)

        # Register two observers
        manager.register_observer(callback1)
        manager.register_observer(callback2)

        # Notify observers
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        manager._notify_observers((crypto_symbol, stock_symbol), 0.03)

        # Verify both callbacks were called
        self.assertEqual(len(calls1), 1)
        self.assertEqual(len(calls2), 1)
        self.assertAlmostEqual(calls1[0], 0.03)
        self.assertAlmostEqual(calls2[0], 0.03)

        print("Multiple observers test passed")

    def test_observer_error_handling(self):
        """Test observer error handling (one observer error doesn't affect others)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        calls = []
        error_calls = []

        def broken_callback(pair_symbol, spread_pct):
            error_calls.append(spread_pct)
            raise RuntimeError("Test error")

        def working_callback(pair_symbol, spread_pct):
            calls.append(spread_pct)

        # Register two observers (broken first, then working)
        manager.register_observer(broken_callback)
        manager.register_observer(working_callback)

        # Notify observers - broken observer will raise, but should be caught
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # The error should be caught internally and not propagate
        # No exception should be raised to the caller
        manager._notify_observers((crypto_symbol, stock_symbol), 0.02)

        # Verify broken observer was called (before it raised)
        self.assertEqual(len(error_calls), 1)

        # Verify working observer was still called (after broken observer failed)
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0], 0.02)

        # Verify error was logged
        debug_msgs = algo.get_debug_messages()
        self.assertTrue(any("Observer error" in msg for msg in debug_msgs))

        print("Observer error handling test passed")


class TestSpreadManagerExecutionEngine(unittest.TestCase):
    """Test ExecutionEngine integration methods"""

    def test_get_pair_symbol_from_crypto_exists(self):
        """Test getting pair symbol from crypto symbol (exists)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        manager.add_pair(MockSecurity(crypto_symbol), MockSecurity(stock_symbol))

        # Get pair
        pair = manager.get_pair_symbol_from_crypto(crypto_symbol)

        # Verify
        self.assertIsNotNone(pair)
        self.assertEqual(pair[0], crypto_symbol)
        self.assertEqual(pair[1], stock_symbol)

        print("Get pair symbol from crypto (exists) test passed")

    def test_get_pair_symbol_from_crypto_not_exists(self):
        """Test getting pair symbol from crypto symbol (not exists)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)

        # Get non-existent pair
        pair = manager.get_pair_symbol_from_crypto(crypto_symbol)

        # Verify
        self.assertIsNone(pair)

        print("Get pair symbol from crypto (not exists) test passed")


class TestSpreadManagerManyToOne(unittest.TestCase):
    """Test many-to-one crypto-stock relationships"""

    def test_multiple_cryptos_one_stock(self):
        """Test multiple cryptos paired with one stock"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        crypto1_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        crypto2_symbol = Symbol.Create("TSLAON", SecurityType.Crypto, Market.Kraken)
        crypto3_symbol = Symbol.Create("TSLAzUSD", SecurityType.Crypto, Market.Kraken)

        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        stock = MockSecurity(stock_symbol)

        # Add three cryptos all paired with same stock
        manager.add_pair(MockSecurity(crypto1_symbol), stock)
        manager.add_pair(MockSecurity(crypto2_symbol), stock)
        manager.add_pair(MockSecurity(crypto3_symbol), stock)

        # Verify stock's crypto list
        cryptos = manager.get_cryptos_for_stock(stock_symbol)
        self.assertEqual(len(cryptos), 3)
        self.assertIn(crypto1_symbol, cryptos)
        self.assertIn(crypto2_symbol, cryptos)
        self.assertIn(crypto3_symbol, cryptos)

        # Verify only one stock was added
        self.assertEqual(len(manager.stocks), 1)

        print("Multiple cryptos one stock test passed")


if __name__ == '__main__':
    print("Running SpreadManager tests...\n")
    unittest.main(verbosity=2)
