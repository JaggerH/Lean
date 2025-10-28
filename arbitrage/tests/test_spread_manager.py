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
from spread_manager import SpreadManager, MarketState, SpreadSignal


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


class TestMarketStateEnum(unittest.TestCase):
    """Test MarketState enum"""

    def test_market_state_values(self):
        """Test MarketState enum values"""
        self.assertEqual(MarketState.CROSSED.value, "crossed")
        self.assertEqual(MarketState.LIMIT_OPPORTUNITY.value, "limit")
        self.assertEqual(MarketState.NO_OPPORTUNITY.value, "none")
        print("MarketState enum values test passed")

    def test_market_state_members(self):
        """Test MarketState enum members"""
        self.assertIsInstance(MarketState.CROSSED, MarketState)
        self.assertIsInstance(MarketState.LIMIT_OPPORTUNITY, MarketState)
        self.assertIsInstance(MarketState.NO_OPPORTUNITY, MarketState)
        print("MarketState enum members test passed")


class TestSpreadSignalDataclass(unittest.TestCase):
    """Test SpreadSignal dataclass"""

    def test_spread_signal_instantiation(self):
        """Test creating SpreadSignal instances"""
        # Create test symbols
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        signal = SpreadSignal(
            pair_symbol=(crypto_symbol, stock_symbol),
            market_state=MarketState.CROSSED,
            theoretical_spread=0.005,
            executable_spread=0.004,
            direction="SHORT_SPREAD"
        )

        self.assertEqual(signal.pair_symbol, (crypto_symbol, stock_symbol))
        self.assertEqual(signal.market_state, MarketState.CROSSED)
        self.assertEqual(signal.theoretical_spread, 0.005)
        self.assertEqual(signal.executable_spread, 0.004)
        self.assertEqual(signal.direction, "SHORT_SPREAD")
        # Test @property methods
        self.assertTrue(signal.is_crossed)
        self.assertFalse(signal.has_limit_opportunity)
        self.assertTrue(signal.is_executable)

        print("SpreadSignal instantiation test passed")

    def test_spread_signal_no_opportunity(self):
        """Test SpreadSignal with NO_OPPORTUNITY state"""
        # Create test symbols
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        signal = SpreadSignal(
            pair_symbol=(crypto_symbol, stock_symbol),
            market_state=MarketState.NO_OPPORTUNITY,
            theoretical_spread=0.002,
            executable_spread=None,  # Should be None for no opportunity
            direction=None  # Should be None for no opportunity
        )

        self.assertEqual(signal.market_state, MarketState.NO_OPPORTUNITY)
        self.assertIsNone(signal.executable_spread)
        self.assertIsNone(signal.direction)
        # Test @property methods
        self.assertFalse(signal.is_crossed)
        self.assertFalse(signal.has_limit_opportunity)
        self.assertFalse(signal.is_executable)

        print("SpreadSignal NO_OPPORTUNITY test passed")

    def test_spread_signal_limit_opportunity(self):
        """Test SpreadSignal with LIMIT_OPPORTUNITY state"""
        # Create test symbols
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        signal = SpreadSignal(
            pair_symbol=(crypto_symbol, stock_symbol),
            market_state=MarketState.LIMIT_OPPORTUNITY,
            theoretical_spread=0.003,
            executable_spread=None,  # LIMIT_OPPORTUNITY doesn't have executable_spread
            direction="LONG_SPREAD"
        )

        self.assertEqual(signal.market_state, MarketState.LIMIT_OPPORTUNITY)
        self.assertIsNone(signal.executable_spread)  # Should be None for LIMIT_OPPORTUNITY
        self.assertEqual(signal.direction, "LONG_SPREAD")
        # Test @property methods
        self.assertFalse(signal.is_crossed)
        self.assertTrue(signal.has_limit_opportunity)
        self.assertFalse(signal.is_executable)  # No executable spread

        print("SpreadSignal LIMIT_OPPORTUNITY test passed")


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
        """Test spread percentage calculation (now returns dict)"""
        # Static method, doesn't need algorithm instance

        # Test scenario 1: token higher than stock (CROSSED Market)
        result = SpreadManager.calculate_spread_pct(
            token_bid=150.5,
            token_ask=150.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # Should return dict
        self.assertIsInstance(result, dict)
        # Should be CROSSED Market
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        # Theoretical spread should be positive
        self.assertGreater(result["theoretical_spread"], 0)
        # Should have executable spread
        self.assertIsNotNone(result["executable_spread"])

        # Test scenario 2: token lower than stock (CROSSED Market)
        result = SpreadManager.calculate_spread_pct(
            token_bid=149.5,
            token_ask=149.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # Should return dict
        self.assertIsInstance(result, dict)
        # Should be CROSSED Market
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        # Theoretical spread should be negative
        self.assertLess(result["theoretical_spread"], 0)
        # Should have executable spread
        self.assertIsNotNone(result["executable_spread"])

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
        """Test edge case with token bid = 0 (now returns dict)"""
        result = SpreadManager.calculate_spread_pct(
            token_bid=0.0,
            token_ask=150.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # Should return NO_OPPORTUNITY when token_bid is 0
        self.assertIsInstance(result, dict)
        self.assertEqual(result["market_state"], MarketState.NO_OPPORTUNITY)
        self.assertEqual(result["theoretical_spread"], 0.0)
        self.assertIsNone(result["executable_spread"])
        print("Zero token bid test passed")

    def test_calculate_spread_pct_zero_token_ask(self):
        """Test edge case with token ask = 0 (now returns dict)"""
        result = SpreadManager.calculate_spread_pct(
            token_bid=150.0,
            token_ask=0.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # Should return NO_OPPORTUNITY when token_ask is 0
        self.assertIsInstance(result, dict)
        self.assertEqual(result["market_state"], MarketState.NO_OPPORTUNITY)
        self.assertEqual(result["theoretical_spread"], 0.0)
        self.assertIsNone(result["executable_spread"])
        print("Zero token ask test passed")

    def test_calculate_spread_pct_equal_prices(self):
        """Test all prices equal (now returns dict)"""
        result = SpreadManager.calculate_spread_pct(
            token_bid=150.0,
            token_ask=150.0,
            stock_bid=150.0,
            stock_ask=150.0
        )

        # When prices are equal, should be NO_OPPORTUNITY
        self.assertIsInstance(result, dict)
        self.assertEqual(result["market_state"], MarketState.NO_OPPORTUNITY)
        self.assertEqual(result["theoretical_spread"], 0.0)
        self.assertIsNone(result["executable_spread"])
        print("Equal prices test passed")

    def test_calculate_spread_pct_large_positive_spread(self):
        """Test large positive spread (token significantly higher than stock)"""
        result = SpreadManager.calculate_spread_pct(
            token_bid=200.0,
            token_ask=201.0,
            stock_bid=150.0,
            stock_ask=151.0
        )

        # Should return dict with CROSSED Market (token_bid > stock_ask)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "SHORT_SPREAD")
        # Theoretical spread should be positive and large
        self.assertGreater(result["theoretical_spread"], 0.2)  # Over 20%
        # Should have executable spread
        self.assertIsNotNone(result["executable_spread"])
        self.assertGreater(result["executable_spread"], 0.2)
        print(f"Large positive spread test passed (spread={result['theoretical_spread']:.4f})")

    def test_calculate_spread_pct_large_negative_spread(self):
        """Test large negative spread (token significantly lower than stock)"""
        result = SpreadManager.calculate_spread_pct(
            token_bid=100.0,
            token_ask=101.0,
            stock_bid=150.0,
            stock_ask=151.0
        )

        # Should return dict with CROSSED Market (stock_bid > token_ask)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "LONG_SPREAD")
        # Theoretical spread should be negative and large
        self.assertLess(result["theoretical_spread"], -0.3)  # Below -30%
        # Should have executable spread (which will also be negative)
        self.assertIsNotNone(result["executable_spread"])
        self.assertLess(result["executable_spread"], -0.3)
        print(f"Large negative spread test passed (spread={result['theoretical_spread']:.4f})")

    def test_calculate_spread_pct_chooses_larger_absolute(self):
        """Test choosing larger absolute spread value"""
        # Scenario: short token spread = 0.2%, long token spread = 0.4%
        # Should choose 0.4% as theoretical spread
        result = SpreadManager.calculate_spread_pct(
            token_bid=150.5,
            token_ask=150.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # This should be CROSSED Market (token_bid=150.5 > stock_ask=150.1)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "SHORT_SPREAD")

        # Scenario 1 (SHORT_SPREAD): (150.5 - 150.1) / 150.5 = 0.266%
        # Scenario 2 (LONG_SPREAD): (150.6 - 150.0) / 150.6 = 0.398%
        # Theoretical spread should choose larger absolute value (Scenario 2)
        self.assertAlmostEqual(result["theoretical_spread"], 0.00398, places=5)

        # Executable spread should be the SHORT_SPREAD (since that's the direction)
        self.assertAlmostEqual(result["executable_spread"], 0.00266, places=5)

        print(f"Larger absolute value selection test passed (theoretical={result['theoretical_spread']:.5f})")


class TestSpreadManagerObserverPattern(unittest.TestCase):
    """Test observer pattern functionality"""

    def test_register_observer(self):
        """Test registering spread observer"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # Create mock callback
        calls = []

        def mock_callback(spread_signal):
            calls.append({'signal': spread_signal})

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

        def mock_callback(spread_signal):
            pass

        # Register then unregister
        manager.register_observer(mock_callback)
        manager.unregister_observer(mock_callback)

        # Verify
        self.assertEqual(len(manager._spread_observers), 0)

        print("Unregister observer test passed")

    def test_notify_observers(self):
        """Test notifying observers with SpreadSignal"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        calls = []

        def mock_callback(spread_signal):
            """Callback now receives only SpreadSignal object (contains pair_symbol)"""
            calls.append({
                'crypto': spread_signal.pair_symbol[0],
                'stock': spread_signal.pair_symbol[1],
                'signal': spread_signal
            })

        # Register observer
        manager.register_observer(mock_callback)

        # Create test data
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # Create a SpreadSignal object
        test_signal = SpreadSignal(
            pair_symbol=pair_symbol,
            market_state=MarketState.CROSSED,
            theoretical_spread=0.05,
            executable_spread=0.04,
            direction="SHORT_SPREAD"
        )

        # Notify observers with SpreadSignal (only signal parameter)
        manager._notify_observers(test_signal)

        # Verify callback was called
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['crypto'], crypto_symbol)
        self.assertEqual(calls[0]['stock'], stock_symbol)

        # Verify SpreadSignal was passed correctly
        received_signal = calls[0]['signal']
        self.assertIsInstance(received_signal, SpreadSignal)
        self.assertEqual(received_signal.market_state, MarketState.CROSSED)
        self.assertAlmostEqual(received_signal.theoretical_spread, 0.05)
        self.assertAlmostEqual(received_signal.executable_spread, 0.04)
        self.assertEqual(received_signal.direction, "SHORT_SPREAD")

        print("Notify observers test passed")

    def test_multiple_observers(self):
        """Test multiple observers receive SpreadSignal notifications"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        calls1 = []
        calls2 = []

        def callback1(spread_signal):
            """First callback receives SpreadSignal"""
            calls1.append(spread_signal)

        def callback2(spread_signal):
            """Second callback receives SpreadSignal"""
            calls2.append(spread_signal)

        # Register two observers
        manager.register_observer(callback1)
        manager.register_observer(callback2)

        # Create test signal
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        test_signal = SpreadSignal(
            pair_symbol=(crypto_symbol, stock_symbol),
            market_state=MarketState.LIMIT_OPPORTUNITY,
            theoretical_spread=0.03,
            executable_spread=None,  # LIMIT_OPPORTUNITY doesn't have executable_spread
            direction="LONG_SPREAD"
        )

        # Notify observers
        manager._notify_observers(test_signal)

        # Verify both callbacks were called
        self.assertEqual(len(calls1), 1)
        self.assertEqual(len(calls2), 1)

        # Verify both received the same SpreadSignal
        self.assertIsInstance(calls1[0], SpreadSignal)
        self.assertIsInstance(calls2[0], SpreadSignal)
        self.assertEqual(calls1[0].market_state, MarketState.LIMIT_OPPORTUNITY)
        self.assertEqual(calls2[0].market_state, MarketState.LIMIT_OPPORTUNITY)
        self.assertAlmostEqual(calls1[0].theoretical_spread, 0.03)
        self.assertAlmostEqual(calls2[0].theoretical_spread, 0.03)

        print("Multiple observers test passed")

    def test_observer_error_handling(self):
        """Test observer error handling (one observer error doesn't affect others)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        calls = []
        error_calls = []

        def broken_callback(spread_signal):
            """Broken callback that raises an error"""
            error_calls.append(spread_signal)
            raise RuntimeError("Test error")

        def working_callback(spread_signal):
            """Working callback that succeeds"""
            calls.append(spread_signal)

        # Register two observers (broken first, then working)
        manager.register_observer(broken_callback)
        manager.register_observer(working_callback)

        # Create test signal
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        test_signal = SpreadSignal(
            pair_symbol=(crypto_symbol, stock_symbol),
            market_state=MarketState.CROSSED,
            theoretical_spread=0.02,
            executable_spread=0.018,
            direction="SHORT_SPREAD"
        )

        # The error should be caught internally and not propagate
        # No exception should be raised to the caller
        manager._notify_observers(test_signal)

        # Verify broken observer was called (before it raised)
        self.assertEqual(len(error_calls), 1)

        # Verify working observer was still called (after broken observer failed)
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], SpreadSignal)
        self.assertAlmostEqual(calls[0].theoretical_spread, 0.02)

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


class TestSpreadManagerAnalyzeSignal(unittest.TestCase):
    """Test new analyze_spread_signal method (两层价差系统)"""

    def test_crossed_market_short_spread(self):
        """Test Crossed Market: token_bid > stock_ask (SHORT_SPREAD)"""
        # Scenario: 可以卖token买stock，立即套利
        token_bid = 150.5
        token_ask = 150.6
        stock_bid = 149.8
        stock_ask = 150.0  # token_bid > stock_ask => Crossed

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Verify market state
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "SHORT_SPREAD")

        # Verify executable spread
        self.assertIsNotNone(result["executable_spread"])
        expected_spread = (token_bid - stock_ask) / token_bid
        self.assertAlmostEqual(result["executable_spread"], expected_spread, places=6)

        # Verify theoretical spread is also calculated
        self.assertIsNotNone(result["theoretical_spread"])

        print("Crossed market SHORT_SPREAD test passed")

    def test_crossed_market_long_spread(self):
        """Test Crossed Market: stock_bid > token_ask (LONG_SPREAD)"""
        # Scenario: 可以买token卖stock，立即套利
        token_bid = 149.8
        token_ask = 150.0
        stock_bid = 150.5  # stock_bid > token_ask => Crossed
        stock_ask = 150.6

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Verify market state
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "LONG_SPREAD")

        # Verify executable spread
        self.assertIsNotNone(result["executable_spread"])
        # For LONG_SPREAD: (token_ask - stock_bid) / token_ask
        expected_spread = (token_ask - stock_bid) / token_ask
        self.assertAlmostEqual(result["executable_spread"], expected_spread, places=6)

        print("Crossed market LONG_SPREAD test passed")

    def test_limit_opportunity_short_spread(self):
        """Test Limit Opportunity: 接近但未交叉的价格 (SHORT_SPREAD)"""
        # Scenario: token_ask > stock_ask > token_bid > stock_bid (LIMIT_OPPORTUNITY)
        token_bid = 150.2
        token_ask = 150.6
        stock_bid = 149.5
        stock_ask = 150.4  # token_ask > stock_ask > token_bid > stock_bid

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should be LIMIT_OPPORTUNITY because prices form the correct interval
        self.assertEqual(result["market_state"], MarketState.LIMIT_OPPORTUNITY)
        self.assertEqual(result["direction"], "SHORT_SPREAD")

        # New feature: LIMIT_OPPORTUNITY now calculates executable_spread
        # For SHORT_SPREAD: max of two spreads
        # spread_1 = (token_ask - stock_ask) / token_ask
        # spread_2 = (token_bid - stock_bid) / token_bid
        spread_1 = (token_ask - stock_ask) / token_ask
        spread_2 = (token_bid - stock_bid) / token_bid
        expected_spread = max(spread_1, spread_2)

        self.assertIsNotNone(result["executable_spread"])
        self.assertAlmostEqual(result["executable_spread"], expected_spread, places=6)

        print("Limit opportunity SHORT_SPREAD test passed")

    def test_no_opportunity(self):
        """Test No Opportunity: 价格区间交错，无套利机会"""
        # Scenario: A_ask > B_ask > B_bid > A_bid
        token_bid = 149.5
        token_ask = 150.5
        stock_bid = 150.0
        stock_ask = 150.2

        # token_bid (149.5) < stock_ask (150.2)：不能 Short token + Long stock
        # stock_bid (150.0) < token_ask (150.5)：不能 Long token + Short stock

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should be NO_OPPORTUNITY
        self.assertEqual(result["market_state"], MarketState.NO_OPPORTUNITY)
        self.assertIsNone(result["executable_spread"])
        self.assertIsNone(result["direction"])

        # Theoretical spread should still be calculated
        self.assertIsNotNone(result["theoretical_spread"])

        print("No opportunity test passed")

    def test_theoretical_spread_always_calculated(self):
        """Test that theoretical spread is always calculated"""
        test_cases = [
            # Crossed Market
            (150.5, 150.6, 149.8, 150.0),
            # Normal Market
            (150.0, 150.1, 149.8, 149.9),
            # No Opportunity
            (149.5, 150.5, 150.0, 150.2),
        ]

        for token_bid, token_ask, stock_bid, stock_ask in test_cases:
            result = SpreadManager.calculate_spread_pct(
                token_bid, token_ask, stock_bid, stock_ask
            )

            # Verify return type is dict
            self.assertIsInstance(result, dict)

            # Theoretical spread should always be calculated
            self.assertIsNotNone(result["theoretical_spread"])

            # Verify calling calculate_spread_pct again returns consistent results
            result2 = SpreadManager.calculate_spread_pct(
                token_bid, token_ask, stock_bid, stock_ask
            )
            self.assertAlmostEqual(result["theoretical_spread"], result2["theoretical_spread"], places=6)

        print("Theoretical spread always calculated test passed")

    def test_signal_contains_price_details(self):
        """Test that result dict contains all necessary spread details"""
        token_bid = 150.5
        token_ask = 150.6
        stock_bid = 149.8
        stock_ask = 150.0

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Verify all required keys are present
        self.assertIn("market_state", result)
        self.assertIn("theoretical_spread", result)
        self.assertIn("executable_spread", result)
        self.assertIn("direction", result)

        print("Signal contains price details test passed")

    def test_crossed_market_tiny_spread(self):
        """Test crossed market with tiny spread (no threshold filtering)"""
        # token_bid > stock_ask, even if spread is tiny
        token_bid = 150.05
        token_ask = 150.1
        stock_bid = 149.9
        stock_ask = 150.0

        # Spread = (150.05 - 150.0) / 150.05 = 0.0333%
        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should be CROSSED because token_bid > stock_ask (no threshold filtering in this layer)
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertIsNotNone(result["executable_spread"])
        # Spread should be positive but small
        self.assertGreater(result["executable_spread"], 0)
        self.assertLess(result["executable_spread"], 0.001)  # < 0.1%

        print("Crossed market tiny spread test passed")

    def test_no_crossed_no_limit(self):
        """Test when prices are close but don't form any opportunity pattern"""
        # Prices that don't match CROSSED or LIMIT_OPPORTUNITY patterns
        # Use overlapping intervals that don't form a clean pattern
        token_bid = 149.8
        token_ask = 150.2
        stock_bid = 149.9
        stock_ask = 150.1

        # Check intervals:
        # token_bid (149.8) < stock_ask (150.1): no CROSSED for SHORT_SPREAD
        # stock_bid (149.9) < token_ask (150.2): no CROSSED for LONG_SPREAD
        # Price interval: token_ask (150.2) > stock_ask (150.1) > stock_bid (149.9) > token_bid (149.8)
        # This doesn't match either LIMIT_OPPORTUNITY pattern:
        #   - Not: token_ask > stock_ask > token_bid > stock_bid (stock_bid > token_bid)
        #   - Not: stock_ask > token_ask > stock_bid > token_bid

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should be NO_OPPORTUNITY (no crossing, no LIMIT interval match)
        self.assertEqual(result["market_state"], MarketState.NO_OPPORTUNITY)
        self.assertIsNone(result["executable_spread"])

        print("No crossed no limit test passed")

    def test_clear_crossed_market(self):
        """Test clear crossed market detection (no threshold filtering)"""
        token_bid = 150.3
        token_ask = 150.4
        stock_bid = 149.8
        stock_ask = 150.0

        # token_bid (150.3) > stock_ask (150.0) => CROSSED
        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should detect CROSSED opportunity (no threshold filtering)
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "SHORT_SPREAD")
        self.assertIsNotNone(result["executable_spread"])
        # Spread should be (150.3 - 150.0) / 150.3 = 0.1996%
        self.assertAlmostEqual(result["executable_spread"], 0.001996, places=5)

        print("Clear crossed market test passed")

    def test_small_crossed_market(self):
        """Test crossed market with small spread"""
        # Prices very close to crossing
        token_bid = 150.08
        token_ask = 150.1
        stock_bid = 149.9
        stock_ask = 150.0

        # token_bid (150.08) > stock_ask (150.0) => CROSSED
        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should be CROSSED because token_bid > stock_ask
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertEqual(result["direction"], "SHORT_SPREAD")
        self.assertIsNotNone(result["executable_spread"])
        # Spread should be (150.08 - 150.0) / 150.08 = 0.0533%
        self.assertGreater(result["executable_spread"], 0)
        self.assertLess(result["executable_spread"], 0.001)

        print("Small crossed market test passed")

    def test_specific_spread_value(self):
        """Test crossed market with specific spread value"""
        # Create scenario where spread is exactly 0.1%
        # (token_bid - stock_ask) / token_bid = 0.001
        # token_bid - stock_ask = 0.001 * token_bid
        # stock_ask = token_bid * (1 - 0.001) = token_bid * 0.999

        token_bid = 150.0
        stock_ask = token_bid * 0.999  # = 149.85
        token_ask = 150.1
        stock_bid = 149.8

        result = SpreadManager.calculate_spread_pct(
            token_bid, token_ask, stock_bid, stock_ask
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should be CROSSED because token_bid > stock_ask
        self.assertEqual(result["market_state"], MarketState.CROSSED)
        self.assertIsNotNone(result["executable_spread"])
        # Spread should be exactly 0.1%
        self.assertAlmostEqual(result["executable_spread"], 0.001, places=5)

        print("Specific spread value test passed")

    def test_both_directions_crossed(self):
        """Test when both SHORT_SPREAD and LONG_SPREAD are crossed (impossible in reality, but test logic)"""
        # This is theoretically impossible (would violate bid/ask ordering),
        # but test that the function chooses one direction
        # In practice, only one direction can be crossed at a time

        # Test SHORT_SPREAD direction
        result1 = SpreadManager.calculate_spread_pct(
            token_bid=150.5,  # > stock_ask
            token_ask=150.6,
            stock_bid=149.8,
            stock_ask=150.0
        )
        self.assertIsInstance(result1, dict)
        self.assertEqual(result1["direction"], "SHORT_SPREAD")

        # Test LONG_SPREAD direction
        result2 = SpreadManager.calculate_spread_pct(
            token_bid=149.8,
            token_ask=150.0,
            stock_bid=150.5,  # > token_ask
            stock_ask=150.6
        )
        self.assertIsInstance(result2, dict)
        self.assertEqual(result2["direction"], "LONG_SPREAD")

        print("Both directions crossed test passed")

    def test_zero_prices_in_signal(self):
        """Test calculate_spread_pct with zero prices (should still return theoretical spread as 0)"""
        result = SpreadManager.calculate_spread_pct(
            token_bid=0.0,
            token_ask=150.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # Verify return type is dict
        self.assertIsInstance(result, dict)

        # Should return NO_OPPORTUNITY with theoretical_spread = 0
        self.assertEqual(result["market_state"], MarketState.NO_OPPORTUNITY)
        self.assertEqual(result["theoretical_spread"], 0.0)
        self.assertIsNone(result["executable_spread"])

        print("Zero prices in signal test passed")


class TestSpreadManagerOnData(unittest.TestCase):
    """
    Test on_data() method behavior

    NOTE: on_data() tests are commented out because they require complex mocking
    of LEAN framework internals (Securities collection, Slice, etc.)

    The core logic (analyze_spread_signal, observer notifications) is thoroughly
    tested in other test classes.

    For integration testing of on_data(), use live/paper trading tests or
    backtesting with actual LEAN framework.
    """

    def test_on_data_logic_via_analyze_spread_signal(self):
        """Test the core logic used by on_data via calculate_spread_pct"""
        # This tests the same logic that on_data() uses internally

        # Test Case 1: Executable opportunity (should trigger observer)
        result1 = SpreadManager.calculate_spread_pct(150.5, 150.6, 149.8, 150.0)
        self.assertIsInstance(result1, dict)
        self.assertIsNotNone(result1["executable_spread"])  # Would notify observers

        # Test Case 2: No opportunity (should NOT trigger observer)
        result2 = SpreadManager.calculate_spread_pct(149.5, 150.5, 150.0, 150.2)
        self.assertIsInstance(result2, dict)
        self.assertIsNone(result2["executable_spread"])  # Would NOT notify observers

        print("on_data logic via calculate_spread_pct test passed")


if __name__ == '__main__':
    print("Running SpreadManager tests...\n")
    unittest.main(verbosity=2)
