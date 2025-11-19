"""
SpreadManager - Core multi-leg pair subscription and spread management

Supports multiple arbitrage pair types:
1. (Crypto, Stock) - tokenized stock spot arbitrage
2. (CryptoFuture, Stock) - tokenized stock futures arbitrage
3. (Crypto, CryptoFuture) - spot-future basis arbitrage

Major Refactoring History:
- 2025-11-19: Unified naming to leg1/leg2, removed redundant data structures
- 2025-11-11: Generalized from crypto-stock to multi-pair support
- 2025-10-23: Implemented two-layer spread signal system
  * Theoretical Spread: continuous monitoring for visualization
  * Executable Spread: condition-based signals for trading
  * Market state classification: CROSSED / LIMIT_OPPORTUNITY / NO_OPPORTUNITY
"""
from AlgorithmImports import *
from typing import Dict, Set, List, Tuple, Optional, TYPE_CHECKING, Type
from enum import Enum
from dataclasses import dataclass
import sys
import os
sys.path.append(os.path.dirname(__file__))
from limit_order_optimizer import LimitOrderOptimizer
from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel
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
class PairMapping:
    """
    交易对映射关系（重构 2025-11-11）

    统一抽象化所有类型的交易对配对关系，支持：
    1. (Crypto, Stock) - tokenized stock 现货套利
    2. (CryptoFuture, Stock) - tokenized stock 期货套利
    3. (Crypto, CryptoFuture) - spot-future basis 套利

    Attributes:
        leg1: 第一条腿的 Symbol（crypto/spot）
        leg2: 第二条腿的 Symbol（stock/future）
        pair_type: 配对类型 ('crypto_stock' | 'cryptofuture_stock' | 'spot_future')
        leg1_security: 第一条腿的 Security 对象
        leg2_security: 第二条腿的 Security 对象
    """
    leg1: Symbol
    leg2: Symbol
    pair_type: str
    leg1_security: Security
    leg2_security: Security


@dataclass
class SpreadSignal:
    """
    价差信号（包含市场状态和可执行价差）

    设计理念（重构 2025-10-23）：
    - pair_symbol: 交易对标识，包含完整上下文
    - theoretical_spread: 理论最大价差，始终有值（用于连续监控和可视化）
    - executable_spread: 可执行价差，只在 CROSSED 市场时有值（LIMIT_OPPORTUNITY 由执行层计算）
    - 移除冗余字段：crossed_bid_ask 和 limit_opportunity_exists 改用 @property 方法
    - 移除价格字段：leg1_bid/ask, leg2_bid/ask（可从 Security.Cache 获取）

    Attributes:
        pair_symbol: (leg1_symbol, leg2_symbol) 交易对
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
    多腿交易对管理器（Multi-leg Pair Manager）

    支持多种套利交易对类型，统一管理订阅、价差计算和事件通知。

    支持的交易对类型：
    - (Crypto, Stock): tokenized stock 现货套利
    - (CryptoFuture, Stock): tokenized stock 期货套利
    - (Crypto, CryptoFuture): spot-future basis 套利

    核心功能：
    - 交易对订阅与自动去重（多对一关系管理）
    - 价差计算与市场状态分类
    - 观察者模式事件通知（策略 + 监控）
    - 直接使用 algorithm.Securities 避免数据冗余

    Example Usage:
        manager = SpreadManager(algorithm)

        # 订阅 spot-future 配对
        spot_sec, future_sec = manager.subscribe_trading_pair(
            pair_symbol=(spot_symbol, future_symbol),
            resolution=(Resolution.ORDERBOOK, Resolution.TICK)
        )

        # 注册观察者
        manager.register_observer(strategy.on_spread_update)
    """

    def __init__(self, algorithm: QCAlgorithm):
        """
        Initialize SpreadManager

        Args:
            algorithm: QCAlgorithm instance for accessing trading APIs

        Note:
            监控功能通过观察者模式实现，使用 register_pair_observer() 和
            register_observer() 注册监控回调。

        Refactored (2025-11-11):
            使用 PairMapping 统一管理所有配对类型，支持：
            - (Crypto, Stock) - tokenized stock 现货套利
            - (CryptoFuture, Stock) - tokenized stock 期货套利
            - (Crypto, CryptoFuture) - spot-future basis 套利
        """
        self.algorithm = algorithm
        self._pair_observers = []    # pair 事件观察者列表（监控回调）
        self._spread_observers = []  # spread 事件观察者列表（策略回调）

        # === 新数据结构（2025-11-19 重构）===
        # (leg1_symbol, leg2_symbol) -> PairMapping（支持任意多对多关系）
        self.pair_mappings: Dict[Tuple[Symbol, Symbol], PairMapping] = {}

        # leg2 -> [leg1s]（多对一关系，用于 stock 去重和查找）
        self.leg2_to_leg1s: Dict[Symbol, List[Symbol]] = {}

        # Note: Position and order management has been moved to BaseStrategy
        # for better separation of concerns and to support multiple strategy instances
        # Note: Security 对象统一从 algorithm.Securities 获取，不再维护副本

    def register_observer(self, callback):
        """
        注册价差观察者（策略回调）

        Args:
            callback: 回调函数，签名为 callback(signal: SpreadSignal)

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

    def register_pair_observer(self, callback):
        """
        注册 pair 添加事件观察者（监控回调）

        当通过 add_pair() 或 subscribe_trading_pair() 添加新交易对时触发。

        Args:
            callback: 回调函数，签名为 callback(leg1: Security, leg2: Security)

        Example:
            >>> manager.register_pair_observer(monitor.write_pair_mapping)
        """
        if callback not in self._pair_observers:
            self._pair_observers.append(callback)
            callback_name = getattr(callback, '__name__', repr(callback))
            self.algorithm.Debug(f"✅ Registered pair observer: {callback_name}")

    def unregister_pair_observer(self, callback):
        """
        注销 pair 观察者

        Args:
            callback: 要移除的回调函数

        Example:
            >>> manager.unregister_pair_observer(monitor.write_pair_mapping)
        """
        if callback in self._pair_observers:
            self._pair_observers.remove(callback)
            callback_name = getattr(callback, '__name__', repr(callback))
            self.algorithm.Debug(f"🗑️ Unregistered pair observer: {callback_name}")

    def _notify_pair_observers(self, leg1: Security, leg2: Security):
        """
        通知所有注册的 pair 观察者

        Args:
            leg1: Leg1 Security 对象
            leg2: Leg2 Security 对象
        """
        for observer in self._pair_observers:
            try:
                observer(leg1, leg2)
            except:
                import traceback
                error_msg = traceback.format_exc()
                self.algorithm.Debug(
                    f"❌ Pair observer error for {leg1.Symbol.Value}<->{leg2.Symbol.Value}: {error_msg}"
                )

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

    def _detect_pair_type(self, leg1_symbol: Symbol, leg2_symbol: Symbol) -> str:
        """
        自动检测配对类型（2025-11-11）

        支持的组合：
        1. (Crypto, CryptoFuture) -> 'spot_future'
        2. (CryptoFuture, Crypto) -> 'spot_future'（自动翻转）
        3. (Crypto, Equity) -> 'crypto_stock'
        4. (CryptoFuture, Equity) -> 'cryptofuture_stock'

        Args:
            leg1_symbol: 第一条腿的 Symbol
            leg2_symbol: 第二条腿的 Symbol

        Returns:
            str: 配对类型（'crypto_stock' | 'cryptofuture_stock' | 'spot_future'）

        Raises:
            ValueError: 如果配对组合不支持

        Example:
            >>> pair_type = manager._detect_pair_type(spot_symbol, future_symbol)
            >>> # 'spot_future'
        """
        type1 = leg1_symbol.SecurityType
        type2 = leg2_symbol.SecurityType

        # Spot-Future 配对（支持双向）
        if {type1, type2} == {SecurityType.Crypto, SecurityType.CryptoFuture}:
            return 'spot_future'

        # Crypto-Stock 配对
        if type1 == SecurityType.Crypto and type2 == SecurityType.Equity:
            return 'crypto_stock'

        # CryptoFuture-Stock 配对
        if type1 == SecurityType.CryptoFuture and type2 == SecurityType.Equity:
            return 'cryptofuture_stock'

        # 未支持的组合
        raise ValueError(
            f"Unsupported pair combination: {type1} ({leg1_symbol.Value}) <-> "
            f"{type2} ({leg2_symbol.Value}). "
            f"Supported: (Crypto, CryptoFuture), (Crypto, Equity), (CryptoFuture, Equity)"
        )

    def add_pair(self, leg1: Security, leg2: Security):
        """
        Register a trading pair（向后兼容方法，已被 subscribe_trading_pair 内部使用）

        注意（2025-11-11 重构）：
        - 此方法已被 subscribe_trading_pair 取代，不推荐直接调用
        - 保留此方法仅为向后兼容，现在内部使用 PairMapping
        - 自动检测配对类型并创建 PairMapping

        Args:
            leg1: 第一条腿的 Security 对象
            leg2: 第二条腿的 Security 对象

        Side Effects:
            - 创建 PairMapping 并添加到 self.pair_mappings
            - 更新 self.leg2_to_leg1s 多对一映射
            - 通知所有注册的 pair 观察者

        Example:
            >>> # 不推荐直接调用，应使用 subscribe_trading_pair
            >>> manager.add_pair(crypto, stock)
        """
        leg1_symbol = leg1.Symbol
        leg2_symbol = leg2.Symbol

        # 自动检测配对类型
        try:
            pair_type = self._detect_pair_type(leg1_symbol, leg2_symbol)
        except ValueError:
            # 如果检测失败，默认为 crypto_stock（向后兼容）
            pair_type = 'crypto_stock'
            self.algorithm.Debug(
                f"⚠️ 无法检测配对类型，默认为 crypto_stock: {leg1_symbol.Value} <-> {leg2_symbol.Value}"
            )

        # 创建 PairMapping
        mapping = PairMapping(
            leg1=leg1_symbol,
            leg2=leg2_symbol,
            pair_type=pair_type,
            leg1_security=leg1,
            leg2_security=leg2
        )

        # 使用 (leg1, leg2) tuple 作为 key（支持一对多关系）
        pair_key = (leg1_symbol, leg2_symbol)
        self.pair_mappings[pair_key] = mapping

        # 更新 leg2 -> [leg1s] 多对一映射
        if leg2_symbol not in self.leg2_to_leg1s:
            self.leg2_to_leg1s[leg2_symbol] = []
        if leg1_symbol not in self.leg2_to_leg1s[leg2_symbol]:
            self.leg2_to_leg1s[leg2_symbol].append(leg1_symbol)

        # 通知 pair 观察者（如监控系统）
        self._notify_pair_observers(leg1, leg2)

    def subscribe_trading_pair(
        self,
        pair_symbol: Tuple[Symbol, Symbol],
        resolution: Tuple[Resolution, Resolution] = (Resolution.ORDERBOOK, Resolution.TICK),
        fee_model: Tuple = None,  # None = 让 Brokerage 自动选择（GateFuturesFeeModel + IBKR）
        leverage_config: Tuple[float, float] = (5.0, 2.0),
        extended_market_hours: bool = False
    ) -> Tuple[Security, Security]:
        """
        订阅并注册交易对（重构 2025-11-11）

        支持 3 种配对模式，自动检测类型：
        1. (Crypto, Stock) - tokenized stock 现货套利
        2. (CryptoFuture, Stock) - tokenized stock 期货套利
        3. (Crypto, CryptoFuture) - spot-future basis 套利

        封装了完整的交易对初始化流程：
        1. 自动检测配对类型
        2. 添加两条腿的数据订阅
        3. 设置数据标准化模式为 RAW
        4. 配置 Margin 模式和杠杆倍数
        5. 设置 Fee Model（支持独立配置）
        6. 创建 PairMapping 并注册到 SpreadManager

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 元组
            resolution: (leg1_resolution, leg2_resolution) 元组
            fee_model: (leg1_fee_model, leg2_fee_model) 元组，None 表示使用默认
            leverage_config: (leg1_leverage, leg2_leverage) 元组
            extended_market_hours: 股票是否订阅盘前盘后数据（仅对 stock 有效）

        Returns:
            (leg1_security, leg2_security) 元组

        Examples:
            >>> # 示例 1: Crypto-Stock 配对
            >>> crypto_symbol = Symbol.Create("AAPLXUSDT", SecurityType.CryptoFuture, Market.Gate)
            >>> stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)
            >>> crypto_sec, stock_sec = manager.subscribe_trading_pair(
            ...     pair_symbol=(crypto_symbol, stock_symbol),
            ...     resolution=(Resolution.ORDERBOOK, Resolution.TICK)
            ... )

            >>> # 示例 2: Spot-Future 配对
            >>> spot_symbol = Symbol.Create("BTCUSDT", SecurityType.Crypto, Market.Gate)
            >>> future_symbol = Symbol.Create("BTCUSDT_PERP", SecurityType.CryptoFuture, Market.Gate)
            >>> spot_sec, future_sec = manager.subscribe_trading_pair(
            ...     pair_symbol=(spot_symbol, future_symbol),
            ...     leverage_config=(1.0, 5.0)
            ... )
        """
        # 步骤 1: 解构参数
        leg1_symbol, leg2_symbol = pair_symbol

        # 处理 fee_model（None = 使用默认）
        if fee_model is None:
            leg1_fee = None
            leg2_fee = InteractiveBrokersFeeModel()  # 默认 IBKR 费用模型（向后兼容）
        else:
            leg1_fee, leg2_fee = fee_model

        # 步骤 2: 自动检测配对类型
        try:
            pair_type = self._detect_pair_type(leg1_symbol, leg2_symbol)
        except ValueError as e:
            self.algorithm.Error(f"配对类型检测失败: {e}")
            raise

        # 步骤 3: 根据类型调用专用订阅方法
        if pair_type == 'spot_future':
            leg1_sec, leg2_sec = self._subscribe_spot_future(
                leg1_symbol, leg2_symbol, resolution, (leg1_fee, leg2_fee), leverage_config
            )
        elif pair_type in ['crypto_stock', 'cryptofuture_stock']:
            leg1_sec, leg2_sec = self._subscribe_crypto_stock(
                leg1_symbol, leg2_symbol, resolution, (leg1_fee, leg2_fee),
                leverage_config, extended_market_hours
            )
        else:
            raise ValueError(f"Unsupported pair type: {pair_type}")

        # 步骤 4: 创建 PairMapping 并注册
        mapping = PairMapping(
            leg1=leg1_symbol,
            leg2=leg2_symbol,
            pair_type=pair_type,
            leg1_security=leg1_sec,
            leg2_security=leg2_sec
        )

        # 使用 (leg1, leg2) tuple 作为 key（支持一对多关系）
        pair_key = (leg1_symbol, leg2_symbol)
        self.pair_mappings[pair_key] = mapping

        # 更新 leg2 -> [leg1s] 多对一映射
        if leg2_symbol not in self.leg2_to_leg1s:
            self.leg2_to_leg1s[leg2_symbol] = []
        if leg1_symbol not in self.leg2_to_leg1s[leg2_symbol]:
            self.leg2_to_leg1s[leg2_symbol].append(leg1_symbol)

        # 步骤 5: 通知 pair 观察者（保持向后兼容）
        self._notify_pair_observers(leg1_sec, leg2_sec)

        self.algorithm.Debug(
            f"✅ Subscribed {pair_type} pair: {leg1_symbol.Value} <-> {leg2_symbol.Value}"
        )

        return (leg1_sec, leg2_sec)

    def _subscribe_spot_future(
        self,
        leg1_symbol: Symbol,
        leg2_symbol: Symbol,
        resolution: Tuple[Resolution, Resolution],
        fee_model: Tuple,
        leverage_config: Tuple[float, float]
    ) -> Tuple[Security, Security]:
        """
        订阅 Spot-Future 配对（2025-11-11）

        支持 (Crypto, CryptoFuture) 双向配对，自动标准化为 (spot, future) 顺序。

        Args:
            leg1_symbol: 第一条腿的 Symbol
            leg2_symbol: 第二条腿的 Symbol
            resolution: (leg1_resolution, leg2_resolution) 元组
            fee_model: (leg1_fee_model, leg2_fee_model) 元组
            leverage_config: (leg1_leverage, leg2_leverage) 元组

        Returns:
            (leg1_security, leg2_security) 元组（按输入顺序返回）

        Example:
            >>> spot_sec, future_sec = manager._subscribe_spot_future(
            ...     spot_symbol, future_symbol,
            ...     (Resolution.ORDERBOOK, Resolution.TICK),
            ...     (None, None),
            ...     (1.0, 5.0)
            ... )
        """
        # 确保顺序: spot 在前, future 在后（内部标准化）
        if leg1_symbol.SecurityType == SecurityType.CryptoFuture:
            # 需要翻转
            spot_symbol, future_symbol = leg2_symbol, leg1_symbol
            spot_res, future_res = resolution[1], resolution[0]
            spot_fee, future_fee = fee_model[1], fee_model[0]
            spot_lev, future_lev = leverage_config[1], leverage_config[0]
            should_flip_result = True
        else:
            # 已经是 spot 在前
            spot_symbol, future_symbol = leg1_symbol, leg2_symbol
            spot_res, future_res = resolution
            spot_fee, future_fee = fee_model
            spot_lev, future_lev = leverage_config
            should_flip_result = False

        # === 订阅 Spot（检查是否已订阅）===
        if spot_symbol in self.algorithm.Securities:
            spot_security = self.algorithm.Securities[spot_symbol]
            self.algorithm.Debug(f"Spot {spot_symbol.Value} already subscribed, reusing existing security")
        else:
            spot_security = self.algorithm.add_crypto(
                spot_symbol.Value, spot_res, spot_symbol.ID.Market
            )
            # 设置配置
            spot_security.DataNormalizationMode = DataNormalizationMode.RAW
            spot_security.SetBuyingPowerModel(SecurityMarginModel(spot_lev))
            if spot_fee is not None:
                spot_security.FeeModel = spot_fee

        # === 订阅 Future（检查是否已订阅）===
        if future_symbol in self.algorithm.Securities:
            future_security = self.algorithm.Securities[future_symbol]
            self.algorithm.Debug(f"Future {future_symbol.Value} already subscribed, reusing existing security")
        else:
            future_security = self.algorithm.add_crypto_future(
                future_symbol.Value, future_res, future_symbol.ID.Market
            )
            # 设置配置
            future_security.DataNormalizationMode = DataNormalizationMode.RAW
            future_security.SetBuyingPowerModel(SecurityMarginModel(future_lev))
            if future_fee is not None:
                future_security.FeeModel = future_fee

        # 返回结果（按输入顺序）
        if should_flip_result:
            return (future_security, spot_security)
        else:
            return (spot_security, future_security)

    def _subscribe_crypto_stock(
        self,
        crypto_symbol: Symbol,
        stock_symbol: Symbol,
        resolution: Tuple[Resolution, Resolution],
        fee_model: Tuple,
        leverage_config: Tuple[float, float],
        extended_market_hours: bool
    ) -> Tuple[Security, Security]:
        """
        订阅 Crypto-Stock 配对（2025-11-11 重构自原 subscribe_trading_pair）

        支持 Crypto 和 CryptoFuture 与 Stock 的配对。

        Args:
            crypto_symbol: Crypto 或 CryptoFuture Symbol
            stock_symbol: Stock Symbol
            resolution: (crypto_resolution, stock_resolution) 元组
            fee_model: (crypto_fee_model, stock_fee_model) 元组
            leverage_config: (crypto_leverage, stock_leverage) 元组
            extended_market_hours: 股票是否订阅盘前盘后数据

        Returns:
            (crypto_security, stock_security) 元组

        Example:
            >>> crypto_sec, stock_sec = manager._subscribe_crypto_stock(
            ...     crypto_symbol, stock_symbol,
            ...     (Resolution.ORDERBOOK, Resolution.TICK),
            ...     (None, InteractiveBrokersFeeModel()),
            ...     (5.0, 2.0),
            ...     True
            ... )
        """
        crypto_res, stock_res = resolution
        crypto_fee, stock_fee = fee_model
        crypto_leverage, stock_leverage = leverage_config

        # === 添加加密货币数据 ===
        security_type = crypto_symbol.SecurityType

        if security_type == SecurityType.Crypto:
            # 现货：使用 add_crypto
            crypto_security = self.algorithm.add_crypto(
                crypto_symbol.Value, crypto_res, crypto_symbol.ID.Market
            )
        elif security_type == SecurityType.CryptoFuture:
            # 期货：使用 add_crypto_future
            crypto_security = self.algorithm.add_crypto_future(
                crypto_symbol.Value, crypto_res, crypto_symbol.ID.Market
            )
        else:
            raise ValueError(f"Unsupported crypto security type: {security_type}")

        # 设置加密货币配置
        crypto_security.DataNormalizationMode = DataNormalizationMode.RAW
        crypto_security.SetBuyingPowerModel(SecurityMarginModel(crypto_leverage))
        if crypto_fee is not None:
            crypto_security.FeeModel = crypto_fee

        # === 添加股票数据（检查是否已订阅）===
        if stock_symbol in self.algorithm.Securities:
            stock_security = self.algorithm.Securities[stock_symbol]
            self.algorithm.Debug(f"Stock {stock_symbol.Value} already subscribed, reusing existing security")
        else:
            stock_security = self.algorithm.add_equity(
                stock_symbol.Value, stock_res, stock_symbol.ID.Market,
                extended_market_hours=extended_market_hours
            )
            # 设置股票配置（仅在首次订阅时）
            stock_security.DataNormalizationMode = DataNormalizationMode.RAW
            stock_security.SetBuyingPowerModel(SecurityMarginModel(stock_leverage))
            stock_security.FeeModel = stock_fee

        return (crypto_security, stock_security)

    def get_all_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        Get all registered trading pairs（重构 2025-11-19）

        包含所有类型的配对：crypto-stock, cryptofuture-stock, spot-future

        Returns:
            List of (leg1_symbol, leg2_symbol) tuples

        Example:
            >>> pairs = manager.get_all_pairs()
            >>> for leg1_sym, leg2_sym in pairs:
            ...     print(f"{leg1_sym} -> {leg2_sym}")
        """
        return list(self.pair_mappings.keys())

    def get_leg1s_for_leg2(self, leg2_symbol: Symbol) -> List[Symbol]:
        """
        获取与 leg2 配对的所有 leg1 列表（多对一关系）

        适用于所有配对类型，例如：
        - 一个 stock 可能对应多个 crypto/cryptofuture
        - 一个 future 可能对应多个 spot（理论上）

        Args:
            leg2_symbol: leg2 的 Symbol

        Returns:
            List[Symbol]: 与该 leg2 配对的所有 leg1

        Example:
            >>> leg1s = manager.get_leg1s_for_leg2(stock_symbol)
            >>> print(leg1s)  # [crypto1, crypto2, ...]
        """
        return self.leg2_to_leg1s.get(leg2_symbol, [])

    def get_pair_symbols_from_leg1(self, leg1_symbol: Symbol) -> List[Tuple[Symbol, Symbol]]:
        """
        获取包含指定 leg1 的所有交易对（支持一对多）

        重构自 get_pair_symbol_from_leg1 (2025-11-19)：
        现在支持一个 leg1 对应多个 leg2 的场景（如跨交易所套利）

        Args:
            leg1_symbol: leg1 的 Symbol

        Returns:
            List[Tuple[Symbol, Symbol]]: 所有包含该 leg1 的配对列表，如果不存在则返回空列表

        Examples:
            >>> # 单个配对场景
            >>> pairs = manager.get_pair_symbols_from_leg1(btc_spot)
            >>> # [(BTC_Spot, BTC_Future_Gate)]

            >>> # 多个配对场景（跨交易所套利）
            >>> pairs = manager.get_pair_symbols_from_leg1(btc_spot_gate)
            >>> # [(BTC_Spot_Gate, BTC_Future_Gate), (BTC_Spot_Gate, BTC_Future_Binance)]
        """
        return [pair for pair in self.pair_mappings.keys() if pair[0] == leg1_symbol]

    def get_pair_symbol_from_leg1(self, leg1_symbol: Symbol) -> Optional[Tuple[Symbol, Symbol]]:
        """
        从 leg1 获取第一个匹配的配对（向后兼容方法）

        ⚠️ 注意：如果一个 leg1 对应多个 leg2，此方法只返回第一个。
        建议使用 get_pair_symbols_from_leg1() 获取所有配对。

        Args:
            leg1_symbol: leg1 的 Symbol

        Returns:
            (leg1_symbol, leg2_symbol) tuple, or None if not found

        Example:
            >>> pair = manager.get_pair_symbol_from_leg1(leg1_symbol)
            >>> print(pair)  # (leg1_symbol, leg2_symbol) 或 None
        """
        pairs = self.get_pair_symbols_from_leg1(leg1_symbol)
        return pairs[0] if pairs else None

    def get_pair_mapping(self, pair_symbol: Tuple[Symbol, Symbol]) -> Optional[PairMapping]:
        """
        通过完整的 pair_symbol 获取 PairMapping（新增 2025-11-19）

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 完整配对

        Returns:
            PairMapping 对象，如果不存在则返回 None

        Example:
            >>> mapping = manager.get_pair_mapping((btc_spot, btc_future))
            >>> if mapping:
            ...     print(mapping.pair_type)  # 'spot_future'
        """
        return self.pair_mappings.get(pair_symbol)

    def get_pair_symbols_from_leg2(self, leg2_symbol: Symbol) -> List[Tuple[Symbol, Symbol]]:
        """
        获取包含指定 leg2 的所有交易对（多对一的反向查询）（新增 2025-11-19）

        与 get_leg1s_for_leg2() 类似，但返回完整的配对列表而不是仅 leg1 列表。

        Args:
            leg2_symbol: leg2 的 Symbol

        Returns:
            List[Tuple[Symbol, Symbol]]: 所有包含该 leg2 的配对列表

        Example:
            >>> # 查找所有与某个 future 配对的 pair
            >>> pairs = manager.get_pair_symbols_from_leg2(btc_future)
            >>> # [(BTC_Spot_Gate, BTC_Future), (BTC_Spot_Binance, BTC_Future)]
        """
        return [pair for pair in self.pair_mappings.keys() if pair[1] == leg2_symbol]


    @staticmethod
    def calculate_spread_pct(leg1_bid: float, leg1_ask: float,
                            leg2_bid: float, leg2_ask: float) -> dict:
        """
        计算价差并分类市场状态（核心计算逻辑，静态方法）

        功能整合（2025-10-23 重构）：
        - 原 calculate_spread_pct：计算理论价差
        - 原 analyze_spread_signal：分类市场状态
        现在合并为一个函数，简化调用

        命名统一（2025-11-19 重构）：
        - leg1: 第一条腿（可以是 crypto, spot, future）
        - leg2: 第二条腿（可以是 stock, future, spot）
        - 通用于所有交易对类型

        价差计算逻辑：
        1. Short spread: (leg1_bid - leg2_ask) / leg1_bid
        2. Long spread: (leg1_ask - leg2_bid) / leg1_ask
        3. Theoretical spread: 取绝对值较大的那个

        市场状态分类（基于价格区间）：
        1. CROSSED Market（立即可执行）:
           - leg1_bid > leg2_ask → SHORT_SPREAD (卖leg1买leg2)
           - leg2_bid > leg1_ask → LONG_SPREAD (买leg1卖leg2)
           - executable_spread = 实际可成交价差

        2. LIMIT_OPPORTUNITY（需要挂单）:
           - leg1_ask > leg2_ask > leg1_bid > leg2_bid → SHORT_SPREAD
           - leg2_ask > leg1_ask > leg2_bid > leg1_bid → LONG_SPREAD
           - executable_spread = None（由执行层根据挂单逻辑计算）

        3. NO_OPPORTUNITY（无套利机会）:
           - 其他价格区间
           - executable_spread = None

        Args:
            leg1_bid: Leg1 最佳买价
            leg1_ask: Leg1 最佳卖价
            leg2_bid: Leg2 最佳买价
            leg2_ask: Leg2 最佳卖价

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
        # 1. 数据验证（检查双侧价格有效性）
        if leg1_bid <= 0 or leg1_ask <= 0 or leg2_bid <= 0 or leg2_ask <= 0:
            return {
                "market_state": MarketState.NO_OPPORTUNITY,
                "theoretical_spread": 0.0,
                "executable_spread": None,
                "direction": None
            }

        # 2. 计算理论价差（始终计算）
        short_spread = (leg1_bid - leg2_ask) / leg1_bid
        long_spread = (leg1_ask - leg2_bid) / leg1_ask
        theoretical_spread = short_spread if abs(short_spread) >= abs(long_spread) else long_spread

        # 3. CROSSED Market（优先级最高，立即可执行）
        if leg1_bid > leg2_ask:
            # 卖 leg1 @ bid，买 leg2 @ ask
            return {
                "market_state": MarketState.CROSSED,
                "theoretical_spread": theoretical_spread,
                "executable_spread": short_spread,
                "direction": "SHORT_SPREAD"
            }

        if leg2_bid > leg1_ask:
            # 买 leg1 @ ask，卖 leg2 @ bid
            return {
                "market_state": MarketState.CROSSED,
                "theoretical_spread": theoretical_spread,
                "executable_spread": long_spread,
                "direction": "LONG_SPREAD"
            }

        # 4. LIMIT_OPPORTUNITY（需要挂单）
        # 场景 1: leg1 偏贵 (leg1_ask > leg2_ask > leg1_bid > leg2_bid)
        if leg1_ask > leg2_ask > leg1_bid > leg2_bid:
            spread_1 = (leg1_ask - leg2_ask) / leg1_ask
            spread_2 = (leg1_bid - leg2_bid) / leg1_bid
            return {
                "market_state": MarketState.LIMIT_OPPORTUNITY,
                "theoretical_spread": theoretical_spread,
                "executable_spread": max(spread_1, spread_2),  # 由执行层计算
                "direction": "SHORT_SPREAD"
            }

        # 场景 2: leg1 偏便宜 (leg2_ask > leg1_ask > leg2_bid > leg1_bid)
        if leg2_ask > leg1_ask > leg2_bid > leg1_bid:
            spread_1 = (leg1_ask - leg2_bid) / leg1_ask
            spread_2 = (leg1_bid - leg2_ask) / leg1_bid
            return {
                "market_state": MarketState.LIMIT_OPPORTUNITY,
                "theoretical_spread": theoretical_spread,
                "executable_spread": min(spread_1, spread_2),  # 由执行层计算
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
            pair_symbol: (leg1_symbol, leg2_symbol) 交易对

        Returns:
            SpreadSignal 对象（包含 pair_symbol 和所有价差信息）

        Example:
            >>> signal = manager.calculate_spread_signal((leg1_symbol, leg2_symbol))
            >>> signal.pair_symbol  # (leg1_symbol, leg2_symbol)
            >>> signal.theoretical_spread  # 0.00398 (0.398%)
        """
        leg1_symbol, leg2_symbol = pair_symbol

        # 1. 获取 Security 对象
        leg1_security = self.algorithm.Securities[leg1_symbol]
        leg2_security = self.algorithm.Securities[leg2_symbol]

        # 2. 从 Cache 获取价格
        leg1_bid = leg1_security.Cache.BidPrice
        leg1_ask = leg1_security.Cache.AskPrice
        leg2_bid = leg2_security.Cache.BidPrice
        leg2_ask = leg2_security.Cache.AskPrice

        # 3. 调用静态方法计算（核心逻辑）
        result = self.calculate_spread_pct(
            float(leg1_bid), float(leg1_ask),
            float(leg2_bid), float(leg2_ask)
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
        for leg1_symbol, leg2_symbol in self.get_all_pairs():
            pair_symbol = (leg1_symbol, leg2_symbol)

            # 验证 Security 对象存在
            if leg1_symbol not in self.algorithm.Securities:
                continue
            if leg2_symbol not in self.algorithm.Securities:
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
                leg1_security = self.algorithm.Securities[leg1_symbol]
                leg2_security = self.algorithm.Securities[leg2_symbol]
                self.algorithm.Debug(
                    f"⚠️ 异常价差 {signal.theoretical_spread*100:.2f}% | "
                    f"{leg1_symbol.Value}: bid={leg1_security.Cache.BidPrice:.2f} ask={leg1_security.Cache.AskPrice:.2f} | "
                    f"{leg2_symbol.Value}: bid={leg2_security.Cache.BidPrice:.2f} ask={leg2_security.Cache.AskPrice:.2f}"
                )

            # 4. 通知策略（只传 signal，包含完整上下文）
            self._notify_observers(signal)
