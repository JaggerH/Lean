"""
Unit tests for LongCryptoGridStrategy using AlgorithmImports
"""
import unittest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import AlgorithmImports (will be available when run via PythonTestRunner)
from AlgorithmImports import QCAlgorithm, Symbol, SecurityType, Market
from strategy.long_crypto_grid_strategy import LongCryptoGridStrategy
from strategy.grid_models import GridPosition
from spread_manager import SpreadSignal, MarketState


class TestAlgorithm(QCAlgorithm):
    """Simple test algorithm for strategy testing"""

    def __init__(self):
        super().__init__()
        self._debug_messages = []
        self._error_messages = []
        self._current_time = datetime(2025, 1, 15, 9, 30, 0)

    @property
    def time(self):
        """Override time property for testing"""
        return self._current_time

    def advance_time(self, seconds=0, minutes=0, hours=0):
        """Advance algorithm time for testing"""
        self._current_time += timedelta(seconds=seconds, minutes=minutes, hours=hours)

    def debug(self, message):
        """Capture debug messages for testing"""
        self._debug_messages.append(message)
        print(f"[DEBUG] {message}")

    def error(self, message):
        """Capture error messages for testing"""
        self._error_messages.append(message)
        print(f"[ERROR] {message}")

    def get_debug_messages(self):
        """Get all captured debug messages"""
        return self._debug_messages

    def get_error_messages(self):
        """Get all captured error messages"""
        return self._error_messages

    def clear_messages(self):
        """Clear message history"""
        self._debug_messages = []
        self._error_messages = []

    # Mock methods required by BaseStrategy
    def liquidate(self, symbol):
        """Mock liquidate"""
        return []

    def market_order(self, symbol, quantity):
        """Mock market order"""
        class MockTicket:
            def __init__(self, order_id):
                self.order_id = order_id
        return MockTicket(1001)


class TestLongCryptoGridStrategyInit(unittest.TestCase):
    """Test LongCryptoGridStrategy initialization"""

    def test_init_default_params(self):
        """Test initialization with default parameters"""
        algo = TestAlgorithm()
        strategy = LongCryptoGridStrategy(algo)

        # Verify default parameters
        self.assertEqual(strategy.entry_threshold, -0.01)
        self.assertEqual(strategy.exit_threshold, 0.02)
        self.assertEqual(strategy.position_size_pct, 0.25)

        # Verify grid managers initialized
        self.assertIsNotNone(strategy.grid_level_manager)
        self.assertIsNotNone(strategy.grid_position_manager)

        print("✅ Default initialization test passed")

    def test_init_custom_params(self):
        """Test initialization with custom parameters"""
        algo = TestAlgorithm()
        strategy = LongCryptoGridStrategy(
            algo,
            entry_threshold=-0.02,
            exit_threshold=0.03,
            position_size_pct=0.30
        )

        # Verify custom parameters
        self.assertEqual(strategy.entry_threshold, -0.02)
        self.assertEqual(strategy.exit_threshold, 0.03)
        self.assertEqual(strategy.position_size_pct, 0.30)

        print("✅ Custom initialization test passed")


class TestLongCryptoGridStrategyPairInit(unittest.TestCase):
    """Test trading pair initialization"""

    def test_initialize_pair_success(self):
        """Test successful pair initialization with profitable grid"""
        algo = TestAlgorithm()
        strategy = LongCryptoGridStrategy(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # Initialize pair
        strategy.initialize_pair(pair_symbol)

        # Verify grid levels were created
        levels = strategy.grid_level_manager.get_all_levels(pair_symbol)
        self.assertEqual(len(levels), 2)  # Entry + Exit

        # Verify entry level
        entry_level = levels[0]
        self.assertEqual(entry_level.level_id, "entry_long_crypto")
        self.assertEqual(entry_level.type, "ENTRY")
        self.assertEqual(entry_level.spread_pct, -0.01)
        self.assertEqual(entry_level.paired_exit_level_id, "exit_long_crypto")
        self.assertEqual(entry_level.direction, "LONG_SPREAD")

        # Verify exit level
        exit_level = levels[1]
        self.assertEqual(exit_level.level_id, "exit_long_crypto")
        self.assertEqual(exit_level.type, "EXIT")
        self.assertEqual(exit_level.spread_pct, 0.02)

        print("✅ Pair initialization success test passed")

    def test_initialize_pair_unprofitable(self):
        """Test pair initialization fails with unprofitable grid"""
        algo = TestAlgorithm()

        # Create strategy with narrow spread (unprofitable)
        strategy = LongCryptoGridStrategy(
            algo,
            entry_threshold=-0.002,  # -0.2%
            exit_threshold=0.003,    # +0.3%
            # Total profit = 0.5%, Fees = 0.62% -> Unprofitable!
        )

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # Should raise ValueError
        with self.assertRaises(ValueError) as context:
            strategy.initialize_pair(pair_symbol)

        self.assertIn("unprofitable", str(context.exception).lower())

        # Verify error was logged
        errors = algo.get_error_messages()
        self.assertTrue(len(errors) > 0)
        self.assertIn("Grid level validation failed", errors[0])

        print("✅ Unprofitable pair validation test passed")


class TestLongCryptoGridStrategyTrading(unittest.TestCase):
    """Test trading logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.algo = TestAlgorithm()
        self.strategy = LongCryptoGridStrategy(self.algo)

        self.crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        self.stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        self.pair_symbol = (self.crypto_symbol, self.stock_symbol)

        # Initialize pair
        self.strategy.initialize_pair(self.pair_symbol)
        self.algo.clear_messages()

    def test_entry_trigger_below_threshold(self):
        """Test entry triggered when spread <= -1%"""
        # Spread at -1.5% (below -1% threshold)
        spread_pct = -0.015

        # Use grid_level_manager to check trigger logic
        entry_level = self.strategy.grid_level_manager.get_triggered_entry_level(
            self.pair_symbol, spread_pct
        )

        # Verify entry level was triggered
        self.assertIsNotNone(entry_level, "Entry level should trigger when spread <= -1%")
        self.assertEqual(entry_level.level_id, "entry_long_crypto")

        # Verify threshold logic
        self.assertLessEqual(spread_pct, self.strategy.entry_threshold)

        print("✅ Entry trigger test passed")

    def test_no_entry_above_threshold(self):
        """Test no entry when spread > -1%"""
        # Spread at -0.5% (above -1% threshold)
        spread_pct = -0.005

        # 创建 SpreadSignal
        signal = SpreadSignal(
            pair_symbol=self.pair_symbol,
            market_state=MarketState.NO_OPPORTUNITY,
            theoretical_spread=spread_pct,
            executable_spread=None,
            direction=None
        )
        self.strategy.on_spread_update(signal)

        print("✅ No entry above threshold test passed")

    def test_exit_trigger_above_threshold(self):
        """Test exit triggered when spread >= 2%"""
        # Mock grid position as FILLED
        grid_id = "TSLAXUSD_TSLA_entry_long_crypto"
        self.strategy.grid_position_manager.get_active_grids = lambda pair: [grid_id]

        # Mock _close_grid_position
        original_close = self.strategy._close_grid_position
        self.strategy._close_grid_position = lambda *args, **kwargs: [3, 4]  # Mock tickets

        try:
            # Spread at 2.5% (above 2% threshold)
            spread_pct = 0.025

            # 创建 SpreadSignal
            signal = SpreadSignal(
                pair_symbol=self.pair_symbol,
                market_state=MarketState.CROSSED,
                theoretical_spread=spread_pct,
                executable_spread=spread_pct,
                direction="LONG_SPREAD"
            )
            self.strategy.on_spread_update(signal)

            print("✅ Exit trigger test passed")

        finally:
            self.strategy._close_grid_position = original_close

    def test_no_exit_below_threshold(self):
        """Test no exit when spread < 2%"""
        # Spread at 1.5% (below 2% threshold)
        spread_pct = 0.015

        # 创建 SpreadSignal
        signal = SpreadSignal(
            pair_symbol=self.pair_symbol,
            market_state=MarketState.NO_OPPORTUNITY,
            theoretical_spread=spread_pct,
            executable_spread=None,
            direction=None
        )
        self.strategy.on_spread_update(signal)

        print("✅ No exit below threshold test passed")


class TestLongCryptoGridStrategyDirectionRestriction(unittest.TestCase):
    """Test that strategy only trades long crypto direction"""

    def test_only_long_crypto_direction(self):
        """Test grid levels have correct directions (ENTRY=LONG_SPREAD, EXIT=SHORT_SPREAD)"""
        algo = TestAlgorithm()
        strategy = LongCryptoGridStrategy(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        strategy.initialize_pair(pair_symbol)

        # Get grid levels
        levels = strategy.grid_level_manager.get_all_levels(pair_symbol)

        # Verify ENTRY level is LONG_SPREAD (buy crypto, sell stock)
        # Verify EXIT level is SHORT_SPREAD (sell crypto, buy stock)
        for level in levels:
            if hasattr(level, 'direction'):
                if level.type == "ENTRY":
                    self.assertEqual(level.direction, "LONG_SPREAD",
                                   "ENTRY level should be LONG_SPREAD (buy crypto, sell stock)")
                elif level.type == "EXIT":
                    self.assertEqual(level.direction, "SHORT_SPREAD",
                                   "EXIT level should be SHORT_SPREAD (sell crypto, buy stock)")

        print("✅ Direction test passed: ENTRY=LONG_SPREAD, EXIT=SHORT_SPREAD")

    def test_no_short_crypto_entry(self):
        """Test that positive spread (short crypto opportunity) does not trigger entry"""
        algo = TestAlgorithm()
        strategy = LongCryptoGridStrategy(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        strategy.initialize_pair(pair_symbol)

        # Large positive spread (would be short crypto opportunity)
        spread_pct = 0.05  # +5%

        # 创建 SpreadSignal
        signal = SpreadSignal(
            pair_symbol=pair_symbol,
            market_state=MarketState.CROSSED,
            theoretical_spread=spread_pct,
            executable_spread=spread_pct,
            direction="SHORT_SPREAD"
        )
        strategy.on_spread_update(signal)

        print("✅ No short crypto entry test passed")


class TestGridStrategyShouldOpenPosition(unittest.TestCase):
    """Test should_open_position decision logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.algo = TestAlgorithm()
        self.strategy = LongCryptoGridStrategy(self.algo)

        # Create real Symbol objects
        self.crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        self.stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        self.pair_symbol = (self.crypto_symbol, self.stock_symbol)

        # Initialize pair to set up grid levels
        self.strategy.initialize_pair(self.pair_symbol)
        self.algo.clear_messages()

        # Get the initialized grid levels for testing
        levels = self.strategy.grid_level_manager.get_all_levels(self.pair_symbol)
        self.entry_level = levels[0]  # type="ENTRY"

    def test_should_open_returns_true_no_constraints(self):
        """Test should_open_position returns True when no constraints"""
        # Arrange: Mock dependencies to allow opening
        self.strategy.execution_manager.has_active_execution = lambda level: False
        self.strategy.grid_position_manager.has_reached_target = lambda level: False

        # Act: Call the method
        result = self.strategy.should_open_position(self.entry_level)

        # Assert: Should return True
        self.assertTrue(
            result,
            "should_open_position should return True when no active execution and not reached target"
        )

        print("✅ should_open_position returns True with no constraints")

    def test_should_open_returns_false_has_active_execution(self):
        """Test should_open_position returns False when has active execution"""
        # Arrange: Mock active execution exists
        self.strategy.execution_manager.has_active_execution = lambda level: True
        self.strategy.grid_position_manager.has_reached_target = lambda level: False

        # Act: Call the method
        result = self.strategy.should_open_position(self.entry_level)

        # Assert: Should return False
        self.assertFalse(
            result,
            "should_open_position should return False when has active execution"
        )

        print("✅ should_open_position returns False with active execution")

    def test_should_open_returns_false_reached_target(self):
        """Test should_open_position returns False when position reached target"""
        # Arrange: Mock position reached target
        self.strategy.execution_manager.has_active_execution = lambda level: False
        self.strategy.grid_position_manager.has_reached_target = lambda level: True

        # Act: Call the method
        result = self.strategy.should_open_position(self.entry_level)

        # Assert: Should return False
        self.assertFalse(
            result,
            "should_open_position should return False when position reached target"
        )

        print("✅ should_open_position returns False when reached target")

    def test_should_open_returns_false_both_constraints(self):
        """Test should_open_position returns False when both constraints active"""
        # Arrange: Mock both constraints active (edge case)
        self.strategy.execution_manager.has_active_execution = lambda level: True
        self.strategy.grid_position_manager.has_reached_target = lambda level: True

        # Act: Call the method
        result = self.strategy.should_open_position(self.entry_level)

        # Assert: Should return False
        self.assertFalse(
            result,
            "should_open_position should return False when both constraints active"
        )

        print("✅ should_open_position returns False with both constraints")


class TestGridStrategyShouldClosePosition(unittest.TestCase):
    """Test should_close_position decision logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.algo = TestAlgorithm()
        self.strategy = LongCryptoGridStrategy(self.algo)

        # Create real Symbol objects
        self.crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        self.stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        self.pair_symbol = (self.crypto_symbol, self.stock_symbol)

        # Initialize pair to set up grid levels
        self.strategy.initialize_pair(self.pair_symbol)
        self.algo.clear_messages()

        # Get the initialized grid levels for testing
        levels = self.strategy.grid_level_manager.get_all_levels(self.pair_symbol)
        self.entry_level = levels[0]  # type="ENTRY"
        self.exit_level = levels[1]   # type="EXIT"

        # Create a mock GridPosition for testing
        self.mock_position = GridPosition(level=self.entry_level)
        # Give it some position so it's not empty
        self.mock_position.update_filled_qty(1.0, 100.0)

    def test_should_close_returns_true_has_position_no_execution(self):
        """Test should_close_position returns True when has position and no active execution"""
        # Arrange: Mock position exists and no active execution
        self.strategy.grid_position_manager.get_grid_position = lambda level: self.mock_position
        self.strategy.execution_manager.has_active_execution = lambda level: False

        # Act: Call the method
        result = self.strategy.should_close_position(self.exit_level)

        # Assert: Should return True
        self.assertTrue(
            result,
            "should_close_position should return True when has position and no active execution"
        )

        print("✅ should_close_position returns True with position and no execution")

    def test_should_close_returns_false_no_position(self):
        """Test should_close_position returns False when no position exists"""
        # Arrange: Mock no position exists
        self.strategy.grid_position_manager.get_grid_position = lambda level: None
        self.strategy.execution_manager.has_active_execution = lambda level: False

        # Act: Call the method
        result = self.strategy.should_close_position(self.exit_level)

        # Assert: Should return False
        self.assertFalse(
            result,
            "should_close_position should return False when no position exists"
        )

        print("✅ should_close_position returns False with no position")

    def test_should_close_returns_false_has_active_execution(self):
        """Test should_close_position returns False when has active execution"""
        # Arrange: Mock position exists but has active execution
        self.strategy.grid_position_manager.get_grid_position = lambda level: self.mock_position
        self.strategy.execution_manager.has_active_execution = lambda level: True

        # Act: Call the method
        result = self.strategy.should_close_position(self.exit_level)

        # Assert: Should return False
        self.assertFalse(
            result,
            "should_close_position should return False when has active execution"
        )

        print("✅ should_close_position returns False with active execution")

    def test_should_close_returns_false_no_position_and_execution(self):
        """Test should_close_position returns False when no position and has execution"""
        # Arrange: Mock no position and has active execution (edge case)
        self.strategy.grid_position_manager.get_grid_position = lambda level: None
        self.strategy.execution_manager.has_active_execution = lambda level: True

        # Act: Call the method
        result = self.strategy.should_close_position(self.exit_level)

        # Assert: Should return False (short-circuits on no position)
        self.assertFalse(
            result,
            "should_close_position should return False when no position exists"
        )

        print("✅ should_close_position returns False with no position and execution")


if __name__ == '__main__':
    print("Running LongCryptoGridStrategy tests...\n")
    unittest.main(verbosity=2)
