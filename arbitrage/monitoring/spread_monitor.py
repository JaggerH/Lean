"""
Spread Monitor - 价差监控适配器

将价差数据和交易对配对映射写入监控后端（Redis）的适配器层。
从核心业务逻辑 (SpreadManager) 中解耦监控实现细节。
"""
from AlgorithmImports import *
from typing import Optional


class RedisSpreadMonitor:
    """
    基于 Redis 的价差监控适配器

    负责:
    - 写入交易对配对映射 (pair_mappings)
    - 写入实时价差数据 (spreads)

    使用方式:
        monitor = RedisSpreadMonitor(algorithm, redis_client)
        monitor.write_pair_mapping(crypto, stock)
        monitor.write_spread(crypto_symbol, stock_symbol, spread_pct, ...)
    """

    def __init__(self, algorithm: QCAlgorithm, redis_client):
        """
        初始化监控适配器

        Args:
            algorithm: QCAlgorithm 实例（用于日志输出）
            redis_client: TradingRedis 客户端实例
        """
        self.algorithm = algorithm
        self.redis = redis_client

        # 日志记录状态（避免刷屏）
        self._pair_mapping_logged = set()
        self._spread_write_logged = set()
        self._redis_error_logged = False

    def write_pair_mapping(self, crypto: Security, stock: Security):
        """
        将交易对配对映射写入 Redis（在 subscribe 时写入，持久化配对关系）

        这个方法在 add_pair() 时调用，将配对关系写入 Redis，
        让监控系统能够根据市场信息正确配对持仓数据。

        Args:
            crypto: Crypto Security 对象
            stock: Stock Security 对象

        Redis数据结构:
            Key: trading:pair_mappings (Hash)
            Field: "{crypto_symbol}<->{stock_symbol}"
            Value: {
                "pair": "AAPLUSDx<->AAPL",
                "crypto": {
                    "symbol": "AAPLUSDx",
                    "market": "kraken",
                    "account": "Kraken"
                },
                "stock": {
                    "symbol": "AAPL",
                    "market": "usa",
                    "account": "IBKR"
                }
            }
        """
        try:
            crypto_symbol = crypto.Symbol
            stock_symbol = stock.Symbol

            # 构建交易对标识
            pair_key = f"{crypto_symbol.Value}<->{stock_symbol.Value}"

            # 从 Symbol.ID.Market 获取市场信息
            crypto_market = str(crypto_symbol.ID.Market).lower()
            stock_market = str(stock_symbol.ID.Market).lower()

            # 根据市场推断账户名称
            # TODO: 未来支持多交易所时，这个映射可以配置化
            crypto_account = "Kraken" if crypto_market == "kraken" else "Unknown"
            stock_account = "IBKR" if stock_market == "usa" else "Unknown"

            # 构建配对数据
            mapping_data = {
                'pair': pair_key,
                'crypto': {
                    'symbol': crypto_symbol.Value,
                    'market': crypto_market,
                    'account': crypto_account
                },
                'stock': {
                    'symbol': stock_symbol.Value,
                    'market': stock_market,
                    'account': stock_account
                }
            }

            # 写入 Redis
            self.redis.set_pair_mapping(pair_key, mapping_data)

            # 日志：每个交易对只记录首次成功写入
            if pair_key not in self._pair_mapping_logged:
                self._pair_mapping_logged.add(pair_key)
                self.algorithm.Debug(
                    f"✓ Redis配对映射写入成功: {pair_key} | "
                    f"crypto({crypto_market}) <-> stock({stock_market})"
                )

        except Exception as e:
            self.algorithm.Debug(f"⚠️ RedisSpreadMonitor: 配对映射写入失败: {e}")
            if not self._redis_error_logged:
                self._redis_error_logged = True
                import traceback
                self.algorithm.Debug(f"   详细错误:\n{traceback.format_exc()}")

    def write_spread(self, pair_symbol: tuple, spread_pct: float):
        """
        将价差数据写入 Redis

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
            spread_pct: 价差百分比
        """
        try:
            crypto_symbol, stock_symbol = pair_symbol

            # 获取 Security 对象以访问当前价格
            crypto_security = self.algorithm.securities[crypto_symbol]
            stock_security = self.algorithm.securities[stock_symbol]

            # 构建交易对标识 (如 "BTCUSDx<->BTC")
            pair_key = f"{crypto_symbol.Value}<->{stock_symbol.Value}"

            # 构建价差数据
            spread_data = {
                'pair': pair_key,
                'crypto_symbol': crypto_symbol.Value,
                'stock_symbol': stock_symbol.Value,
                'spread_pct': float(spread_pct),
                'crypto_bid': float(crypto_security.Cache.BidPrice),
                'crypto_ask': float(crypto_security.Cache.AskPrice),
                'crypto_limit_bid': float(crypto_security.Cache.BidPrice),  # 我们的买入限价
                'crypto_limit_ask': float(crypto_security.Cache.AskPrice),  # 我们的卖出限价
                'stock_bid': float(stock_security.Cache.BidPrice),
                'stock_ask': float(stock_security.Cache.AskPrice),
                'timestamp': self.algorithm.Time.isoformat()
            }

            # 写入 Redis
            self.redis.set_spread(pair_key, spread_data)

            # 调试日志：每个交易对只记录首次成功写入
            if pair_key not in self._spread_write_logged:
                self._spread_write_logged.add(pair_key)
                self.algorithm.Debug(
                    f"✓ Redis价差写入成功 [{pair_key}] | "
                    f"spread={spread_pct:.4%} | "
                    f"crypto={crypto_security.Cache.BidPrice:.2f}/{crypto_security.Cache.AskPrice:.2f} | "
                    f"stock={stock_security.Cache.BidPrice:.2f}/{stock_security.Cache.AskPrice:.2f}"
                )


        except Exception as e:
            self.algorithm.Debug(f"⚠️ RedisSpreadMonitor: 价差写入失败: {e}")
            # 输出详细错误信息（仅首次）
            if not self._redis_error_logged:
                self._redis_error_logged = True
                import traceback
                self.algorithm.Debug(f"   详细错误:\n{traceback.format_exc()}")
