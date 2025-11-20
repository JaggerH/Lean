"""
SpreadManager - Core multi-leg pair subscription and spread management

Supports multiple arbitrage pair types:
1. (Crypto, Stock) - tokenized stock spot arbitrage
2. (CryptoFuture, Stock) - tokenized stock futures arbitrage
3. (Crypto, CryptoFuture) - spot-future basis arbitrage

Architecture (2025-11-20 Major Refactoring to use TradingPair):
SpreadManager now leverages LEAN's native TradingPair infrastructure:
- Uses algorithm.AddTradingPair() for pair registration
- Uses algorithm.TradingPairs collection for iteration
- Uses C# TradingPair.Update() for spread calculation
- Provides _adapt_to_spread_signal() for backward compatibility

Code Reduction:
- Deleted SpreadCalculator.calculate_spread_pct() - 80+ lines (now in C# TradingPair)
- Simplified on_data() to use TradingPairs collection
- Simplified calculate_spread_signal() to use TradingPair objects

All public APIs remain unchanged for backward compatibility.

Major Refactoring History:
- 2025-11-20: Migrated to use LEAN's native TradingPair, deleted ~100+ lines of redundant code
- 2025-11-19: Split into 3 classes using Facade pattern (PairSubscriptionManager, PairRegistry, SpreadCalculator)
- 2025-11-19: Fixed pair_mappings to support one-to-many relationships using tuple keys
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

# Try to import TradingPairs (may not be available in all environments)
try:
    from QuantConnect.TradingPairs import TradingPair, MarketState as CSharpMarketState
    HAS_TRADING_PAIRS = True
except ImportError:
    # TradingPairs not available (e.g., in test environment)
    TradingPair = None
    CSharpMarketState = None
    HAS_TRADING_PAIRS = False

# 避免循环导入，仅用于类型检查
if TYPE_CHECKING:
    from monitoring.spread_monitor import RedisSpreadMonitor
    from strategy.base_strategy import BaseStrategy


class MarketState(Enum):
    """
    市场状态分类

    [DEPRECATED - 将逐步迁移到 QuantConnect.TradingPairs.MarketState]
    保留用于向后兼容，新代码应使用 C# 的 MarketState

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

    [DEPRECATED - 将逐步迁移到 QuantConnect.TradingPairs.TradingPair]
    保留用于向后兼容，新代码应直接使用 C# 的 TradingPair 对象

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
        Initialize SpreadManager (Facade Pattern)

        Args:
            algorithm: QCAlgorithm instance for accessing trading APIs

        Architecture (2025-11-19 Refactoring):
            SpreadManager 现在作为 Facade 外观模式，内部委托给三个职责单一的类：
            1. PairSubscriptionManager - 处理 LEAN API 订阅
            2. PairRegistry - 存储和查询交易对映射
            3. SpreadCalculator - 计算价差和通知观察者

            保持向后兼容，所有现有 API 不变。
        """
        self.algorithm = algorithm

        # === Facade Pattern: 组合三个内部类（2025-11-19）===
        self._subscription_mgr = PairSubscriptionManager(algorithm)
        self._registry = PairRegistry()
        self._calculator = SpreadCalculator(algorithm, self._registry)

        # === 向后兼容属性（委托到内部类）===
        # 这些属性用于保持现有代码的兼容性
        self.pair_mappings = self._registry.pair_mappings  # 直接引用内部存储
        self.leg2_to_leg1s = self._registry.leg2_to_leg1s  # 直接引用内部存储

    def _adapt_to_spread_signal(self, trading_pair) -> Optional[SpreadSignal]:
        """
        适配器方法：将 C# TradingPair 对象转换为 Python SpreadSignal

        C# TradingPair 现在直接提供百分比格式的 spread 计算，
        因此此方法只需简单映射属性，无需手动转换。

        Args:
            trading_pair: LEAN 的 TradingPair 对象（已包含百分比格式的 spread）

        Returns:
            SpreadSignal: 转换后的信号对象，如果价格无效返回 None
        """
        if not HAS_TRADING_PAIRS or trading_pair is None:
            return None

        # 检查价格有效性
        if not trading_pair.HasValidPrices:
            return None

        # 映射市场状态
        market_state = self._map_market_state(trading_pair.MarketState, trading_pair)

        # C# TradingPair 现在直接提供百分比格式的 theoretical_spread
        theoretical_spread_pct = float(trading_pair.TheoreticalSpread)

        # C# TradingPair 现在直接提供百分比格式的 executable_spread（如果有机会）
        executable_spread = float(trading_pair.ExecutableSpread) if trading_pair.ExecutableSpread is not None else None

        # C# TradingPair 现在直接提供 Direction（SHORT_SPREAD 或 LONG_SPREAD）
        direction = trading_pair.Direction if trading_pair.Direction != "none" else None

        # 创建 SpreadSignal 对象
        signal = SpreadSignal(
            pair_symbol=(trading_pair.Leg1Symbol, trading_pair.Leg2Symbol),
            market_state=market_state,
            theoretical_spread=theoretical_spread_pct,
            executable_spread=executable_spread,
            direction=direction
        )

        return signal

    def _map_market_state(self, cs_market_state, trading_pair) -> MarketState:
        """
        映射 C# MarketState 枚举到 Python MarketState 枚举

        C# TradingPair 现在直接提供所有市场状态，包括 LIMIT_OPPORTUNITY

        Args:
            cs_market_state: C# 的 MarketState 枚举值
            trading_pair: TradingPair 对象（未使用，保留用于向后兼容）

        Returns:
            MarketState: Python 的 MarketState 枚举值
        """
        if not HAS_TRADING_PAIRS:
            return MarketState.NO_OPPORTUNITY

        # 直接映射 C# MarketState 到 Python MarketState
        if cs_market_state == CSharpMarketState.Crossed:
            return MarketState.CROSSED
        elif cs_market_state == CSharpMarketState.LimitOpportunity:
            return MarketState.LIMIT_OPPORTUNITY
        elif cs_market_state == CSharpMarketState.NoOpportunity:
            return MarketState.NO_OPPORTUNITY
        elif cs_market_state == CSharpMarketState.Normal:
            return MarketState.NO_OPPORTUNITY
        elif cs_market_state == CSharpMarketState.Inverted:
            return MarketState.NO_OPPORTUNITY
        else:  # Unknown
            return MarketState.NO_OPPORTUNITY

    def register_observer(self, callback):
        """
        注册价差观察者（策略回调）- Facade 委托方法

        Args:
            callback: 回调函数，签名为 callback(signal: SpreadSignal)

        Example:
            >>> manager.register_observer(strategy.on_spread_update)
        """
        self._calculator.register_observer(callback)

    def unregister_observer(self, callback):
        """
        注销价差观察者 - Facade 委托方法

        Args:
            callback: 要移除的回调函数

        Example:
            >>> manager.unregister_observer(strategy.on_spread_update)
        """
        self._calculator.unregister_observer(callback)

    def register_pair_observer(self, callback):
        """
        注册 pair 添加事件观察者（监控回调）- Facade 委托方法

        当通过 add_pair() 或 subscribe_trading_pair() 添加新交易对时触发。

        Args:
            callback: 回调函数，签名为 callback(leg1: Security, leg2: Security)

        Example:
            >>> manager.register_pair_observer(monitor.write_pair_mapping)
        """
        self._calculator.register_pair_observer(callback)

    def unregister_pair_observer(self, callback):
        """
        注销 pair 观察者 - Facade 委托方法

        Args:
            callback: 要移除的回调函数

        Example:
            >>> manager.unregister_pair_observer(monitor.write_pair_mapping)
        """
        self._calculator.unregister_pair_observer(callback)

    def _notify_pair_observers(self, leg1: Security, leg2: Security):
        """
        通知所有注册的 pair 观察者 - Facade 委托方法

        Args:
            leg1: Leg1 Security 对象
            leg2: Leg2 Security 对象
        """
        self._calculator.notify_pair_observers(leg1, leg2)

    def _notify_observers(self, signal: SpreadSignal):
        """
        通知所有注册的观察者 - Facade 委托方法

        Args:
            signal: SpreadSignal 对象（包含 pair_symbol 和所有价差信息）
        """
        self._calculator._notify_observers(signal)

    def _detect_pair_type(self, leg1_symbol: Symbol, leg2_symbol: Symbol) -> str:
        """
        自动检测配对类型 - Facade 委托方法

        Args:
            leg1_symbol: 第一条腿的 Symbol
            leg2_symbol: 第二条腿的 Symbol

        Returns:
            str: 配对类型（'crypto_stock' | 'cryptofuture_stock' | 'spot_future'）
        """
        return self._subscription_mgr._detect_pair_type(leg1_symbol, leg2_symbol)

    def add_pair(self, leg1: Security, leg2: Security):
        """
        Register a trading pair - Facade 委托方法（向后兼容）

        注意：此方法已被 subscribe_trading_pair 取代，不推荐直接调用

        Args:
            leg1: 第一条腿的 Security 对象
            leg2: 第二条腿的 Security 对象

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

        # 委托到 PairRegistry
        self._registry.add_pair(leg1, leg2, pair_type)

        # 通知 pair 观察者（如监控系统）
        self._notify_pair_observers(leg1, leg2)

    def subscribe_trading_pair(
        self,
        pair_symbol: Tuple[Symbol, Symbol],
        resolution: Tuple[Resolution, Resolution] = (Resolution.ORDERBOOK, Resolution.TICK),
        fee_model: Tuple = None,
        leverage_config: Tuple[float, float] = (5.0, 2.0),
        extended_market_hours: bool = False
    ) -> Tuple[Security, Security]:
        """
        订阅并注册交易对 - 使用 LEAN 原生 TradingPair（重构 2025-11-20）

        支持 3 种配对模式，自动检测类型：
        1. (Crypto, Stock) - tokenized stock 现货套利
        2. (CryptoFuture, Stock) - tokenized stock 期货套利
        3. (Crypto, CryptoFuture) - spot-future basis 套利

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 元组
            resolution: (leg1_resolution, leg2_resolution) 元组
            fee_model: (leg1_fee_model, leg2_fee_model) 元组，None 表示使用默认
            leverage_config: (leg1_leverage, leg2_leverage) 元组
            extended_market_hours: 股票是否订阅盘前盘后数据（仅对 stock 有效）

        Returns:
            (leg1_security, leg2_security) 元组
        """
        leg1_symbol, leg2_symbol = pair_symbol

        # 步骤 1: 确保证券已经被订阅（使用原有订阅逻辑）
        leg1_sec, leg2_sec = self._subscription_mgr.subscribe_trading_pair(
            pair_symbol=pair_symbol,
            resolution=resolution,
            fee_model=fee_model,
            leverage_config=leverage_config,
            extended_market_hours=extended_market_hours
        )

        # 步骤 2: 使用 LEAN 原生 AddTradingPair 创建交易对（如果可用）
        pair_type = self._detect_pair_type(leg1_symbol, leg2_symbol)

        # 添加到 LEAN 的 TradingPairs 管理器（如果可用）
        if HAS_TRADING_PAIRS and hasattr(self.algorithm, 'AddTradingPair'):
            # 注意：如果交易对已存在，AddTradingPair 会返回现有的
            trading_pair = self.algorithm.AddTradingPair(leg1_symbol, leg2_symbol, pair_type)

        # 步骤 3: 注册到内部 registry（用于向后兼容）
        # 保留这个是为了支持旧的查询方法
        self._registry.add_pair(leg1_sec, leg2_sec, pair_type)

        # 步骤 4: 通知 pair 观察者
        self._notify_pair_observers(leg1_sec, leg2_sec)

        return (leg1_sec, leg2_sec)

    def get_all_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        Get all registered trading pairs - Facade 委托方法

        Returns:
            List of (leg1_symbol, leg2_symbol) tuples
        """
        return self._registry.get_all_pairs()

    def get_leg1s_for_leg2(self, leg2_symbol: Symbol) -> List[Symbol]:
        """
        获取与 leg2 配对的所有 leg1 列表 - Facade 委托方法

        Args:
            leg2_symbol: leg2 的 Symbol

        Returns:
            List[Symbol]: 与该 leg2 配对的所有 leg1
        """
        return self._registry.get_leg1s_for_leg2(leg2_symbol)

    def get_pair_symbols_from_leg1(self, leg1_symbol: Symbol) -> List[Tuple[Symbol, Symbol]]:
        """
        获取包含指定 leg1 的所有交易对 - Facade 委托方法

        Args:
            leg1_symbol: leg1 的 Symbol

        Returns:
            List[Tuple[Symbol, Symbol]]: 所有包含该 leg1 的配对列表
        """
        return self._registry.get_pair_symbols_from_leg1(leg1_symbol)

    def get_pair_symbol_from_leg1(self, leg1_symbol: Symbol) -> Optional[Tuple[Symbol, Symbol]]:
        """
        从 leg1 获取第一个匹配的配对 - Facade 委托方法（向后兼容）

        Args:
            leg1_symbol: leg1 的 Symbol

        Returns:
            (leg1_symbol, leg2_symbol) tuple, or None if not found
        """
        return self._registry.get_pair_symbol_from_leg1(leg1_symbol)

    def get_pair_mapping(self, pair_symbol: Tuple[Symbol, Symbol]) -> Optional[PairMapping]:
        """
        通过完整的 pair_symbol 获取 PairMapping - Facade 委托方法

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 完整配对

        Returns:
            PairMapping 对象，如果不存在则返回 None
        """
        return self._registry.get_pair_mapping(pair_symbol)

    def get_pair_symbols_from_leg2(self, leg2_symbol: Symbol) -> List[Tuple[Symbol, Symbol]]:
        """
        获取包含指定 leg2 的所有交易对 - Facade 委托方法

        Args:
            leg2_symbol: leg2 的 Symbol

        Returns:
            List[Tuple[Symbol, Symbol]]: 所有包含该 leg2 的配对列表
        """
        return self._registry.get_pair_symbols_from_leg2(leg2_symbol)


    @staticmethod
    def calculate_spread_pct(leg1_bid: float, leg1_ask: float,
                            leg2_bid: float, leg2_ask: float) -> dict:
        """
        [DEPRECATED] 计算价差并分类市场状态 - 保留用于测试兼容性

        这个方法已被 TradingPair 的计算取代，保留仅用于向后兼容。

        Args:
            leg1_bid: Leg1 最佳买价
            leg1_ask: Leg1 最佳卖价
            leg2_bid: Leg2 最佳买价
            leg2_ask: Leg2 最佳卖价

        Returns:
            dict: 价差计算结果
        """
        # 简化版实现，仅用于测试兼容性
        if leg1_bid <= 0 or leg1_ask <= 0 or leg2_bid <= 0 or leg2_ask <= 0:
            return {
                "market_state": MarketState.NO_OPPORTUNITY,
                "theoretical_spread": 0.0,
                "executable_spread": None,
                "direction": None
            }

        # 计算理论价差
        short_spread = (leg1_bid - leg2_ask) / leg1_bid if leg1_bid > 0 else 0
        long_spread = (leg1_ask - leg2_bid) / leg1_ask if leg1_ask > 0 else 0
        theoretical_spread = short_spread if abs(short_spread) >= abs(long_spread) else long_spread

        # 检测 CROSSED Market
        if leg1_bid > leg2_ask:
            return {
                "market_state": MarketState.CROSSED,
                "theoretical_spread": theoretical_spread,
                "executable_spread": short_spread,
                "direction": "SHORT_SPREAD"
            }

        if leg2_bid > leg1_ask:
            return {
                "market_state": MarketState.CROSSED,
                "theoretical_spread": theoretical_spread,
                "executable_spread": long_spread,
                "direction": "LONG_SPREAD"
            }

        # 检测 LIMIT_OPPORTUNITY
        if leg1_ask > leg2_ask > leg1_bid > leg2_bid:
            spread_1 = (leg1_ask - leg2_ask) / leg1_ask if leg1_ask > 0 else 0
            spread_2 = (leg1_bid - leg2_bid) / leg1_bid if leg1_bid > 0 else 0
            return {
                "market_state": MarketState.LIMIT_OPPORTUNITY,
                "theoretical_spread": theoretical_spread,
                "executable_spread": max(spread_1, spread_2),
                "direction": "SHORT_SPREAD"
            }

        if leg2_ask > leg1_ask > leg2_bid > leg1_bid:
            spread_1 = (leg1_ask - leg2_bid) / leg1_ask if leg1_ask > 0 else 0
            spread_2 = (leg1_bid - leg2_ask) / leg1_bid if leg1_bid > 0 else 0
            return {
                "market_state": MarketState.LIMIT_OPPORTUNITY,
                "theoretical_spread": theoretical_spread,
                "executable_spread": min(spread_1, spread_2),
                "direction": "LONG_SPREAD"
            }

        # NO_OPPORTUNITY
        return {
            "market_state": MarketState.NO_OPPORTUNITY,
            "theoretical_spread": theoretical_spread,
            "executable_spread": None,
            "direction": None
        }

    def calculate_spread_signal(self, pair_symbol: Tuple[Symbol, Symbol]) -> SpreadSignal:
        """
        计算价差信号 - Facade 委托方法

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 交易对

        Returns:
            SpreadSignal 对象
        """
        return self._calculator.calculate_spread_signal(pair_symbol)

    def on_data(self, data: Slice):
        """
        处理数据更新 - 使用 LEAN 原生 TradingPairs（重构 2025-11-20）

        利用 C# TradingPair 的自动计算功能，减少 Python 端的计算负担。

        Args:
            data: Slice对象，包含tick数据
        """
        # 使用新的实现，直接利用 TradingPairs
        self._on_data_with_trading_pairs(data)

    def _on_data_with_trading_pairs(self, data: Slice):
        """
        使用 LEAN 原生 TradingPairs 处理数据更新

        Args:
            data: Slice对象，包含tick数据
        """
        # 检查 TradingPairs 是否可用
        if not HAS_TRADING_PAIRS or not hasattr(self.algorithm, 'TradingPairs'):
            # 降级到旧实现
            self._calculator.on_data(data)
            return

        # 更新所有 TradingPair 的价差计算
        # 注意：C# 端的 UpdateAll() 会自动调用每个 pair 的 Update()
        self.algorithm.TradingPairs.UpdateAll()

        # 遍历所有交易对，检查套利机会
        for trading_pair in self.algorithm.TradingPairs.Values:
            # 将 TradingPair 转换为 SpreadSignal（向后兼容）
            signal = self._adapt_to_spread_signal(trading_pair)

            if signal and signal.theoretical_spread != 0:
                # 记录有价差的交易对（用于调试和监控）
                if abs(signal.theoretical_spread) > 0.001:  # 0.1% 阈值
                    self.algorithm.Debug(
                        f"📊 {trading_pair.Key}: "
                        f"State={trading_pair.MarketState} "
                        f"Spread={signal.theoretical_spread:.4f} "
                        f"Direction={trading_pair.Direction}"
                    )

                # 通知策略观察者
                self._notify_observers(signal)


# ============================================================================
# NEW REFACTORED CLASSES (2025-11-19)
# Split SpreadManager into 3 single-responsibility classes
# ============================================================================


class PairSubscriptionManager:
    """
    交易对订阅管理器（Single Responsibility: LEAN API Subscription）

    职责：
    - 处理 LEAN 框架的数据订阅 API 调用
    - 配置 Security 属性（Resolution, FeeModel, Leverage, DataNormalizationMode）
    - 自动检测交易对类型
    - 防止重复订阅

    支持的交易对类型：
    - (Crypto, Stock) - tokenized stock 现货套利
    - (CryptoFuture, Stock) - tokenized stock 期货套利
    - (Crypto, CryptoFuture) - spot-future basis 套利
    """

    def __init__(self, algorithm: QCAlgorithm):
        """
        Initialize PairSubscriptionManager

        Args:
            algorithm: QCAlgorithm instance for accessing LEAN subscription APIs
        """
        self.algorithm = algorithm

    def _detect_pair_type(self, leg1_symbol: Symbol, leg2_symbol: Symbol) -> str:
        """
        自动检测配对类型

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

    def subscribe_trading_pair(
        self,
        pair_symbol: Tuple[Symbol, Symbol],
        resolution: Tuple[Resolution, Resolution] = (Resolution.ORDERBOOK, Resolution.TICK),
        fee_model: Tuple = None,
        leverage_config: Tuple[float, float] = (5.0, 2.0),
        extended_market_hours: bool = False
    ) -> Tuple[Security, Security]:
        """
        订阅并注册交易对（主入口）

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

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 元组
            resolution: (leg1_resolution, leg2_resolution) 元组
            fee_model: (leg1_fee_model, leg2_fee_model) 元组，None 表示使用默认
            leverage_config: (leg1_leverage, leg2_leverage) 元组
            extended_market_hours: 股票是否订阅盘前盘后数据（仅对 stock 有效）

        Returns:
            (leg1_security, leg2_security) 元组
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
        订阅 Spot-Future 配对

        支持 (Crypto, CryptoFuture) 双向配对，自动标准化为 (spot, future) 顺序。

        Args:
            leg1_symbol: 第一条腿的 Symbol
            leg2_symbol: 第二条腿的 Symbol
            resolution: (leg1_resolution, leg2_resolution) 元组
            fee_model: (leg1_fee_model, leg2_fee_model) 元组
            leverage_config: (leg1_leverage, leg2_leverage) 元组

        Returns:
            (leg1_security, leg2_security) 元组（按输入顺序返回）
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
        订阅 Crypto-Stock 配对

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


class PairRegistry:
    """
    交易对元数据注册表（Single Responsibility: Pair Storage & Query）

    职责：
    - 存储交易对映射关系 (PairMapping)
    - 提供多维度查询接口（leg1→pairs, leg2→leg1s, pair→mapping）
    - 支持一对多关系（一个 leg1 对应多个 leg2，如跨交易所套利）

    数据结构：
    - pair_mappings: Dict[Tuple[Symbol, Symbol], PairMapping]  # (leg1, leg2) -> PairMapping
    - leg2_to_leg1s: Dict[Symbol, List[Symbol]]  # leg2 -> [leg1s]（多对一反向索引）

    无外部依赖，纯数据结构。
    """

    def __init__(self):
        """Initialize PairRegistry with empty storage"""
        # (leg1_symbol, leg2_symbol) -> PairMapping（支持任意多对多关系）
        self.pair_mappings: Dict[Tuple[Symbol, Symbol], PairMapping] = {}

        # leg2 -> [leg1s]（多对一关系，用于 leg2 去重和查找）
        self.leg2_to_leg1s: Dict[Symbol, List[Symbol]] = {}

    def add_pair(self, leg1: Security, leg2: Security, pair_type: str):
        """
        添加交易对映射到注册表

        Args:
            leg1: 第一条腿的 Security 对象
            leg2: 第二条腿的 Security 对象
            pair_type: 配对类型 ('crypto_stock' | 'cryptofuture_stock' | 'spot_future')

        Side Effects:
            - 创建 PairMapping 并添加到 self.pair_mappings
            - 更新 self.leg2_to_leg1s 多对一映射
        """
        leg1_symbol = leg1.Symbol
        leg2_symbol = leg2.Symbol

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

    def get_all_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        获取所有注册的交易对

        Returns:
            List of (leg1_symbol, leg2_symbol) tuples
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
        """
        return self.leg2_to_leg1s.get(leg2_symbol, [])

    def get_pair_symbols_from_leg1(self, leg1_symbol: Symbol) -> List[Tuple[Symbol, Symbol]]:
        """
        获取包含指定 leg1 的所有交易对（支持一对多）

        现在支持一个 leg1 对应多个 leg2 的场景（如跨交易所套利）

        Args:
            leg1_symbol: leg1 的 Symbol

        Returns:
            List[Tuple[Symbol, Symbol]]: 所有包含该 leg1 的配对列表，如果不存在则返回空列表
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
        """
        pairs = self.get_pair_symbols_from_leg1(leg1_symbol)
        return pairs[0] if pairs else None

    def get_pair_mapping(self, pair_symbol: Tuple[Symbol, Symbol]) -> Optional[PairMapping]:
        """
        通过完整的 pair_symbol 获取 PairMapping

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 完整配对

        Returns:
            PairMapping 对象，如果不存在则返回 None
        """
        return self.pair_mappings.get(pair_symbol)

    def get_pair_symbols_from_leg2(self, leg2_symbol: Symbol) -> List[Tuple[Symbol, Symbol]]:
        """
        获取包含指定 leg2 的所有交易对（多对一的反向查询）

        与 get_leg1s_for_leg2() 类似，但返回完整的配对列表而不是仅 leg1 列表。

        Args:
            leg2_symbol: leg2 的 Symbol

        Returns:
            List[Tuple[Symbol, Symbol]]: 所有包含该 leg2 的配对列表
        """
        return [pair for pair in self.pair_mappings.keys() if pair[1] == leg2_symbol]

    def has_pair(self, pair_symbol: Tuple[Symbol, Symbol]) -> bool:
        """
        检查交易对是否存在于注册表中

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 完整配对

        Returns:
            bool: 是否存在
        """
        return pair_symbol in self.pair_mappings


class SpreadCalculator:
    """
    价差计算器 + 观察者通知器（Single Responsibility: Spread Calculation & Observer Pattern）

    职责：
    - 计算价差并分类市场状态（CROSSED / LIMIT_OPPORTUNITY / NO_OPPORTUNITY）
    - 管理观察者列表（策略回调 + 监控回调）
    - 触发事件通知（spread 更新 + pair 添加）

    依赖：
    - algorithm: 访问 Securities 的 BidPrice/AskPrice
    - registry: 查询交易对映射关系
    """

    def __init__(self, algorithm: QCAlgorithm, registry: PairRegistry):
        """
        Initialize SpreadCalculator

        Args:
            algorithm: QCAlgorithm instance for accessing Security.Cache prices
            registry: PairRegistry instance for querying pair mappings
        """
        self.algorithm = algorithm
        self.registry = registry
        self._pair_observers = []    # pair 事件观察者列表（监控回调）
        self._spread_observers = []  # spread 事件观察者列表（策略回调）

    def register_observer(self, callback):
        """
        注册价差观察者（策略回调）

        Args:
            callback: 回调函数，签名为 callback(signal: SpreadSignal)
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
        """
        if callback in self._pair_observers:
            self._pair_observers.remove(callback)
            callback_name = getattr(callback, '__name__', repr(callback))
            self.algorithm.Debug(f"🗑️ Unregistered pair observer: {callback_name}")

    def notify_pair_observers(self, leg1: Security, leg2: Security):
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

    # [DELETED 2025-11-20: calculate_spread_pct 静态方法已删除]
    # 现在由 C# TradingPair.Update() 自动计算价差
    # 保留 LIMIT_OPPORTUNITY 逻辑在 _adapt_to_spread_signal 中处理

    def calculate_spread_signal(self, pair_symbol: Tuple[Symbol, Symbol]) -> SpreadSignal:
        """
        计算价差信号 - 使用 TradingPair（重构 2025-11-20）

        Args:
            pair_symbol: (leg1_symbol, leg2_symbol) 交易对

        Returns:
            SpreadSignal 对象
        """
        leg1_symbol, leg2_symbol = pair_symbol

        # 获取对应的 TradingPair 对象（如果可用）
        if HAS_TRADING_PAIRS and hasattr(self.algorithm, 'TradingPairs') and self.algorithm.TradingPairs:
            if hasattr(self.algorithm.TradingPairs, 'Values'):
                for tp in self.algorithm.TradingPairs.Values:
                    if tp.Leg1Symbol == leg1_symbol and tp.Leg2Symbol == leg2_symbol:
                        # 更新计算
                        tp.Update()
                        # 使用适配器转换格式
                        spread_manager = self.algorithm.spread_manager if hasattr(self.algorithm, 'spread_manager') else None
                        if spread_manager:
                            return spread_manager._adapt_to_spread_signal(tp)
                        break

        # 如果没找到 TradingPair，返回空信号
        return SpreadSignal(
            pair_symbol=pair_symbol,
            market_state=MarketState.NO_OPPORTUNITY,
            theoretical_spread=0.0,
            executable_spread=None,
            direction=None
        )

    def on_data(self, data: Slice):
        """
        处理数据更新 - 简化版（重构 2025-11-20）

        注意：主要逻辑已移至 SpreadManager._on_data_with_trading_pairs
        这里仅保留向后兼容的最小逻辑

        Args:
            data: Slice对象，包含tick数据
        """
        # [简化：主逻辑已移至使用 TradingPairs 的新实现]
        # 保留最小向后兼容代码
        pass
