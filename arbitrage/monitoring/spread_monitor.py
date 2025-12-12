"""
Spread Monitor - 价差监控适配器

将价差数据和交易对配对映射写入监控后端（Redis）的适配器层。
使用Framework的TradingPair对象。

更新内容 (2025-12-13):
- 改用 TradingPair 对象（替代已废弃的 SpreadSignal）
- write_spread() 现在接受 TradingPair 对象
"""
from AlgorithmImports import *
from QuantConnect.TradingPairs import TradingPair, MarketState
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
        monitor.write_spread(pair)  # pair: TradingPair 对象

    重构历史:
    - 2025-10-23: write_spread() 参数从 (pair_symbol, spread_pct) 改为 SpreadSignal 对象
    - 2025-12-13: 改用 TradingPair 对象（Framework API）
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

        except Exception as e:
            self.algorithm.Debug(f"⚠️ RedisSpreadMonitor: 配对映射写入失败: {e}")
            if not self._redis_error_logged:
                self._redis_error_logged = True
                import traceback
                self.algorithm.Debug(f"   详细错误:\n{traceback.format_exc()}")

    def write_spread(self, pair: TradingPair):
        """
        将价差数据写入 Redis（Framework版本 - 使用 TradingPair）

        重构变更:
        - 2025-10-23: 参数改为 SpreadSignal 对象，包含完整的价差信息
        - 2025-12-13: 改用 TradingPair 对象（Framework API）

        Args:
            pair: TradingPair 对象，包含：
                - Leg1Symbol / Leg2Symbol: 交易对的两个标的
                - TheoreticalSpread: 理论价差（始终有值，用于监控可视化）
                - MarketState: 市场状态（Crossed / LimitOpportunity / NoOpportunity）
                - ExecutableSpread: 可执行价差（可能为 None）
                - Direction: 交易方向
        """
        try:
            # 从 TradingPair 中获取数据
            crypto_symbol = pair.Leg1Symbol  # Assuming Leg1 is crypto
            stock_symbol = pair.Leg2Symbol   # Assuming Leg2 is stock

            # 获取 Security 对象以访问当前价格
            crypto_security = self.algorithm.Securities[crypto_symbol]
            stock_security = self.algorithm.Securities[stock_symbol]

            # 构建交易对标识 (如 "BTCUSDx<->BTC")
            pair_key = f"{crypto_symbol.Value}<->{stock_symbol.Value}"

            # 将MarketState枚举转换为字符串值
            if pair.MarketState == MarketState.Crossed:
                market_state_str = "crossed"
            elif pair.MarketState == MarketState.LimitOpportunity:
                market_state_str = "limit"
            else:  # NoOpportunity
                market_state_str = "none"

            # 构建价差数据
            spread_data = {
                'pair': pair_key,
                'crypto_symbol': crypto_symbol.Value,
                'stock_symbol': stock_symbol.Value,

                # 原有字段（向后兼容）
                'spread_pct': float(pair.TheoreticalSpread),

                # 新增字段（使用Framework数据）
                'market_state': market_state_str,  # "crossed" / "limit" / "none"
                'theoretical_spread': float(pair.TheoreticalSpread),
                'executable_spread': float(pair.ExecutableSpread) if pair.ExecutableSpread is not None else None,
                'direction': pair.Direction,  # Direction from TradingPair

                # 价格信息
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


        except Exception as e:
            self.algorithm.Debug(f"⚠️ RedisSpreadMonitor: 价差写入失败: {e}")
            # 输出详细错误信息（仅首次）
            if not self._redis_error_logged:
                self._redis_error_logged = True
                import traceback
                self.algorithm.Debug(f"   详细错误:\n{traceback.format_exc()}")
