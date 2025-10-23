"""
SpreadManager - Core position and subscription management for crypto-stock arbitrage

Manages many-to-one relationships between crypto tokens (e.g., TSLAx on Kraken)
and underlying stocks (e.g., TSLA on IBKR).

Major Refactoring (2025-10-23):
- Implemented two-layer spread signal system:
  1. Theoretical Spread: continuous monitoring for visualization
  2. Executable Spread: condition-based signals for trading
- Added market state classification: CROSSED / LIMIT_OPPORTUNITY / NO_OPPORTUNITY
"""
from AlgorithmImports import *
from typing import Dict, Set, List, Tuple, Optional, TYPE_CHECKING, Type
from enum import Enum
from dataclasses import dataclass
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


class MarketState(Enum):
    """
    市场状态分类

    CROSSED: 交叉市场，存在立即可执行的无风险套利（Market Order）
    LIMIT_OPPORTUNITY: 通过 Limit Order + Market Order 存在套利机会
    NO_OPPORTUNITY: 完全不存在套利机会
    """
    CROSSED = "crossed"
    LIMIT_OPPORTUNITY = "limit"
    NO_OPPORTUNITY = "none"


@dataclass
class SpreadSignal:
    """
    价差信号（简化版 - 包含市场状态和可执行价差）

    设计理念（重构 2025-10-23）：
    - pair_symbol: 交易对标识，包含完整上下文
    - theoretical_spread: 理论最大价差，始终有值（用于连续监控和可视化）
    - executable_spread: 可执行价差，只在 CROSSED 市场时有值（LIMIT_OPPORTUNITY 由执行层计算）
    - 移除冗余字段：crossed_bid_ask 和 limit_opportunity_exists 改用 @property 方法
    - 移除价格字段：token_bid/ask, stock_bid/ask（可从 Security.Cache 获取）

    Attributes:
        pair_symbol: (crypto_symbol, stock_symbol) 交易对
        market_state: 市场状态（CROSSED / LIMIT_OPPORTUNITY / NO_OPPORTUNITY）
        theoretical_spread: 理论最大价差（用于监控和可视化，始终有值）
        executable_spread: 可执行价差（仅在 CROSSED 市场时非 None）
        direction: 交易方向（"LONG_SPREAD" 或 "SHORT_SPREAD"，无机会时为 None）
    """
    pair_symbol: Tuple[Symbol, Symbol]
    market_state: MarketState
    theoretical_spread: float
    executable_spread: Optional[float]
    direction: Optional[str]

    @property
    def is_crossed(self) -> bool:
        """是否为交叉市场（立即可执行）"""
        return self.market_state == MarketState.CROSSED

    @property
    def has_limit_opportunity(self) -> bool:
        """是否存在限价机会（需要挂单）"""
        return self.market_state == MarketState.LIMIT_OPPORTUNITY

    @property
    def is_executable(self) -> bool:
        """是否有可执行价差（CROSSED 市场）"""
        return self.executable_spread is not None


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

    def __init__(self, algorithm: QCAlgorithm,
                 monitor_adapter: Optional['RedisSpreadMonitor'] = None):
        """
        Initialize SpreadManager

        Args:
            algorithm: QCAlgorithm instance for accessing trading APIs
            monitor_adapter: 监控适配器实例 (可选，如 RedisSpreadMonitor)
        """
        self.algorithm = algorithm
        self.monitor = monitor_adapter  # 监控适配器（依赖注入）
        self._spread_observers = []  # 价差观察者列表（策略回调）

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

    def register_observer(self, callback):
        """
        注册价差观察者（策略回调）

        Args:
            callback: 回调函数，签名为 callback(pair_symbol, spread_pct)

        Example:
            >>> manager.register_observer(strategy.on_spread_update)
        """
        if callback not in self._spread_observers:
            self._spread_observers.append(callback)
            callback_name = getattr(callback, '__name__', repr(callback))
            self.algorithm.Debug(f"✅ Registered spread observer: {callback_name}")

    def unregister_observer(self, callback):
        """
        注销价差观察者

        Args:
            callback: 要移除的回调函数

        Example:
            >>> manager.unregister_observer(strategy.on_spread_update)
        """
        if callback in self._spread_observers:
            self._spread_observers.remove(callback)
            callback_name = getattr(callback, '__name__', repr(callback))
            self.algorithm.Debug(f"🗑️ Unregistered spread observer: {callback_name}")

    def _notify_observers(self, signal: SpreadSignal):
        """
        通知所有注册的观察者

        Args:
            signal: SpreadSignal 对象（包含 pair_symbol 和所有价差信息）
        """
        for observer in self._spread_observers:
            try:
                observer(signal)
            except:
                import traceback
                error_msg = traceback.format_exc()
                pair_symbol = signal.pair_symbol
                self.algorithm.Debug(
                    f"❌ Observer error for {pair_symbol[0].Value}<->{pair_symbol[1].Value}: {error_msg}"
                )

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
        resolution: Tuple[Resolution, Resolution] = (Resolution.ORDERBOOK, Resolution.TICK),
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
            resolution: (crypto_resolution, stock_resolution) 元组
                - crypto_resolution: 加密货币数据分辨率（如 Resolution.ORDERBOOK, Resolution.TICK）
                - stock_resolution: 股票数据分辨率（如 Resolution.TICK）
            fee_model: (crypto_fee_model, stock_fee_model) 元组
            leverage_config: (crypto_leverage, stock_leverage) 元组
            extended_market_hours: 股票是否订阅盘前盘后数据

        Returns:
            (crypto_security, stock_security) 元组

        Example:
            >>> crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
            >>> stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)
            >>> # 订阅 Orderbook 深度数据
            >>> crypto_sec, stock_sec = manager.subscribe_trading_pair(
            ...     pair_symbol=(crypto_symbol, stock_symbol),
            ...     resolution=(Resolution.ORDERBOOK, Resolution.TICK)
            ... )
        """
        # 解构参数
        crypto_symbol, stock_symbol = pair_symbol
        crypto_res, stock_res = resolution
        crypto_fee, stock_fee = fee_model
        crypto_leverage, stock_leverage = leverage_config

        # === 添加加密货币数据 ===
        # 使用 add_crypto，支持 Resolution.ORDERBOOK 和其他 Resolution
        crypto_security = self.algorithm.add_crypto(
            crypto_symbol.value, crypto_res, crypto_symbol.id.market
        )

        # 记录数据类型（根据 Resolution 判断）
        if crypto_res == Resolution.ORDERBOOK:
            self.data_types[crypto_security.Symbol] = OrderbookDepth
        else:
            self.data_types[crypto_security.Symbol] = Tick

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
                stock_symbol.value, stock_res, stock_symbol.id.market,
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
                            stock_bid: float, stock_ask: float) -> dict:
        """
        计算价差并分类市场状态（核心计算逻辑，静态方法）

        功能整合（2025-10-23 重构）：
        - 原 calculate_spread_pct：计算理论价差
        - 原 analyze_spread_signal：分类市场状态
        现在合并为一个函数，简化调用

        价差计算逻辑：
        1. Short spread: (token_bid - stock_ask) / token_bid
        2. Long spread: (token_ask - stock_bid) / token_ask
        3. Theoretical spread: 取绝对值较大的那个

        市场状态分类（基于价格区间）：
        1. CROSSED Market（立即可执行）:
           - token_bid > stock_ask → SHORT_SPREAD (卖token买stock)
           - stock_bid > token_ask → LONG_SPREAD (买token卖stock)
           - executable_spread = 实际可成交价差

        2. LIMIT_OPPORTUNITY（需要挂单）:
           - token_ask > stock_ask > token_bid > stock_bid → SHORT_SPREAD
           - stock_ask > token_ask > stock_bid > token_bid → LONG_SPREAD
           - executable_spread = None（由执行层根据挂单逻辑计算）

        3. NO_OPPORTUNITY（无套利机会）:
           - 其他价格区间
           - executable_spread = None

        Args:
            token_bid: Token 最佳买价
            token_ask: Token 最佳卖价
            stock_bid: Stock 最佳买价
            stock_ask: Stock 最佳卖价

        Returns:
            dict: 价差计算结果，包含以下键：
                - market_state: MarketState - 市场状态
                - theoretical_spread: float - 理论价差（始终有值）
                - executable_spread: Optional[float] - 可执行价差（CROSSED 时有值）
                - direction: Optional[str] - 交易方向

        Example:
            >>> result = SpreadManager.calculate_spread_pct(150.5, 150.6, 150.0, 150.1)
            >>> result["market_state"]  # MarketState.CROSSED
            >>> result["theoretical_spread"]  # 0.00398 (0.398%)
            >>> result["executable_spread"]  # 0.00265 (0.265%)
            >>> result["direction"]  # "SHORT_SPREAD"
        """
        # 1. 数据验证
        if token_bid <= 0 or token_ask <= 0:
            return {
                "market_state": MarketState.NO_OPPORTUNITY,
                "theoretical_spread": 0.0,
                "executable_spread": None,
                "direction": None
            }

        # 2. 计算理论价差（始终计算）
        short_spread = (token_bid - stock_ask) / token_bid
        long_spread = (token_ask - stock_bid) / token_ask
        theoretical_spread = short_spread if abs(short_spread) >= abs(long_spread) else long_spread

        # 3. CROSSED Market（优先级最高，立即可执行）
        if token_bid > stock_ask:
            # 卖 token @ bid，买 stock @ ask
            return {
                "market_state": MarketState.CROSSED,
                "theoretical_spread": theoretical_spread,
                "executable_spread": short_spread,
                "direction": "SHORT_SPREAD"
            }

        if stock_bid > token_ask:
            # 买 token @ ask，卖 stock @ bid
            return {
                "market_state": MarketState.CROSSED,
                "theoretical_spread": theoretical_spread,
                "executable_spread": long_spread,
                "direction": "LONG_SPREAD"
            }

        # 4. LIMIT_OPPORTUNITY（需要挂单）
        # 场景 1: token 偏贵 (token_ask > stock_ask > token_bid > stock_bid)
        if token_ask > stock_ask > token_bid > stock_bid:
            return {
                "market_state": MarketState.LIMIT_OPPORTUNITY,
                "theoretical_spread": theoretical_spread,
                "executable_spread": None,  # 由执行层计算
                "direction": "SHORT_SPREAD"
            }

        # 场景 2: token 偏便宜 (stock_ask > token_ask > stock_bid > token_bid)
        if stock_ask > token_ask > stock_bid > token_bid:
            return {
                "market_state": MarketState.LIMIT_OPPORTUNITY,
                "theoretical_spread": theoretical_spread,
                "executable_spread": None,  # 由执行层计算
                "direction": "LONG_SPREAD"
            }

        # 5. NO_OPPORTUNITY（其他价格区间）
        return {
            "market_state": MarketState.NO_OPPORTUNITY,
            "theoretical_spread": theoretical_spread,
            "executable_spread": None,
            "direction": None
        }

    def calculate_spread_signal(self, pair_symbol: Tuple[Symbol, Symbol]) -> SpreadSignal:
        """
        计算价差信号（生产环境接口，实例方法）

        封装了完整的价差计算流程：
        1. 从 Security Cache 获取 bid/ask 价格
        2. 调用静态方法 calculate_spread_pct 进行核心计算
        3. 构造包含 pair_symbol 的 SpreadSignal 对象

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 交易对

        Returns:
            SpreadSignal 对象（包含 pair_symbol 和所有价差信息）

        Example:
            >>> signal = manager.calculate_spread_signal((crypto_symbol, stock_symbol))
            >>> signal.pair_symbol  # (crypto_symbol, stock_symbol)
            >>> signal.theoretical_spread  # 0.00398 (0.398%)
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 1. 获取 Security 对象
        crypto_security = self.algorithm.Securities[crypto_symbol]
        stock_security = self.algorithm.Securities[stock_symbol]

        # 2. 从 Cache 获取价格
        crypto_bid = crypto_security.Cache.BidPrice
        crypto_ask = crypto_security.Cache.AskPrice
        stock_bid = stock_security.Cache.BidPrice
        stock_ask = stock_security.Cache.AskPrice

        # 3. 调用静态方法计算（核心逻辑）
        result = self.calculate_spread_pct(
            float(crypto_bid), float(crypto_ask),
            float(stock_bid), float(stock_ask)
        )

        # 4. 构造 SpreadSignal（添加 pair_symbol）
        return SpreadSignal(
            pair_symbol=pair_symbol,
            **result
        )

    def on_data(self, data: Slice):
        """
        处理数据更新 - 监控价差（简化重构版）

        简化设计（2025-10-23）：
        1. 调用 calculate_spread_signal 计算价差并分类市场状态（封装价格获取）
        2. 写入理论价差到监控后端（用于连续可视化）
        3. 通知策略（传递完整的 SpreadSignal 对象）

        Args:
            data: Slice对象，包含tick数据
        """
        for crypto_symbol, stock_symbol in self.get_all_pairs():
            pair_symbol = (crypto_symbol, stock_symbol)

            # 验证 Security 对象存在
            if crypto_symbol not in self.algorithm.Securities:
                continue
            if stock_symbol not in self.algorithm.Securities:
                continue

            # 1. 计算价差信号（封装了价格获取和计算）
            try:
                signal = self.calculate_spread_signal(pair_symbol)
            except Exception as e:
                # 捕获价格获取异常（如价格无效）
                continue

            # 2. 验证价格有效性（通过检查 theoretical_spread）
            if signal.theoretical_spread == 0.0 and signal.market_state == MarketState.NO_OPPORTUNITY:
                continue

            # 3. Debug: 检测异常价差
            if abs(signal.theoretical_spread) > 0.5:  # 超过50%的价差肯定有问题
                crypto_security = self.algorithm.Securities[crypto_symbol]
                stock_security = self.algorithm.Securities[stock_symbol]
                self.algorithm.Debug(
                    f"⚠️ 异常价差 {signal.theoretical_spread*100:.2f}% | "
                    f"{crypto_symbol.Value}: bid={crypto_security.Cache.BidPrice:.2f} ask={crypto_security.Cache.AskPrice:.2f} | "
                    f"{stock_symbol.Value}: bid={stock_security.Cache.BidPrice:.2f} ask={stock_security.Cache.AskPrice:.2f}"
                )

            # 4. 写入理论价差到监控后端（用于连续可视化）
            if self.monitor:
                self.monitor.write_spread(pair_symbol, signal.theoretical_spread)

            # 5. 通知策略（只传 signal，包含完整上下文）
            self._notify_observers(signal)

            # 5. 额外记录可执行机会到监控后端（仅在有可执行机会时）
            if signal.executable_spread is not None and self.monitor:
                self.algorithm.Debug(
                    f"📊 {signal.market_state.value.upper()} | "
                    f"{crypto_symbol.Value}<->{stock_symbol.Value} | "
                    f"Executable: {signal.executable_spread*100:.2f}% | "
                    f"Direction: {signal.direction}"
                )
