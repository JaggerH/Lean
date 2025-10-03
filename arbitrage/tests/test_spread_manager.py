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
from SpreadManager import SpreadManager


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
        """测试 SpreadManager 初始化"""
        # 创建测试算法实例
        algo = TestAlgorithm()

        # 初始化 SpreadManager
        manager = SpreadManager(algo, strategy=None, aggression=0.6)

        # 验证初始化状态
        self.assertIsNotNone(manager)
        self.assertEqual(manager.algorithm, algo)
        self.assertIsNone(manager.strategy)
        self.assertEqual(manager.aggression, 0.6)

        # 验证空数据结构
        self.assertEqual(len(manager.pairs), 0)
        self.assertEqual(len(manager.stock_to_cryptos), 0)
        self.assertEqual(len(manager.stocks), 0)
        self.assertEqual(len(manager.cryptos), 0)
        self.assertEqual(len(manager.pair_positions), 0)
        self.assertEqual(len(manager.orders), 0)

        print("✅ SpreadManager initialization test passed")

    def test_init_with_custom_aggression(self):
        """测试自定义 aggression 参数"""
        algo = TestAlgorithm()

        # 使用自定义 aggression
        manager = SpreadManager(algo, strategy=None, aggression=0.8)

        self.assertEqual(manager.aggression, 0.8)
        print("✅ Custom aggression test passed")

    def test_init_with_strategy(self):
        """测试带 strategy 的初始化"""
        algo = TestAlgorithm()

        # 创建一个 mock strategy
        class MockStrategy:
            pass

        strategy = MockStrategy()
        manager = SpreadManager(algo, strategy=strategy, aggression=0.5)

        self.assertEqual(manager.strategy, strategy)
        self.assertEqual(manager.aggression, 0.5)
        print("✅ Strategy initialization test passed")

    def test_add_pair(self):
        """测试添加交易对"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # 创建 Symbol 对象（而不是直接创建 Security）
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # 创建 mock securities
        # 在实际的 LEAN 环境中，Security 应该从 algorithm.Securities 获取
        # 这里我们只测试 Symbol 的部分
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        crypto = MockSecurity(crypto_symbol)
        stock = MockSecurity(stock_symbol)

        # 添加交易对
        manager.add_pair(crypto, stock)

        # 验证
        self.assertEqual(len(manager.pairs), 1)
        self.assertEqual(manager.pairs[crypto.Symbol], stock.Symbol)
        self.assertEqual(len(manager.stock_to_cryptos[stock.Symbol]), 1)
        self.assertIn(crypto, manager.cryptos)
        self.assertIn(stock, manager.stocks)

        # 验证 debug 消息
        debug_msgs = algo.get_debug_messages()
        self.assertGreater(len(debug_msgs), 0)

        print("✅ Add pair test passed")

    def test_get_all_pairs(self):
        """测试获取所有交易对"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # 创建 mock security helper
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        # 创建两个交易对
        crypto1 = MockSecurity(Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken))
        stock1 = MockSecurity(Symbol.Create("TSLA", SecurityType.Equity, Market.USA))

        crypto2 = MockSecurity(Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken))
        stock2 = MockSecurity(Symbol.Create("AAPL", SecurityType.Equity, Market.USA))

        manager.add_pair(crypto1, stock1)
        manager.add_pair(crypto2, stock2)

        # 获取所有交易对
        pairs = manager.get_all_pairs()

        # 验证
        self.assertEqual(len(pairs), 2)
        self.assertIn((crypto1.Symbol, stock1.Symbol), pairs)
        self.assertIn((crypto2.Symbol, stock2.Symbol), pairs)

        print("✅ Get all pairs test passed")

    def test_calculate_spread_pct(self):
        """测试 spread 百分比计算"""
        # 静态方法，不需要 algorithm 实例

        # 测试场景1: token 高于 stock
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.5,
            token_ask=150.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # 应该返回正值（short token, long stock）
        self.assertGreater(spread, 0)

        # 测试场景2: token 低于 stock
        spread = SpreadManager.calculate_spread_pct(
            token_bid=149.5,
            token_ask=149.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # 应该返回负值（long token, short stock）
        self.assertLess(spread, 0)

        print("✅ Calculate spread percentage test passed")

    def test_get_cryptos_for_stock(self):
        """测试获取 stock 对应的所有 crypto"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        # 创建 mock security helper
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        # 创建一个 stock 对应多个 crypto 的情况
        stock = MockSecurity(Symbol.Create("TSLA", SecurityType.Equity, Market.USA))
        crypto1 = MockSecurity(Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken))
        crypto2 = MockSecurity(Symbol.Create("TSLAON", SecurityType.Crypto, Market.Kraken))

        manager.add_pair(crypto1, stock)
        manager.add_pair(crypto2, stock)

        # 获取该 stock 的所有 crypto
        cryptos = manager.get_cryptos_for_stock(stock.Symbol)

        # 验证
        self.assertEqual(len(cryptos), 2)
        self.assertIn(crypto1.Symbol, cryptos)
        self.assertIn(crypto2.Symbol, cryptos)

        print("✅ Get cryptos for stock test passed")

    def test_record_position(self):
        """测试记录仓位"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # 记录仓位
        manager.record_position(crypto_symbol, stock_symbol, -100.0, 100.0)

        # 验证
        pair_key = (crypto_symbol, stock_symbol)
        self.assertIn(pair_key, manager.pair_positions)
        self.assertEqual(manager.pair_positions[pair_key]['token_qty'], -100.0)
        self.assertEqual(manager.pair_positions[pair_key]['stock_qty'], 100.0)

        print("✅ Record position test passed")

    def test_get_net_stock_position(self):
        """测试获取 stock 的净仓位"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        crypto1_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        crypto2_symbol = Symbol.Create("TSLAON", SecurityType.Crypto, Market.Kraken)

        # 记录多个仓位
        manager.record_position(crypto1_symbol, stock_symbol, -100.0, 100.0)
        manager.record_position(crypto2_symbol, stock_symbol, -200.0, 200.0)

        # 获取净仓位
        net_position = manager.get_net_stock_position(stock_symbol)

        # 验证
        self.assertEqual(net_position, 300.0)  # 100 + 200

        print("✅ Get net stock position test passed")

    def test_close_partial_position(self):
        """测试部分平仓功能"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # 先添加交易对
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        manager.add_pair(MockSecurity(crypto_symbol), MockSecurity(stock_symbol))

        # 记录初始仓位: TSLAx(-300), TSLA(+300)
        manager.record_position(crypto_symbol, stock_symbol, -300.0, 300.0)

        # 平仓100
        result = manager.close_partial_position(crypto_symbol, 100.0)

        # 验证返回值
        self.assertEqual(result['crypto_close_qty'], 100.0)
        self.assertEqual(result['stock_close_qty'], 100.0)

        # 验证剩余仓位: TSLAx(-200), TSLA(+200)
        pair_key = (crypto_symbol, stock_symbol)
        self.assertEqual(manager.pair_positions[pair_key]['token_qty'], -200.0)
        self.assertEqual(manager.pair_positions[pair_key]['stock_qty'], 200.0)

        print("✅ Close partial position test passed")

    def test_close_partial_position_no_pair(self):
        """测试平仓时交易对不存在的错误处理"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)

        # 尝试平仓一个不存在的交易对
        with self.assertRaises(ValueError) as context:
            manager.close_partial_position(crypto_symbol, 100.0)

        self.assertIn("No stock paired with crypto", str(context.exception))

        print("✅ Close partial position error handling test passed")

    def test_close_partial_position_no_position(self):
        """测试平仓时仓位不存在的错误处理"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # 添加交易对但不记录仓位
        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        manager.add_pair(MockSecurity(crypto_symbol), MockSecurity(stock_symbol))

        # 尝试平仓一个不存在的仓位
        with self.assertRaises(ValueError) as context:
            manager.close_partial_position(crypto_symbol, 100.0)

        self.assertIn("No position found for pair", str(context.exception))

        print("✅ Close partial position no position error test passed")


class TestSpreadManagerCalculations(unittest.TestCase):
    """Test spread calculation edge cases"""

    def test_calculate_spread_pct_zero_token_bid(self):
        """测试 token bid 为 0 的边界情况"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=0.0,
            token_ask=150.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # 当 token_bid 为 0 时，应返回 0
        self.assertEqual(spread, 0.0)
        print("✅ Zero token bid test passed")

    def test_calculate_spread_pct_zero_token_ask(self):
        """测试 token ask 为 0 的边界情况"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.0,
            token_ask=0.0,
            stock_bid=100.0,
            stock_ask=101.0
        )

        # 当 token_ask 为 0 时，应返回 0
        self.assertEqual(spread, 0.0)
        print("✅ Zero token ask test passed")

    def test_calculate_spread_pct_equal_prices(self):
        """测试所有价格相等的情况"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.0,
            token_ask=150.0,
            stock_bid=150.0,
            stock_ask=150.0
        )

        # 价格相等时，spread 应为 0
        self.assertEqual(spread, 0.0)
        print("✅ Equal prices test passed")

    def test_calculate_spread_pct_large_positive_spread(self):
        """测试大的正 spread (token 明显高于 stock)"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=200.0,
            token_ask=201.0,
            stock_bid=150.0,
            stock_ask=151.0
        )

        # 应返回正值，且较大
        self.assertGreater(spread, 0.2)  # 超过 20%
        print(f"✅ Large positive spread test passed (spread={spread:.4f})")

    def test_calculate_spread_pct_large_negative_spread(self):
        """测试大的负 spread (token 明显低于 stock)"""
        spread = SpreadManager.calculate_spread_pct(
            token_bid=100.0,
            token_ask=101.0,
            stock_bid=150.0,
            stock_ask=151.0
        )

        # 应返回负值，且较大
        self.assertLess(spread, -0.3)  # 低于 -30%
        print(f"✅ Large negative spread test passed (spread={spread:.4f})")

    def test_calculate_spread_pct_chooses_larger_absolute(self):
        """测试选择绝对值较大的 spread"""
        # 场景: short token spread = 0.2%, long token spread = 0.4%
        # 应选择 0.4%
        spread = SpreadManager.calculate_spread_pct(
            token_bid=150.5,
            token_ask=150.6,
            stock_bid=150.0,
            stock_ask=150.1
        )

        # Scenario 1: (150.5 - 150.1) / 150.5 = 0.266%
        # Scenario 2: (150.6 - 150.0) / 150.6 = 0.398%
        # 应返回 Scenario 2 (较大的绝对值)
        self.assertAlmostEqual(spread, 0.00398, places=5)
        print(f"✅ Larger absolute value selection test passed (spread={spread:.5f})")


class TestSpreadManagerExecutionEngine(unittest.TestCase):
    """Test ExecutionEngine integration methods"""

    def test_get_pair_symbol_from_crypto_exists(self):
        """测试通过 crypto symbol 获取交易对 (存在)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        manager.add_pair(MockSecurity(crypto_symbol), MockSecurity(stock_symbol))

        # 获取交易对
        pair = manager.get_pair_symbol_from_crypto(crypto_symbol)

        # 验证
        self.assertIsNotNone(pair)
        self.assertEqual(pair[0], crypto_symbol)
        self.assertEqual(pair[1], stock_symbol)

        print("✅ Get pair symbol from crypto (exists) test passed")

    def test_get_pair_symbol_from_crypto_not_exists(self):
        """测试通过 crypto symbol 获取交易对 (不存在)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)

        # 获取不存在的交易对
        pair = manager.get_pair_symbol_from_crypto(crypto_symbol)

        # 验证
        self.assertIsNone(pair)

        print("✅ Get pair symbol from crypto (not exists) test passed")

    def test_add_order(self):
        """测试添加订单跟踪"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 添加订单
        manager.add_order(pair_symbol, order_id=12345, is_close=False)

        # 验证
        self.assertIn(pair_symbol, manager.orders)
        self.assertEqual(manager.orders[pair_symbol]['crypto_order'], 12345)
        self.assertEqual(manager.orders[pair_symbol]['is_close'], False)

        print("✅ Add order test passed")

    def test_add_order_close(self):
        """测试添加平仓订单"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 添加平仓订单
        manager.add_order(pair_symbol, order_id=54321, is_close=True)

        # 验证
        order_info = manager.get_order(pair_symbol)
        self.assertIsNotNone(order_info)
        self.assertEqual(order_info['crypto_order'], 54321)
        self.assertEqual(order_info['is_close'], True)

        print("✅ Add close order test passed")

    def test_add_order_duplicate_open_order(self):
        """测试重复添加开仓订单 (应该被忽略)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 添加第一个订单
        manager.add_order(pair_symbol, order_id=12345, is_close=False)

        # 尝试添加重复订单
        algo.clear_debug_messages()
        manager.add_order(pair_symbol, order_id=67890, is_close=False)

        # 验证第二个订单被忽略
        self.assertEqual(manager.orders[pair_symbol]['crypto_order'], 12345)

        # 验证有警告消息
        debug_msgs = algo.get_debug_messages()
        self.assertTrue(any("already exists" in msg for msg in debug_msgs))

        print("✅ Duplicate open order test passed")

    def test_add_order_close_overwrites(self):
        """测试平仓订单可以覆盖现有订单"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 添加开仓订单
        manager.add_order(pair_symbol, order_id=12345, is_close=False)

        # 添加平仓订单 (应该覆盖)
        manager.add_order(pair_symbol, order_id=54321, is_close=True)

        # 验证平仓订单覆盖了开仓订单
        order_info = manager.get_order(pair_symbol)
        self.assertEqual(order_info['crypto_order'], 54321)
        self.assertEqual(order_info['is_close'], True)

        print("✅ Close order overwrites test passed")

    def test_get_order_not_exists(self):
        """测试获取不存在的订单"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 获取不存在的订单
        order_info = manager.get_order(pair_symbol)

        # 验证
        self.assertIsNone(order_info)

        print("✅ Get order (not exists) test passed")

    def test_get_pair_position_exists(self):
        """测试获取交易对仓位 (存在)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 记录仓位
        manager.record_position(crypto_symbol, stock_symbol, -100.0, 100.0)

        # 获取仓位
        position = manager.get_pair_position(pair_symbol)

        # 验证
        self.assertIsNotNone(position)
        self.assertEqual(position[0], -100.0)  # crypto_qty
        self.assertEqual(position[1], 100.0)   # stock_qty

        print("✅ Get pair position (exists) test passed")

    def test_get_pair_position_not_exists(self):
        """测试获取不存在的交易对仓位"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 获取不存在的仓位
        position = manager.get_pair_position(pair_symbol)

        # 验证
        self.assertIsNone(position)

        print("✅ Get pair position (not exists) test passed")

    def test_update_pair_position_new(self):
        """测试更新仓位 (新建)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 更新仓位 (首次)
        manager.update_pair_position(pair_symbol, -50.0, 50.0)

        # 验证
        position = manager.get_pair_position(pair_symbol)
        self.assertEqual(position[0], -50.0)
        self.assertEqual(position[1], 50.0)

        print("✅ Update pair position (new) test passed")

    def test_update_pair_position_accumulate(self):
        """测试仓位累加"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 第一次更新
        manager.update_pair_position(pair_symbol, -50.0, 50.0)

        # 第二次更新 (累加)
        manager.update_pair_position(pair_symbol, -30.0, 30.0)

        # 验证累加结果
        position = manager.get_pair_position(pair_symbol)
        self.assertEqual(position[0], -80.0)  # -50 + (-30)
        self.assertEqual(position[1], 80.0)   # 50 + 30

        print("✅ Update pair position (accumulate) test passed")

    def test_update_pair_position_reduce(self):
        """测试仓位减少"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        pair_symbol = (crypto_symbol, stock_symbol)

        # 开仓
        manager.update_pair_position(pair_symbol, -100.0, 100.0)

        # 减仓
        manager.update_pair_position(pair_symbol, 50.0, -50.0)

        # 验证减仓结果
        position = manager.get_pair_position(pair_symbol)
        self.assertEqual(position[0], -50.0)  # -100 + 50
        self.assertEqual(position[1], 50.0)   # 100 + (-50)

        print("✅ Update pair position (reduce) test passed")


class TestSpreadManagerMonitoring(unittest.TestCase):
    """Test spread monitoring functionality"""

    def test_monitor_spread_no_strategy(self):
        """测试没有 strategy 时 monitor_spread 不执行"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo, strategy=None)

        # 准备 mock quotes
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)

        class MockQuote:
            def __init__(self, bid, ask):
                self.BidPrice = bid
                self.AskPrice = ask

        latest_quotes = {
            crypto_symbol: MockQuote(150.0, 151.0)
        }

        # 调用 monitor_spread (应该直接返回，不报错)
        manager.monitor_spread(latest_quotes)

        # 验证没有崩溃即可
        print("✅ Monitor spread (no strategy) test passed")

    def test_monitor_spread_with_strategy(self):
        """测试有 strategy 时正确调用 on_spread_update"""
        algo = TestAlgorithm()

        # 创建 mock strategy
        class MockStrategy:
            def __init__(self):
                self.calls = []

            def on_spread_update(self, crypto_symbol, stock_symbol, spread_pct,
                                crypto_quote, stock_quote,
                                crypto_bid_price, crypto_ask_price):
                self.calls.append({
                    'crypto_symbol': crypto_symbol,
                    'stock_symbol': stock_symbol,
                    'spread_pct': spread_pct,
                    'crypto_bid_price': crypto_bid_price,
                    'crypto_ask_price': crypto_ask_price
                })

        strategy = MockStrategy()
        manager = SpreadManager(algo, strategy=strategy, aggression=0.6)

        # 添加交易对
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        manager.add_pair(MockSecurity(crypto_symbol), MockSecurity(stock_symbol))

        # 准备 mock quotes
        class MockQuote:
            def __init__(self, bid, ask):
                self.BidPrice = bid
                self.AskPrice = ask

        latest_quotes = {
            crypto_symbol: MockQuote(150.0, 151.0),
            stock_symbol: MockQuote(149.0, 150.0)
        }

        # 调用 monitor_spread
        manager.monitor_spread(latest_quotes)

        # 验证 strategy.on_spread_update 被调用
        self.assertEqual(len(strategy.calls), 1)
        call = strategy.calls[0]
        self.assertEqual(call['crypto_symbol'], crypto_symbol)
        self.assertEqual(call['stock_symbol'], stock_symbol)

        # 验证使用了限价单价格
        # crypto_bid_price = sell_limit = 151.0 - (151.0 - 150.0) * 0.6 = 150.4
        # crypto_ask_price = buy_limit = 150.0 + (151.0 - 150.0) * 0.6 = 150.6
        # However, looking at the code, the names are swapped in monitor_spread:
        # crypto_bid_price = calculate_buy_limit_price (buying crypto)
        # crypto_ask_price = calculate_sell_limit_price (selling crypto)
        self.assertAlmostEqual(call['crypto_bid_price'], 150.6, places=5)  # buy_limit
        self.assertAlmostEqual(call['crypto_ask_price'], 150.4, places=5)  # sell_limit

        print("✅ Monitor spread (with strategy) test passed")

    def test_monitor_spread_missing_quotes(self):
        """测试缺少部分 quotes 时跳过该交易对"""
        algo = TestAlgorithm()

        class MockStrategy:
            def __init__(self):
                self.calls = []

            def on_spread_update(self, crypto_symbol, stock_symbol, spread_pct,
                                crypto_quote, stock_quote,
                                crypto_bid_price, crypto_ask_price):
                self.calls.append({})

        strategy = MockStrategy()
        manager = SpreadManager(algo, strategy=strategy)

        # 添加交易对
        crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        class MockSecurity:
            def __init__(self, symbol):
                self.Symbol = symbol

        manager.add_pair(MockSecurity(crypto_symbol), MockSecurity(stock_symbol))

        # 只提供 crypto quote，缺少 stock quote
        class MockQuote:
            def __init__(self, bid, ask):
                self.BidPrice = bid
                self.AskPrice = ask

        latest_quotes = {
            crypto_symbol: MockQuote(150.0, 151.0)
            # stock_symbol missing
        }

        # 调用 monitor_spread
        manager.monitor_spread(latest_quotes)

        # 验证 strategy 没有被调用
        self.assertEqual(len(strategy.calls), 0)

        print("✅ Monitor spread (missing quotes) test passed")


class TestSpreadManagerManyToOne(unittest.TestCase):
    """Test many-to-one crypto-stock relationships"""

    def test_multiple_cryptos_one_stock(self):
        """测试多个 crypto 对应一个 stock"""
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

        # 添加三个 crypto 都对应同一个 stock
        manager.add_pair(MockSecurity(crypto1_symbol), stock)
        manager.add_pair(MockSecurity(crypto2_symbol), stock)
        manager.add_pair(MockSecurity(crypto3_symbol), stock)

        # 验证 stock 对应的 crypto 列表
        cryptos = manager.get_cryptos_for_stock(stock_symbol)
        self.assertEqual(len(cryptos), 3)
        self.assertIn(crypto1_symbol, cryptos)
        self.assertIn(crypto2_symbol, cryptos)
        self.assertIn(crypto3_symbol, cryptos)

        # 验证只有一个 stock 被添加
        self.assertEqual(len(manager.stocks), 1)

        print("✅ Multiple cryptos one stock test passed")

    def test_net_position_multiple_pairs(self):
        """测试多个交易对的净仓位计算"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        crypto1_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        crypto2_symbol = Symbol.Create("TSLAON", SecurityType.Crypto, Market.Kraken)
        crypto3_symbol = Symbol.Create("TSLAzUSD", SecurityType.Crypto, Market.Kraken)

        # 记录多个仓位
        manager.record_position(crypto1_symbol, stock_symbol, -100.0, 100.0)
        manager.record_position(crypto2_symbol, stock_symbol, -200.0, 200.0)
        manager.record_position(crypto3_symbol, stock_symbol, -150.0, 150.0)

        # 计算净仓位
        net_position = manager.get_net_stock_position(stock_symbol)

        # 验证: 100 + 200 + 150 = 450
        self.assertEqual(net_position, 450.0)

        print("✅ Net position multiple pairs test passed")

    def test_net_position_with_mixed_directions(self):
        """测试混合方向的净仓位 (部分做多，部分做空)"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)
        crypto1_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        crypto2_symbol = Symbol.Create("TSLAON", SecurityType.Crypto, Market.Kraken)

        # 一个做多 stock，一个做空 stock
        manager.record_position(crypto1_symbol, stock_symbol, -100.0, 100.0)   # Long stock
        manager.record_position(crypto2_symbol, stock_symbol, 50.0, -50.0)     # Short stock

        # 计算净仓位
        net_position = manager.get_net_stock_position(stock_symbol)

        # 验证: 100 + (-50) = 50
        self.assertEqual(net_position, 50.0)

        print("✅ Net position mixed directions test passed")

    def test_net_position_no_stock(self):
        """测试不存在的 stock 的净仓位"""
        algo = TestAlgorithm()
        manager = SpreadManager(algo)

        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # 获取不存在的 stock 的净仓位
        net_position = manager.get_net_stock_position(stock_symbol)

        # 验证返回 0
        self.assertEqual(net_position, 0.0)

        print("✅ Net position (no stock) test passed")


if __name__ == '__main__':
    print("Running SpreadManager tests...\n")
    unittest.main(verbosity=2)
