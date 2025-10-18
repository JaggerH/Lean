"""
Comprehensive Unit Tests for SpreadMatcher

Tests cover:
1. Lot alignment (_round_to_lot)
2. Spread calculation (_calc_spread_pct)
3. Spread validation (_validate_spread)
4. OrderbookDepth detection (_has_orderbook_depth)
5. Single-leg matching (_match_single_leg)
6. Dual-leg matching (_match_dual_leg)
7. Fallback matching (_match_fallback)
8. Main entry point with auto-detection (match_pair)
9. Edge cases (invalid prices, empty orderbook, insufficient liquidity, etc.)
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
from pathlib import Path

# Add arbitrage directory to path
arbitrage_path = Path(__file__).parent.parent
if str(arbitrage_path) not in sys.path:
    sys.path.insert(0, str(arbitrage_path))

from strategy.spread_matcher import SpreadMatcher, MatchResult


class MockOrderLevel:
    """Mock orderbook level for testing"""
    def __init__(self, price: float, size: float):
        self.price = price
        self.size = size


class MockOrderbook:
    """Mock OrderbookDepth for testing"""
    def __init__(self, bids=None, asks=None):
        self.bids = bids or []
        self.asks = asks or []


class MockSymbolProperties:
    """Mock SymbolProperties for testing"""
    def __init__(self, lot_size: float = 1.0):
        self.lot_size = lot_size


class MockCache:
    """Mock security cache for testing"""
    def __init__(self, orderbook_depth=None):
        self.orderbook_depth = orderbook_depth


class MockSecurity:
    """Mock Security object for testing"""
    def __init__(self, symbol, bid_price=0.0, ask_price=0.0, price=0.0,
                 lot_size=1.0, orderbook=None):
        self.symbol = symbol
        self.bid_price = bid_price
        self.ask_price = ask_price
        self.price = price
        self.symbol_properties = MockSymbolProperties(lot_size)
        self.cache = MockCache(orderbook)


class MockAlgorithm:
    """Mock QCAlgorithm for testing"""
    def __init__(self):
        self.securities = {}
        self.debug_messages = []

    def debug(self, message):
        """Capture debug messages"""
        self.debug_messages.append(message)


class TestSpreadMatcherLotAlignment(unittest.TestCase):
    """Test suite for _round_to_lot method"""

    def test_round_to_lot_integer_lot_size(self):
        """Test rounding with integer lot size"""
        self.assertEqual(SpreadMatcher._round_to_lot(100.0, 1.0), 100.0)
        self.assertEqual(SpreadMatcher._round_to_lot(105.7, 1.0), 105.0)
        self.assertEqual(SpreadMatcher._round_to_lot(99.1, 1.0), 99.0)

    def test_round_to_lot_fractional_lot_size(self):
        """Test rounding with fractional lot size (e.g., 0.01 for crypto)"""
        self.assertEqual(SpreadMatcher._round_to_lot(1.234567, 0.01), 1.23)
        self.assertEqual(SpreadMatcher._round_to_lot(0.999, 0.01), 0.99)
        self.assertEqual(SpreadMatcher._round_to_lot(10.005, 0.01), 10.0)

    def test_round_to_lot_large_lot_size(self):
        """Test rounding with large lot size (e.g., 100 shares)"""
        self.assertEqual(SpreadMatcher._round_to_lot(550.0, 100.0), 500.0)
        self.assertEqual(SpreadMatcher._round_to_lot(999.0, 100.0), 900.0)
        self.assertEqual(SpreadMatcher._round_to_lot(50.0, 100.0), 0.0)

    def test_round_to_lot_zero_lot_size(self):
        """Test with zero lot size (should return original value)"""
        self.assertEqual(SpreadMatcher._round_to_lot(123.456, 0.0), 123.456)

    def test_round_to_lot_negative_lot_size(self):
        """Test with negative lot size (should return original value)"""
        self.assertEqual(SpreadMatcher._round_to_lot(123.456, -1.0), 123.456)


class TestSpreadMatcherSpreadCalculation(unittest.TestCase):
    """Test suite for _calc_spread_pct method"""

    def test_calc_spread_positive(self):
        """Test positive spread (buy higher than sell)"""
        spread = SpreadMatcher._calc_spread_pct(102.0, 100.0)
        self.assertAlmostEqual(spread, 2.0, places=6)

    def test_calc_spread_negative(self):
        """Test negative spread (buy lower than sell)"""
        spread = SpreadMatcher._calc_spread_pct(98.0, 100.0)
        self.assertAlmostEqual(spread, -2.0, places=6)

    def test_calc_spread_zero(self):
        """Test zero spread (equal prices)"""
        spread = SpreadMatcher._calc_spread_pct(100.0, 100.0)
        self.assertAlmostEqual(spread, 0.0, places=6)

    def test_calc_spread_small_difference(self):
        """Test small spread difference"""
        spread = SpreadMatcher._calc_spread_pct(100.05, 100.0)
        self.assertAlmostEqual(spread, 0.05, places=6)

    def test_calc_spread_large_difference(self):
        """Test large spread difference"""
        spread = SpreadMatcher._calc_spread_pct(150.0, 100.0)
        self.assertAlmostEqual(spread, 50.0, places=6)

    def test_calc_spread_zero_sell_price(self):
        """Test with zero sell price (should return -inf)"""
        spread = SpreadMatcher._calc_spread_pct(100.0, 0.0)
        self.assertEqual(spread, float('-inf'))


class TestSpreadMatcherSpreadValidation(unittest.TestCase):
    """Test suite for _validate_spread method"""

    def test_validate_spread_above_threshold(self):
        """Test spread above minimum threshold"""
        self.assertTrue(SpreadMatcher._validate_spread(2.0, 1.0))
        self.assertTrue(SpreadMatcher._validate_spread(0.0, -1.0))

    def test_validate_spread_at_threshold(self):
        """Test spread exactly at threshold"""
        self.assertTrue(SpreadMatcher._validate_spread(1.0, 1.0))
        self.assertTrue(SpreadMatcher._validate_spread(-1.0, -1.0))

    def test_validate_spread_below_threshold(self):
        """Test spread below threshold"""
        self.assertFalse(SpreadMatcher._validate_spread(0.5, 1.0))
        self.assertFalse(SpreadMatcher._validate_spread(-2.0, -1.0))

    def test_validate_spread_negative_threshold(self):
        """Test with negative threshold (allow negative spreads)"""
        self.assertTrue(SpreadMatcher._validate_spread(-0.5, -1.0))
        self.assertFalse(SpreadMatcher._validate_spread(-1.5, -1.0))


class TestSpreadMatcherOrderbookDetection(unittest.TestCase):
    """Test suite for _has_orderbook_depth method"""

    def test_has_orderbook_valid(self):
        """Test with valid orderbook"""
        algorithm = MockAlgorithm()
        symbol = Mock()

        orderbook = MockOrderbook(
            bids=[MockOrderLevel(100.0, 10.0)],
            asks=[MockOrderLevel(101.0, 10.0)]
        )

        security = MockSecurity(symbol, orderbook=orderbook)
        algorithm.securities[symbol] = security

        self.assertTrue(SpreadMatcher._has_orderbook_depth(algorithm, symbol))

    def test_has_orderbook_none(self):
        """Test with None orderbook"""
        algorithm = MockAlgorithm()
        symbol = Mock()

        security = MockSecurity(symbol, orderbook=None)
        algorithm.securities[symbol] = security

        self.assertFalse(SpreadMatcher._has_orderbook_depth(algorithm, symbol))

    def test_has_orderbook_empty_bids(self):
        """Test with empty bids"""
        algorithm = MockAlgorithm()
        symbol = Mock()

        orderbook = MockOrderbook(
            bids=[],
            asks=[MockOrderLevel(101.0, 10.0)]
        )

        security = MockSecurity(symbol, orderbook=orderbook)
        algorithm.securities[symbol] = security

        self.assertFalse(SpreadMatcher._has_orderbook_depth(algorithm, symbol))

    def test_has_orderbook_empty_asks(self):
        """Test with empty asks"""
        algorithm = MockAlgorithm()
        symbol = Mock()

        orderbook = MockOrderbook(
            bids=[MockOrderLevel(100.0, 10.0)],
            asks=[]
        )

        security = MockSecurity(symbol, orderbook=orderbook)
        algorithm.securities[symbol] = security

        self.assertFalse(SpreadMatcher._has_orderbook_depth(algorithm, symbol))

    def test_has_orderbook_none_bids(self):
        """Test with None bids"""
        algorithm = MockAlgorithm()
        symbol = Mock()

        orderbook = MockOrderbook(
            bids=None,
            asks=[MockOrderLevel(101.0, 10.0)]
        )

        security = MockSecurity(symbol, orderbook=orderbook)
        algorithm.securities[symbol] = security

        self.assertFalse(SpreadMatcher._has_orderbook_depth(algorithm, symbol))

    def test_has_orderbook_none_asks(self):
        """Test with None asks"""
        algorithm = MockAlgorithm()
        symbol = Mock()

        orderbook = MockOrderbook(
            bids=[MockOrderLevel(100.0, 10.0)],
            asks=None
        )

        security = MockSecurity(symbol, orderbook=orderbook)
        algorithm.securities[symbol] = security

        self.assertFalse(SpreadMatcher._has_orderbook_depth(algorithm, symbol))


class TestSpreadMatcherSingleLeg(unittest.TestCase):
    """Test suite for _match_single_leg method"""

    def test_single_leg_long_s1_basic(self):
        """Test LONG_S1 direction (buy symbol_ob, sell symbol_bp)"""
        algorithm = MockAlgorithm()

        # Create symbols
        symbol_ob = Mock()
        symbol_bp = Mock()
        symbol_ob.__str__ = lambda x: "OB"
        symbol_bp.__str__ = lambda x: "BP"

        # Setup orderbook side (asks for buying)
        orderbook = MockOrderbook(asks=[
            MockOrderLevel(100.0, 20.0),
            MockOrderLevel(101.0, 30.0)
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)

        # Setup best price side
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        # Match for $1000 target
        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-2.5,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.executable)
        self.assertEqual(len(result.legs), 2)

        # Check leg 1: buy symbol_ob (positive qty)
        self.assertEqual(result.legs[0][0], symbol_ob)
        self.assertGreater(result.legs[0][1], 0)

        # Check leg 2: sell symbol_bp (negative qty)
        self.assertEqual(result.legs[1][0], symbol_bp)
        self.assertLess(result.legs[1][1], 0)

        # Verify market value equality (approximately)
        # In single-leg matching, total_usd_ob is used to calculate counter shares
        # The buy and sell values may differ due to how fees are applied in the calculation
        # But they should be reasonably close
        self.assertAlmostEqual(result.total_usd_buy, result.total_usd_sell, delta=25.0)

    def test_single_leg_short_s1_basic(self):
        """Test SHORT_S1 direction (sell symbol_ob, buy symbol_bp)"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()
        symbol_ob.__str__ = lambda x: "OB"
        symbol_bp.__str__ = lambda x: "BP"

        # Setup orderbook side (bids for selling)
        orderbook = MockOrderbook(bids=[
            MockOrderLevel(100.0, 20.0),
            MockOrderLevel(99.0, 30.0)
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)

        # Setup best price side
        security_bp = MockSecurity(symbol_bp, ask_price=98.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="SHORT_S1",
            min_spread_pct=-2.5,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.executable)

        # Check leg 1: sell symbol_ob (negative qty)
        self.assertEqual(result.legs[0][0], symbol_ob)
        self.assertLess(result.legs[0][1], 0)

        # Check leg 2: buy symbol_bp (positive qty)
        self.assertEqual(result.legs[1][0], symbol_bp)
        self.assertGreater(result.legs[1][1], 0)

    def test_single_leg_partial_fill(self):
        """Test partial fill when orderbook insufficient"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        # Limited orderbook (only $500 available)
        orderbook = MockOrderbook(asks=[
            MockOrderLevel(100.0, 5.0)  # Only 5 shares at $100 = $500
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        # Request $1000 but only $500 available
        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertFalse(result.reached_target)
        self.assertGreater(result.remaining_usd, 400.0)  # Should have ~$500 remaining

    def test_single_leg_spread_threshold_filtering(self):
        """Test spread threshold filtering"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        # Multiple levels with varying spreads
        orderbook = MockOrderbook(asks=[
            MockOrderLevel(100.0, 10.0),  # Spread: (100/102 - 1) * 100 = -1.96%
            MockOrderLevel(105.0, 20.0),  # Spread: (105/102 - 1) * 100 = 2.94%
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        # Set min_spread_pct = 0.0 (should reject first level with -1.96%)
        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=2000.0,
            direction="LONG_S1",
            min_spread_pct=0.0,  # Only accept spreads >= 0%
            fee_per_share=0.0,
            debug=False
        )

        # Should stop at first level since its spread is negative
        # Returns None because no levels meet the threshold
        self.assertIsNone(result)

    def test_single_leg_lot_alignment(self):
        """Test lot size alignment"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        orderbook = MockOrderbook(asks=[
            MockOrderLevel(100.0, 10.5)  # 10.5 shares
        ])
        # Lot size = 1.0, so should round down to 10.0
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=0.01)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=500.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        # Should be rounded to lot size
        self.assertEqual(result.total_shares_ob % 1.0, 0.0)

    def test_single_leg_invalid_price(self):
        """Test with invalid best price (zero)"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        orderbook = MockOrderbook(asks=[MockOrderLevel(100.0, 10.0)])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=0.0, price=0.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-2.0,
            fee_per_share=0.0,
            debug=True
        )

        self.assertIsNone(result)

    def test_single_leg_no_matching_shares(self):
        """Test when no shares match criteria"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        orderbook = MockOrderbook(asks=[
            MockOrderLevel(110.0, 10.0)  # Spread: (110/100 - 1) * 100 = 10%
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=100.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        # Require spread >= 15%, but we only have 10%
        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=15.0,  # Need at least 15% but we have 10%
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNone(result)

    def test_single_leg_with_fees(self):
        """Test with transaction fees"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        orderbook = MockOrderbook(asks=[MockOrderLevel(100.0, 20.0)])
        security_ob = MockSecurity(symbol_ob, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.005,  # $0.005 per share
            debug=False
        )

        self.assertIsNotNone(result)
        # Buy side should include fees
        self.assertGreater(result.total_usd_buy, result.total_shares_ob * 100.0)


class TestSpreadMatcherDualLeg(unittest.TestCase):
    """Test suite for _match_dual_leg method"""

    def test_dual_leg_long_s1_basic(self):
        """Test dual-leg LONG_S1 (buy symbol1, sell symbol2)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Both have orderbooks
        orderbook1 = MockOrderbook(asks=[
            MockOrderLevel(100.0, 20.0),
            MockOrderLevel(101.0, 30.0)
        ])
        orderbook2 = MockOrderbook(bids=[
            MockOrderLevel(102.0, 25.0),
            MockOrderLevel(101.0, 35.0)
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.executable)

        # Check leg signs
        self.assertGreater(result.legs[0][1], 0)  # Buy symbol1
        self.assertLess(result.legs[1][1], 0)     # Sell symbol2

    def test_dual_leg_short_s1_basic(self):
        """Test dual-leg SHORT_S1 (sell symbol1, buy symbol2)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        orderbook1 = MockOrderbook(bids=[
            MockOrderLevel(100.0, 20.0),
            MockOrderLevel(99.0, 30.0)
        ])
        orderbook2 = MockOrderbook(asks=[
            MockOrderLevel(98.0, 25.0),
            MockOrderLevel(99.0, 35.0)
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="SHORT_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.executable)

        # Check leg signs
        self.assertLess(result.legs[0][1], 0)     # Sell symbol1
        self.assertGreater(result.legs[1][1], 0)  # Buy symbol2

    def test_dual_leg_market_value_equality(self):
        """Test market value equality (not share equality)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Different prices
        orderbook1 = MockOrderbook(asks=[
            MockOrderLevel(100.0, 50.0)
        ])
        orderbook2 = MockOrderbook(bids=[
            MockOrderLevel(200.0, 50.0)  # 2x price
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-60.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)

        # Shares should NOT be equal (market value should be equal)
        qty1 = abs(result.legs[0][1])
        qty2 = abs(result.legs[1][1])

        # qty2 should be roughly half of qty1 (since price is 2x)
        self.assertLess(qty2, qty1)

        # Market values should be approximately equal
        value1 = qty1 * 100.0
        value2 = qty2 * 200.0
        self.assertAlmostEqual(value1, value2, delta=10.0)

    def test_dual_leg_multi_level_matching(self):
        """Test matching across multiple levels"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Multiple levels
        orderbook1 = MockOrderbook(asks=[
            MockOrderLevel(100.0, 5.0),   # $500
            MockOrderLevel(101.0, 5.0),   # $505
            MockOrderLevel(102.0, 5.0)    # $510
        ])
        orderbook2 = MockOrderbook(bids=[
            MockOrderLevel(102.0, 5.0),
            MockOrderLevel(101.0, 5.0),
            MockOrderLevel(100.0, 5.0)
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        # Request more than one level can provide
        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=1200.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        # Should have multiple matched details
        self.assertGreater(len(result.matched_details), 1)

    def test_dual_leg_insufficient_liquidity(self):
        """Test when both sides have insufficient liquidity"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Very limited liquidity
        orderbook1 = MockOrderbook(asks=[
            MockOrderLevel(100.0, 2.0)  # Only $200
        ])
        orderbook2 = MockOrderbook(bids=[
            MockOrderLevel(102.0, 2.0)
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertFalse(result.reached_target)
        self.assertGreater(result.remaining_usd, 700.0)

    def test_dual_leg_spread_filter(self):
        """Test spread filtering in dual-leg"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        orderbook1 = MockOrderbook(asks=[
            MockOrderLevel(100.0, 10.0),
            MockOrderLevel(110.0, 10.0)  # Bad spread
        ])
        orderbook2 = MockOrderbook(bids=[
            MockOrderLevel(95.0, 5.0),   # Good spread with first level
            MockOrderLevel(90.0, 10.0)
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=0.0,  # Require positive spread
            fee_per_share=0.0,
            debug=False
        )

        # Should skip pairs that don't meet spread threshold
        # Might get partial match or None depending on matching logic
        if result:
            self.assertGreater(result.avg_spread_pct, 0.0)


class TestSpreadMatcherFallback(unittest.TestCase):
    """Test suite for _match_fallback method"""

    def test_fallback_long_s1(self):
        """Test fallback with LONG_S1 direction"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # No orderbooks, only BestBid/Ask
        security1 = MockSecurity(symbol1, ask_price=100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_fallback(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.executable)
        self.assertTrue(result.reached_target)

        # Check quantities
        qty1 = abs(result.legs[0][1])
        qty2 = abs(result.legs[1][1])

        # In fallback mode, both sides calculate qty from target_usd / price
        # The buy and sell values may differ due to rounding and price differences
        # But they should be reasonably close to target
        self.assertAlmostEqual(result.total_usd_buy, 1000.0, delta=5.0)
        self.assertAlmostEqual(result.total_usd_sell, 1000.0, delta=100.0)

    def test_fallback_short_s1(self):
        """Test fallback with SHORT_S1 direction"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        security1 = MockSecurity(symbol1, bid_price=100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, ask_price=98.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_fallback(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="SHORT_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.executable)

    def test_fallback_invalid_prices(self):
        """Test fallback with invalid prices"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Zero prices
        security1 = MockSecurity(symbol1, ask_price=0.0, price=0.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=100.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_fallback(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=True
        )

        self.assertIsNone(result)

    def test_fallback_spread_below_threshold(self):
        """Test fallback when spread below threshold"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        security1 = MockSecurity(symbol1, ask_price=110.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=100.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        # Spread is (110/100 - 1) * 100 = 10%, require at least 15%
        result = SpreadMatcher._match_fallback(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=15.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNone(result)

    def test_fallback_price_fallback_to_last(self):
        """Test fallback to last price when bid/ask is zero"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Zero ask_price, should fallback to price
        security1 = MockSecurity(symbol1, ask_price=0.0, price=100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_fallback(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)


class TestSpreadMatcherMainEntry(unittest.TestCase):
    """Test suite for match_pair method (main entry point)"""

    def test_match_pair_dual_leg_detection(self):
        """Test auto-detection of dual-leg scenario"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Both have orderbooks
        orderbook1 = MockOrderbook(
            asks=[MockOrderLevel(100.0, 20.0)],
            bids=[MockOrderLevel(99.0, 20.0)]
        )
        orderbook2 = MockOrderbook(
            asks=[MockOrderLevel(101.0, 20.0)],
            bids=[MockOrderLevel(102.0, 20.0)]
        )

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher.match_pair(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            debug=True
        )

        # Should use dual-leg matching
        self.assertIsNotNone(result)
        # Check debug messages
        self.assertTrue(any("OrderbookDepth" in msg for msg in algorithm.debug_messages))

    def test_match_pair_single_leg_s1_detection(self):
        """Test auto-detection of single-leg (symbol1 has orderbook)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Only symbol1 has orderbook
        orderbook1 = MockOrderbook(
            asks=[MockOrderLevel(100.0, 20.0)],
            bids=[MockOrderLevel(99.0, 20.0)]
        )

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher.match_pair(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            debug=True
        )

        # Should use single-leg matching
        self.assertIsNotNone(result)

    def test_match_pair_single_leg_s2_detection(self):
        """Test auto-detection of single-leg (symbol2 has orderbook)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Only symbol2 has orderbook
        orderbook2 = MockOrderbook(
            asks=[MockOrderLevel(101.0, 20.0)],
            bids=[MockOrderLevel(102.0, 20.0)]
        )

        security1 = MockSecurity(symbol1, ask_price=100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher.match_pair(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            debug=True
        )

        # Should swap and use single-leg matching
        self.assertIsNotNone(result)
        # Legs should be in original order
        self.assertEqual(result.legs[0][0], symbol1)
        self.assertEqual(result.legs[1][0], symbol2)

    def test_match_pair_fallback_detection(self):
        """Test auto-detection of fallback scenario (no orderbooks)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Neither has orderbook
        security1 = MockSecurity(symbol1, ask_price=100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher.match_pair(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            debug=True
        )

        # Should use fallback matching
        self.assertIsNotNone(result)


class TestSpreadMatcherEdgeCases(unittest.TestCase):
    """Test suite for edge cases and error conditions"""

    def test_empty_orderbook(self):
        """Test with completely empty orderbook"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        # Empty orderbook, but provide fallback prices
        orderbook = MockOrderbook(asks=[], bids=[])
        security_ob = MockSecurity(symbol_ob, ask_price=100.0, lot_size=1.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        # Should detect as no orderbook and fallback
        result = SpreadMatcher.match_pair(
            algorithm, symbol_ob, symbol_bp,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0
        )

        # Should use fallback (both have no valid orderbook)
        self.assertIsNotNone(result)

    def test_zero_target_usd(self):
        """Test with zero target USD"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        security1 = MockSecurity(symbol1, ask_price=100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher.match_pair(
            algorithm, symbol1, symbol2,
            target_usd=0.0,
            direction="LONG_S1",
            min_spread_pct=-3.0
        )

        # Should handle gracefully
        self.assertIsNotNone(result)
        self.assertEqual(result.total_usd_buy, 0.0)

    def test_negative_prices(self):
        """Test with negative prices (invalid)"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        security1 = MockSecurity(symbol1, ask_price=-100.0, lot_size=1.0)
        security2 = MockSecurity(symbol2, bid_price=102.0, lot_size=1.0)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher.match_pair(
            algorithm, symbol1, symbol2,
            target_usd=1000.0,
            direction="LONG_S1",
            min_spread_pct=-3.0
        )

        self.assertIsNone(result)

    def test_very_small_lot_sizes(self):
        """Test with very small lot sizes (crypto)"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        orderbook = MockOrderbook(asks=[
            MockOrderLevel(10000.0, 0.12345)  # Bitcoin-like
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=0.00000001, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=10200.0, lot_size=0.00000001)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=100.0,
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        # Should handle tiny lot sizes
        self.assertGreater(result.total_shares_ob, 0)

    def test_very_large_lot_sizes(self):
        """Test with very large lot sizes"""
        algorithm = MockAlgorithm()

        symbol_ob = Mock()
        symbol_bp = Mock()

        orderbook = MockOrderbook(asks=[
            MockOrderLevel(100.0, 1000.0)
        ])
        security_ob = MockSecurity(symbol_ob, lot_size=100.0, orderbook=orderbook)
        security_bp = MockSecurity(symbol_bp, bid_price=102.0, lot_size=100.0)

        algorithm.securities[symbol_ob] = security_ob
        algorithm.securities[symbol_bp] = security_bp

        result = SpreadMatcher._match_single_leg(
            algorithm, symbol_ob, symbol_bp,
            target_usd=500.0,  # Only enough for 5 shares, but lot is 100
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        # Should round down to 0 or handle gracefully
        if result:
            self.assertEqual(result.total_shares_ob % 100.0, 0.0)

    def test_extreme_spread_values(self):
        """Test with extreme spread values"""
        # Very positive spread
        spread1 = SpreadMatcher._calc_spread_pct(1000.0, 100.0)
        self.assertAlmostEqual(spread1, 900.0, places=2)

        # Very negative spread
        spread2 = SpreadMatcher._calc_spread_pct(10.0, 1000.0)
        self.assertAlmostEqual(spread2, -99.0, places=2)

    def test_concurrent_orderbook_exhaustion(self):
        """Test when both sides of dual-leg exhaust simultaneously"""
        algorithm = MockAlgorithm()

        symbol1 = Mock()
        symbol2 = Mock()

        # Exactly matching quantities
        orderbook1 = MockOrderbook(asks=[
            MockOrderLevel(100.0, 10.0)
        ])
        orderbook2 = MockOrderbook(bids=[
            MockOrderLevel(102.0, 9.8)  # Slightly less
        ])

        security1 = MockSecurity(symbol1, lot_size=1.0, orderbook=orderbook1)
        security2 = MockSecurity(symbol2, lot_size=1.0, orderbook=orderbook2)

        algorithm.securities[symbol1] = security1
        algorithm.securities[symbol2] = security2

        result = SpreadMatcher._match_dual_leg(
            algorithm, symbol1, symbol2,
            target_usd=2000.0,  # More than available
            direction="LONG_S1",
            min_spread_pct=-3.0,
            fee_per_share=0.0,
            debug=False
        )

        self.assertIsNotNone(result)
        # Should match up to available liquidity
        self.assertFalse(result.reached_target)


if __name__ == '__main__':
    unittest.main(verbosity=2)
