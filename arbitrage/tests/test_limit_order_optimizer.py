"""
Unit tests for LimitOrderOptimizer
"""
import unittest
import sys
from pathlib import Path

# Add parent directory to path to import limit_order_optimizer
sys.path.insert(0, str(Path(__file__).parent.parent))

from limit_order_optimizer import LimitOrderOptimizer


class TestLimitOrderOptimizer(unittest.TestCase):
    """Test cases for LimitOrderOptimizer class"""

    def test_calculate_buy_limit_price_default(self):
        """测试固定激进度(0.6)的买入价格计算"""
        best_bid = 100.0
        best_ask = 101.0

        result = LimitOrderOptimizer.calculate_buy_limit_price(best_bid, best_ask)

        # spread = 1.0, aggression = 0.6
        # expected = 100.0 + 1.0 * 0.6 = 100.6
        self.assertAlmostEqual(result, 100.6, places=6)

    def test_calculate_sell_limit_price_default(self):
        """测试固定激进度(0.6)的卖出价格计算"""
        best_bid = 100.0
        best_ask = 101.0

        result = LimitOrderOptimizer.calculate_sell_limit_price(best_bid, best_ask)

        # spread = 1.0, aggression = 0.6
        # expected = 101.0 - 1.0 * 0.6 = 100.4
        self.assertAlmostEqual(result, 100.4, places=6)

    def test_tight_spread(self):
        """测试窄价差的情况"""
        best_bid = 100.00
        best_ask = 100.01

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # spread = 0.01, aggression = 0.6
        # buy = 100.00 + 0.01 * 0.6 = 100.006
        # sell = 100.01 - 0.01 * 0.6 = 100.004
        self.assertAlmostEqual(buy_price, 100.006, places=6)
        self.assertAlmostEqual(sell_price, 100.004, places=6)

    def test_wide_spread(self):
        """测试宽价差的情况"""
        best_bid = 100.0
        best_ask = 200.0

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # spread = 100.0, aggression = 0.6
        # buy = 100.0 + 100.0 * 0.6 = 160.0
        # sell = 200.0 - 100.0 * 0.6 = 140.0
        self.assertAlmostEqual(buy_price, 160.0, places=6)
        self.assertAlmostEqual(sell_price, 140.0, places=6)

    def test_buy_price_within_spread(self):
        """验证买入价格始终在spread内"""
        best_bid = 100.0
        best_ask = 110.0

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        self.assertGreaterEqual(buy_price, best_bid)
        self.assertLessEqual(buy_price, best_ask)

    def test_sell_price_within_spread(self):
        """验证卖出价格始终在spread内"""
        best_bid = 100.0
        best_ask = 110.0

        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )
        self.assertGreaterEqual(sell_price, best_bid)
        self.assertLessEqual(sell_price, best_ask)

    def test_zero_spread(self):
        """测试零价差情况(bid == ask)"""
        best_bid = 100.0
        best_ask = 100.0

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # When spread is 0, both prices should equal best_bid/best_ask
        self.assertAlmostEqual(buy_price, 100.0, places=6)
        self.assertAlmostEqual(sell_price, 100.0, places=6)
        self.assertAlmostEqual(buy_price, sell_price, places=6)

    def test_very_small_spread(self):
        """测试极小价差(高精度)"""
        best_bid = 1000.0000
        best_ask = 1000.0001

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # spread = 0.0001, aggression = 0.6
        # buy = 1000.0000 + 0.0001 * 0.6 = 1000.00006
        # sell = 1000.0001 - 0.0001 * 0.6 = 1000.00004
        self.assertAlmostEqual(buy_price, 1000.00006, places=8)
        self.assertAlmostEqual(sell_price, 1000.00004, places=8)

    def test_large_price_values(self):
        """测试大价格值(如BTC价格)"""
        best_bid = 60000.0
        best_ask = 60100.0

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # spread = 100.0, aggression = 0.6
        # buy = 60000.0 + 100.0 * 0.6 = 60060.0
        # sell = 60100.0 - 100.0 * 0.6 = 60040.0
        self.assertAlmostEqual(buy_price, 60060.0, places=6)
        self.assertAlmostEqual(sell_price, 60040.0, places=6)

    def test_small_price_values(self):
        """测试小价格值(如小币种价格)"""
        best_bid = 0.00010
        best_ask = 0.00012

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # spread = 0.00002, aggression = 0.6
        # buy = 0.00010 + 0.00002 * 0.6 = 0.000112
        # sell = 0.00012 - 0.00002 * 0.6 = 0.000108
        self.assertAlmostEqual(buy_price, 0.000112, places=8)
        self.assertAlmostEqual(sell_price, 0.000108, places=8)

    def test_symmetric_behavior(self):
        """验证买入和卖出价格的对称性"""
        best_bid = 100.0
        best_ask = 110.0

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # 在相同激进度下，买卖价格应该围绕spread中心对称
        # buy_price - best_bid 应该等于 best_ask - sell_price
        buy_offset = buy_price - best_bid
        sell_offset = best_ask - sell_price

        self.assertAlmostEqual(buy_offset, sell_offset, places=6,
                               msg="Asymmetric behavior with fixed aggression=0.6")

    def test_floating_point_precision(self):
        """测试浮点数精度问题"""
        # Use values that might cause floating-point precision issues
        best_bid = 0.1 + 0.2  # = 0.30000000000000004 in floating point
        best_ask = 0.4

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask
        )

        # Verify prices are still within spread despite floating-point issues
        self.assertGreaterEqual(buy_price, best_bid)
        self.assertLessEqual(buy_price, best_ask)
        self.assertGreaterEqual(sell_price, best_bid)
        self.assertLessEqual(sell_price, best_ask)


if __name__ == '__main__':
    unittest.main()
