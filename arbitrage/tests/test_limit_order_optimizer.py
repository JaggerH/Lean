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

    def test_calculate_buy_limit_price_default_aggression(self):
        """测试默认激进度(0.6)的买入价格计算"""
        best_bid = 100.0
        best_ask = 101.0

        result = LimitOrderOptimizer.calculate_buy_limit_price(best_bid, best_ask)

        # spread = 1.0, aggression = 0.6
        # expected = 100.0 + 1.0 * 0.6 = 100.6
        self.assertAlmostEqual(result, 100.6, places=6)

    def test_calculate_buy_limit_price_custom_aggression(self):
        """测试自定义激进度的买入价格计算"""
        best_bid = 50.0
        best_ask = 52.0
        aggression = 0.3

        result = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )

        # spread = 2.0, aggression = 0.3
        # expected = 50.0 + 2.0 * 0.3 = 50.6
        self.assertAlmostEqual(result, 50.6, places=6)

    def test_calculate_buy_limit_price_zero_aggression(self):
        """测试激进度为0时的买入价格(应该等于best_bid)"""
        best_bid = 100.0
        best_ask = 105.0

        result = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression=0.0
        )

        self.assertAlmostEqual(result, best_bid, places=6)

    def test_calculate_buy_limit_price_max_aggression(self):
        """测试激进度为0.99时的买入价格(接近best_ask)"""
        best_bid = 100.0
        best_ask = 110.0

        result = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression=0.99
        )

        # spread = 10.0, aggression = 0.99
        # expected = 100.0 + 10.0 * 0.99 = 109.9
        self.assertAlmostEqual(result, 109.9, places=6)

    def test_calculate_buy_limit_price_aggression_clamping_upper(self):
        """测试激进度超过0.99时会被限制"""
        best_bid = 100.0
        best_ask = 110.0

        result = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression=1.5
        )

        # aggression应被限制为0.99
        # expected = 100.0 + 10.0 * 0.99 = 109.9
        self.assertAlmostEqual(result, 109.9, places=6)

    def test_calculate_buy_limit_price_aggression_clamping_lower(self):
        """测试激进度为负数时会被限制为0"""
        best_bid = 100.0
        best_ask = 110.0

        result = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression=-0.5
        )

        # aggression应被限制为0.0
        self.assertAlmostEqual(result, best_bid, places=6)

    def test_calculate_sell_limit_price_default_aggression(self):
        """测试默认激进度(0.6)的卖出价格计算"""
        best_bid = 100.0
        best_ask = 101.0

        result = LimitOrderOptimizer.calculate_sell_limit_price(best_bid, best_ask)

        # spread = 1.0, aggression = 0.6
        # expected = 101.0 - 1.0 * 0.6 = 100.4
        self.assertAlmostEqual(result, 100.4, places=6)

    def test_calculate_sell_limit_price_custom_aggression(self):
        """测试自定义激进度的卖出价格计算"""
        best_bid = 50.0
        best_ask = 52.0
        aggression = 0.3

        result = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # spread = 2.0, aggression = 0.3
        # expected = 52.0 - 2.0 * 0.3 = 51.4
        self.assertAlmostEqual(result, 51.4, places=6)

    def test_calculate_sell_limit_price_zero_aggression(self):
        """测试激进度为0时的卖出价格(应该等于best_ask)"""
        best_bid = 100.0
        best_ask = 105.0

        result = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression=0.0
        )

        self.assertAlmostEqual(result, best_ask, places=6)

    def test_calculate_sell_limit_price_max_aggression(self):
        """测试激进度为0.99时的卖出价格(接近best_bid)"""
        best_bid = 100.0
        best_ask = 110.0

        result = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression=0.99
        )

        # spread = 10.0, aggression = 0.99
        # expected = 110.0 - 10.0 * 0.99 = 100.1
        self.assertAlmostEqual(result, 100.1, places=6)

    def test_calculate_sell_limit_price_aggression_clamping_upper(self):
        """测试激进度超过0.99时会被限制"""
        best_bid = 100.0
        best_ask = 110.0

        result = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression=2.0
        )

        # aggression应被限制为0.99
        # expected = 110.0 - 10.0 * 0.99 = 100.1
        self.assertAlmostEqual(result, 100.1, places=6)

    def test_calculate_sell_limit_price_aggression_clamping_lower(self):
        """测试激进度为负数时会被限制为0"""
        best_bid = 100.0
        best_ask = 110.0

        result = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression=-1.0
        )

        # aggression应被限制为0.0
        self.assertAlmostEqual(result, best_ask, places=6)

    def test_tight_spread(self):
        """测试窄价差的情况"""
        best_bid = 100.00
        best_ask = 100.01
        aggression = 0.5

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # spread = 0.01, aggression = 0.5
        # buy = 100.00 + 0.01 * 0.5 = 100.005
        # sell = 100.01 - 0.01 * 0.5 = 100.005
        self.assertAlmostEqual(buy_price, 100.005, places=6)
        self.assertAlmostEqual(sell_price, 100.005, places=6)

        # 在相同激进度下,买卖价应该相等
        self.assertAlmostEqual(buy_price, sell_price, places=6)

    def test_wide_spread(self):
        """测试宽价差的情况"""
        best_bid = 100.0
        best_ask = 200.0
        aggression = 0.5

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # spread = 100.0, aggression = 0.5
        # buy = 100.0 + 100.0 * 0.5 = 150.0
        # sell = 200.0 - 100.0 * 0.5 = 150.0
        self.assertAlmostEqual(buy_price, 150.0, places=6)
        self.assertAlmostEqual(sell_price, 150.0, places=6)

    def test_buy_price_within_spread(self):
        """验证买入价格始终在spread内"""
        best_bid = 100.0
        best_ask = 110.0

        for aggression in [0.0, 0.25, 0.5, 0.75, 0.99]:
            buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
                best_bid, best_ask, aggression
            )
            self.assertGreaterEqual(buy_price, best_bid)
            self.assertLessEqual(buy_price, best_ask)

    def test_sell_price_within_spread(self):
        """验证卖出价格始终在spread内"""
        best_bid = 100.0
        best_ask = 110.0

        for aggression in [0.0, 0.25, 0.5, 0.75, 0.99]:
            sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
                best_bid, best_ask, aggression
            )
            self.assertGreaterEqual(sell_price, best_bid)
            self.assertLessEqual(sell_price, best_ask)

    def test_zero_spread(self):
        """测试零价差情况(bid == ask)"""
        best_bid = 100.0
        best_ask = 100.0
        aggression = 0.5

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # When spread is 0, both prices should equal best_bid/best_ask
        self.assertAlmostEqual(buy_price, 100.0, places=6)
        self.assertAlmostEqual(sell_price, 100.0, places=6)
        self.assertAlmostEqual(buy_price, sell_price, places=6)

    def test_very_small_spread(self):
        """测试极小价差(高精度)"""
        best_bid = 1000.0000
        best_ask = 1000.0001
        aggression = 0.5

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # spread = 0.0001, aggression = 0.5
        # buy = 1000.0000 + 0.0001 * 0.5 = 1000.00005
        # sell = 1000.0001 - 0.0001 * 0.5 = 1000.00005
        self.assertAlmostEqual(buy_price, 1000.00005, places=8)
        self.assertAlmostEqual(sell_price, 1000.00005, places=8)

    def test_large_price_values(self):
        """测试大价格值(如BTC价格)"""
        best_bid = 60000.0
        best_ask = 60100.0
        aggression = 0.5

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # spread = 100.0, aggression = 0.5
        # buy = 60000.0 + 100.0 * 0.5 = 60050.0
        # sell = 60100.0 - 100.0 * 0.5 = 60050.0
        self.assertAlmostEqual(buy_price, 60050.0, places=6)
        self.assertAlmostEqual(sell_price, 60050.0, places=6)

    def test_small_price_values(self):
        """测试小价格值(如小币种价格)"""
        best_bid = 0.00010
        best_ask = 0.00012
        aggression = 0.6

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
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

        for aggression in [0.1, 0.3, 0.5, 0.7, 0.9]:
            buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
                best_bid, best_ask, aggression
            )
            sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
                best_bid, best_ask, aggression
            )

            # 在相同激进度下，买卖价格应该围绕spread中心对称
            # buy_price - best_bid 应该等于 best_ask - sell_price
            buy_offset = buy_price - best_bid
            sell_offset = best_ask - sell_price

            self.assertAlmostEqual(buy_offset, sell_offset, places=6,
                                   msg=f"Asymmetric behavior at aggression={aggression}")

    def test_aggression_edge_case_exactly_one(self):
        """测试激进度恰好为1.0的边界情况"""
        best_bid = 100.0
        best_ask = 110.0

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression=1.0
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression=1.0
        )

        # aggression应被限制为0.99
        expected_buy = 100.0 + 10.0 * 0.99
        expected_sell = 110.0 - 10.0 * 0.99

        self.assertAlmostEqual(buy_price, expected_buy, places=6)
        self.assertAlmostEqual(sell_price, expected_sell, places=6)

    def test_floating_point_precision(self):
        """测试浮点数精度问题"""
        # Use values that might cause floating-point precision issues
        best_bid = 0.1 + 0.2  # = 0.30000000000000004 in floating point
        best_ask = 0.4
        aggression = 0.5

        buy_price = LimitOrderOptimizer.calculate_buy_limit_price(
            best_bid, best_ask, aggression
        )
        sell_price = LimitOrderOptimizer.calculate_sell_limit_price(
            best_bid, best_ask, aggression
        )

        # Verify prices are still within spread despite floating-point issues
        self.assertGreaterEqual(buy_price, best_bid)
        self.assertLessEqual(buy_price, best_ask)
        self.assertGreaterEqual(sell_price, best_bid)
        self.assertLessEqual(sell_price, best_ask)

    def test_aggression_increment_monotonicity(self):
        """验证激进度递增时价格的单调性"""
        best_bid = 100.0
        best_ask = 110.0

        aggression_levels = [0.0, 0.2, 0.4, 0.6, 0.8, 0.99]

        buy_prices = []
        sell_prices = []

        for aggression in aggression_levels:
            buy_prices.append(LimitOrderOptimizer.calculate_buy_limit_price(
                best_bid, best_ask, aggression
            ))
            sell_prices.append(LimitOrderOptimizer.calculate_sell_limit_price(
                best_bid, best_ask, aggression
            ))

        # Buy prices should be monotonically increasing
        for i in range(len(buy_prices) - 1):
            self.assertLessEqual(buy_prices[i], buy_prices[i + 1],
                                msg=f"Buy price not monotonic at index {i}")

        # Sell prices should be monotonically decreasing
        for i in range(len(sell_prices) - 1):
            self.assertGreaterEqual(sell_prices[i], sell_prices[i + 1],
                                   msg=f"Sell price not monotonic at index {i}")


if __name__ == '__main__':
    unittest.main()
