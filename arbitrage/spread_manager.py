"""
SpreadManager - Core position and subscription management for crypto-stock arbitrage

Manages many-to-one relationships between crypto tokens (e.g., TSLAx on Kraken)
and underlying stocks (e.g., TSLA on IBKR).
"""
from AlgorithmImports import *
from typing import Dict, Set, List, Tuple, Optional, TYPE_CHECKING, Type
import sys
import os
sys.path.append(os.path.dirname(__file__))
from limit_order_optimizer import LimitOrderOptimizer
from QuantConnect.Orders.Fees import KrakenFeeModel, InteractiveBrokersFeeModel
from QuantConnect.Securities import SecurityMarginModel
from QuantConnect.Data.Market import OrderbookDepth

# 避免循环导入，仅用于类型检查
if TYPE_CHECKING:
    from monitoring.spread_monitor import RedisSpreadMonitor
    from strategy.base_strategy import BaseStrategy


class SpreadManager:
    """
    Manages crypto-stock trading pairs with automatic deduplication and position tracking.

    Key Features:
    - Automatic stock subscription with deduplication (many tokens -> one stock)
    - Track all crypto-stock pairs
    - Calculate spread percentage
    - (Phase 2) Manage net positions to avoid risk exposure

    Example Usage:
        manager = SpreadManager(algorithm)

        # Subscribe crypto and auto-subscribe corresponding stock
        crypto = algorithm.AddCrypto("TSLAxUSD", Resolution.Tick, Market.Kraken)
        stock = manager.subscribe_stock_by_crypto(crypto)
        manager.add_pair(crypto, stock)
    """

    def __init__(self, algorithm: QCAlgorithm, strategy: Optional['BaseStrategy'] = None,
                 aggression: float = 0.6,
                 monitor_adapter: Optional['RedisSpreadMonitor'] = None):
        """
        Initialize SpreadManager

        Args:
            algorithm: QCAlgorithm instance for accessing trading APIs
            strategy: 策略实例 (可选，如 LongCryptoStrategy, BothSideStrategy)
            aggression: 限价单激进度
            monitor_adapter: 监控适配器实例 (可选，如 RedisSpreadMonitor)
        """
        self.algorithm = algorithm
        self.strategy = strategy
        self.aggression = aggression
        self.monitor = monitor_adapter  # 监控适配器（依赖注入）

        # 日志输出
        if self.monitor:
            self.algorithm.Debug("📊 SpreadManager: 监控适配器已启用")
        else:
            self.algorithm.Debug("📊 SpreadManager: 监控适配器未启用")

        # Crypto Symbol -> Stock Symbol mapping
        self.pairs: Dict[Symbol, Symbol] = {}

        # Stock Symbol -> List of Crypto Symbols (for many-to-one tracking)
        self.stock_to_cryptos: Dict[Symbol, List[Symbol]] = {}

        # Already subscribed stocks (Security objects)
        self.stocks: Set[Security] = set()

        # Already subscribed cryptos (Security objects)
        self.cryptos: Set[Security] = set()

        # Data type registry (Symbol -> Type mapping for dynamic data access)
        self.data_types: Dict[Symbol, Type] = {}

        # Note: Position and order management has been moved to BaseStrategy
        # for better separation of concerns and to support multiple strategy instances

    def add_pair(self, crypto: Security, stock: Security):
        """
        Register a crypto-stock trading pair

        Args:
            crypto: Crypto Security object
            stock: Stock Security object

        Side Effects:
            - Adds pair to self.pairs
            - Updates self.stock_to_cryptos for many-to-one tracking
            - Adds securities to self.cryptos and self.stocks

        Example:
            >>> manager.add_pair(crypto, stock)
            >>> pairs = manager.get_all_pairs()
            >>> print(pairs)  # [(TSLAxUSD, TSLA), ...]
        """
        crypto_symbol = crypto.Symbol
        stock_symbol = stock.Symbol

        # Add to pairs mapping
        self.pairs[crypto_symbol] = stock_symbol

        # Update reverse mapping (stock -> list of cryptos)
        if stock_symbol not in self.stock_to_cryptos:
            self.stock_to_cryptos[stock_symbol] = []
        self.stock_to_cryptos[stock_symbol].append(crypto_symbol)

        # Track securities
        self.cryptos.add(crypto)
        self.stocks.add(stock)

        # 写入配对映射到监控后端（通过适配器）
        if self.monitor:
            self.monitor.write_pair_mapping(crypto, stock)

    def subscribe_trading_pair(
        self,
        pair_symbol: Tuple[Symbol, Symbol],
        resolution: Tuple[Type, Resolution] = (OrderbookDepth, Resolution.TICK),
        fee_model: Tuple = (KrakenFeeModel(), InteractiveBrokersFeeModel()),
        leverage_config: Tuple[float, float] = (5.0, 2.0),
        extended_market_hours: bool = False
    ) -> Tuple[Security, Security]:
        """
        订阅并注册交易对（多账户模式）

        封装了完整的交易对初始化流程：
        1. 添加加密货币和股票数据订阅
        2. 设置数据标准化模式为 RAW
        3. 配置 Margin 模式和杠杆倍数
        4. 设置 Fee Model
        5. 自动注册到 SpreadManager

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 元组
            resolution: (data_type, resolution) 元组
                - data_type: 数据类型（如 OrderbookDepth），为 None 时使用默认 add_crypto
                - resolution: 数据分辨率（如 Resolution.TICK）
            fee_model: (crypto_fee_model, stock_fee_model) 元组
            leverage_config: (crypto_leverage, stock_leverage) 元组
            extended_market_hours: 股票是否订阅盘前盘后数据

        Returns:
            (crypto_security, stock_security) 元组

        Example:
            >>> crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
            >>> stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)
            >>> crypto_sec, stock_sec = manager.subscribe_trading_pair(
            ...     pair_symbol=(crypto_symbol, stock_symbol)
            ... )
        """
        # 解构参数
        crypto_symbol, stock_symbol = pair_symbol
        data_type, res = resolution
        crypto_fee, stock_fee = fee_model
        crypto_leverage, stock_leverage = leverage_config

        # === 添加加密货币数据 ===
        if data_type is None:
            # 使用默认 add_crypto
            crypto_security = self.algorithm.add_crypto(
                crypto_symbol.value, res, crypto_symbol.id.market
            )
            # 记录数据类型为 Tick (使用 Security.Symbol 而非参数 Symbol)
            self.data_types[crypto_security.Symbol] = Tick
        else:
            # 使用自定义数据类型（如 OrderbookDepth）
            crypto_security = self.algorithm.add_data(data_type, crypto_symbol, res)
            # 记录自定义数据类型 (使用 Security.Symbol 而非参数 Symbol)
            self.data_types[crypto_security.Symbol] = data_type # Orderbook Depth

        # 设置加密货币配置
        crypto_security.data_normalization_mode = DataNormalizationMode.RAW
        crypto_security.set_buying_power_model(SecurityMarginModel(crypto_leverage))
        crypto_security.fee_model = crypto_fee

        # === 添加股票数据（检查是否已订阅） ===
        if stock_symbol in self.algorithm.securities:
            stock_security = self.algorithm.securities[stock_symbol]
            self.algorithm.Debug(f"Stock {stock_symbol.value} already subscribed, reusing existing security")
        else:
            stock_security = self.algorithm.add_equity(
                stock_symbol.value, res, stock_symbol.id.market,
                extended_market_hours=extended_market_hours
            )
            # 设置股票配置（仅在首次订阅时）
            stock_security.data_normalization_mode = DataNormalizationMode.RAW
            stock_security.set_buying_power_model(SecurityMarginModel(stock_leverage))
            stock_security.fee_model = stock_fee
            # 记录股票数据类型为 Tick (使用 Security.Symbol 而非参数 Symbol)
            self.data_types[stock_security.Symbol] = Tick

        # === 注册交易对 ===
        self.add_pair(crypto_security, stock_security)

        return (crypto_security, stock_security)

    def get_all_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        Get all registered crypto-stock pairs

        Returns:
            List of (crypto_symbol, stock_symbol) tuples

        Example:
            >>> pairs = manager.get_all_pairs()
            >>> for crypto_sym, stock_sym in pairs:
            ...     print(f"{crypto_sym} -> {stock_sym}")
        """
        return list(self.pairs.items())

    def get_cryptos_for_stock(self, stock_symbol: Symbol) -> List[Symbol]:
        """
        !!! 目前没有任何函数引用他
        Get all crypto symbols paired with a given stock (many-to-one relationship)

        Args:
            stock_symbol: Stock Symbol

        Returns:
            List of crypto Symbols paired with this stock

        Example:
            >>> cryptos = manager.get_cryptos_for_stock(tsla_symbol)
            >>> print(cryptos)  # [TSLAxUSD, TSLAON, ...]
        """
        return self.stock_to_cryptos.get(stock_symbol, [])

    def get_pair_symbol_from_crypto(self, crypto_symbol: Symbol) -> Optional[Tuple[Symbol, Symbol]]:
        """
        Get pair symbol from crypto symbol

        Args:
            crypto_symbol: Crypto Symbol

        Returns:
            (crypto_symbol, stock_symbol) tuple, or None if not found
        """
        stock_symbol = self.pairs.get(crypto_symbol)
        if stock_symbol:
            return (crypto_symbol, stock_symbol)
        return None


    @staticmethod
    def calculate_spread_pct(token_bid: float, token_ask: float,
                            stock_bid: float, stock_ask: float) -> float:
        """
        Calculate bidirectional spread percentage for arbitrage opportunities

        Compares two arbitrage scenarios and returns the one with largest absolute value:
        1. Short token, Long stock: (token_bid - stock_ask) / token_bid
        2. Long token, Short stock: (token_ask - stock_bid) / token_ask

        By using (token - stock) consistently, the sign indicates direction:
        - Positive spread: token overpriced → short token, long stock
        - Negative spread: token underpriced → long token, short stock

        Args:
            token_bid: Crypto token best bid price
            token_ask: Crypto token best ask price
            stock_bid: Underlying stock best bid price
            stock_ask: Underlying stock best ask price

        Returns:
            Spread percentage with largest absolute value (preserves sign)

        Example:
            >>> # AAPLx bid=150.5, ask=150.6, AAPL bid=150.0, ask=150.1
            >>> spread = SpreadManager.calculate_spread_pct(150.5, 150.6, 150.0, 150.1)
            >>> # Scenario 1: (150.5 - 150.1) / 150.5 = 0.266%
            >>> # Scenario 2: (150.6 - 150.0) / 150.6 = 0.398%
            >>> # Returns: 0.398 (larger abs value, positive = short token)
        """
        if token_bid == 0 or token_ask == 0:
            return 0.0

        # Scenario 1: Short token (sell at bid), Long stock (buy at ask)
        spread_short_token = ((token_bid - stock_ask) / token_bid)

        # Scenario 2: Long token (buy at ask), Short stock (sell at bid)
        spread_long_token = ((token_ask - stock_bid) / token_ask)

        # Return the spread with largest absolute value (best opportunity)
        if abs(spread_short_token) >= abs(spread_long_token):
            return spread_short_token
        else:
            return spread_long_token

    def on_data(self, data: Slice):
        """
        处理数据更新 - 监控价差

        Args:
            data: Slice对象，包含tick数据
        """
        for crypto_symbol, stock_symbol in self.get_all_pairs():
            # 获取 Security 对象
            if crypto_symbol not in self.algorithm.Securities or stock_symbol not in self.algorithm.Securities:
                continue

            crypto_security = self.algorithm.Securities[crypto_symbol]
            stock_security = self.algorithm.Securities[stock_symbol]

            # 直接使用 Cache 的 BidPrice/AskPrice（自动从 OrderbookDepth 或 Tick 更新）
            crypto_bid = crypto_security.Cache.BidPrice
            crypto_ask = crypto_security.Cache.AskPrice
            stock_bid = stock_security.Cache.BidPrice
            stock_ask = stock_security.Cache.AskPrice

            # 验证价格有效性
            if crypto_bid <= 0 or crypto_ask <= 0 or stock_bid <= 0 or stock_ask <= 0:
                continue

            # 计算spread
            spread_pct = self.calculate_spread_pct(
                float(crypto_bid),
                float(crypto_ask),
                float(stock_bid),
                float(stock_ask)
            )

            # Debug: 检测异常价差
            if abs(spread_pct) > 0.5:  # 超过50%的价差肯定有问题
                self.algorithm.Debug(
                    f"⚠️ 异常价差 {spread_pct*100:.2f}% | "
                    f"{crypto_symbol.Value}: bid={crypto_bid:.2f} ask={crypto_ask:.2f} | "
                    f"{stock_symbol.Value}: bid={stock_bid:.2f} ask={stock_ask:.2f}"
                )

            # 触发策略（简化参数）
            pair_symbol = (crypto_symbol, stock_symbol)
            self.strategy.on_spread_update(pair_symbol, spread_pct)

            # 写入价差数据到监控后端（通过适配器）
            if self.monitor:
                self.monitor.write_spread(pair_symbol, spread_pct)
