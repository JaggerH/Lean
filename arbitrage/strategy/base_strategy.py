"""
Base Strategy - 套利策略基类

提供基础工具方法和抽象接口，供具体策略继承和扩展
"""
from AlgorithmImports import *
from typing import Tuple


class BaseStrategy:
    """
    套利策略基类（简化版）

    职责:
    - 提供基础的工具方法（验证、调试）
    - 定义策略接口（on_spread_update, on_order_event）

    子类需要实现:
    - on_spread_update(): 处理价差更新的具体逻辑
    """

    def __init__(self, algorithm: QCAlgorithm, debug: bool = False):
        """
        初始化基础策略

        Args:
            algorithm: QCAlgorithm实例
            debug: 是否输出debug日志 (默认False)
        """
        self.algorithm = algorithm
        self.debug = debug

    def _debug(self, message: str):
        """
        条件debug输出

        Args:
            message: Debug消息
        """
        if self.debug:
            self.algorithm.debug(message)

    def _validate_order_preconditions(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                                       action: str = "order") -> Tuple[bool, str]:
        """
        验证下单前置条件

        检查项:
        1. Crypto security 是否有数据 (HasData)
        2. Stock security 是否有数据 (HasData)
        3. 价格是否有效 (> 0)

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            action: 操作描述 (用于日志，如 "open" / "close")

        Returns:
            (is_valid, error_message): 验证通过返回 (True, "")，失败返回 (False, "原因")
        """
        # 1. 检查 crypto 是否有数据
        crypto_security = self.algorithm.securities[crypto_symbol]
        if not crypto_security.has_data:
            msg = f"⚠️ Cannot {action} - crypto {crypto_symbol.value} has no data yet"
            self._debug(msg)
            return (False, msg)

        # 2. 检查 stock 是否有数据
        stock_security = self.algorithm.securities[stock_symbol]
        if not stock_security.has_data:
            msg = f"⚠️ Cannot {action} - stock {stock_symbol.value} has no data yet"
            self._debug(msg)
            return (False, msg)

        # 3. 检查价格是否有效
        if crypto_security.price <= 0 or stock_security.price <= 0:
            msg = f"⚠️ Cannot {action} - invalid prices (crypto: {crypto_security.price}, stock: {stock_security.price})"
            self._debug(msg)
            return (False, msg)

        # 所有检查通过
        return (True, "")

    def on_spread_update(self, signal):
        """
        处理价差更新 - 由子类实现具体策略逻辑

        Args:
            signal: SpreadSignal 对象（包含 pair_symbol, theoretical_spread 等所有价差信息）
        """
        raise NotImplementedError("Subclass must implement on_spread_update()")

    def on_order_event(self, order_event):
        """
        处理订单事件 - 由子类覆盖

        Args:
            order_event: OrderEvent 对象
        """
        pass


# ============================================================================
#                      向后兼容 - 已废弃的方法说明
# ============================================================================
#
# 以下功能已从 BaseStrategy 移除，因为在 GridStrategy 中完全未使用：
#
# ❌ 移除的属性:
#    - positions: Dict[Tuple[Symbol, Symbol], Tuple[float, float]]
#    - order_to_pair: Dict[int, Dict]
#    - state_persistence: StatePersistence
#
# ❌ 移除的方法:
#    - get_pair_position(), update_pair_position()
#    - register_orders(), get_pair_by_order_id()
#    - _open_position(), _close_position()
#    - _should_open_position(), _should_close_position()
#    - restore_state(), _sync_open_orders(), _get_symbol_from_string()
#
# ✅ 替代方案:
#    - ExecutionManager: 订单管理和执行
#    - GridPositionManager: 持仓管理
#    - StatePersistence (通过 MonitoringContext): 状态持久化
#      - 只保存 grid_positions 和 execution_targets
#      - 不再保存 positions 和 order_to_pair
#
# 📚 详细说明:
#
# 1. positions - 交易对持仓追踪
#    旧功能: {(crypto_symbol, stock_symbol): (crypto_qty, stock_qty)}
#    替代: GridPositionManager.grid_positions
#    原因: GridStrategy 使用网格持仓管理，不需要简单的 pair 持仓追踪
#
# 2. order_to_pair - 订单映射
#    旧功能: {order_id: {"pair": (Symbol, Symbol), "filled_qty_snapshot": float}}
#    替代: ExecutionManager.active_targets (通过 ExecutionTarget 管理订单组)
#    原因: 网格交易使用 ExecutionTarget 封装订单组，提供更丰富的状态管理
#
# 3. _open_position() / _close_position() - 开仓/平仓
#    旧功能: 直接调用 SpreadMarketOrder
#    替代: ExecutionManager.execute(ExecutionTarget)
#    原因: 网格交易需要更复杂的执行逻辑（limit order、retry、partial fill处理等）
#
# 4. restore_state() - 状态恢复
#    旧功能: 恢复 positions 和 order_to_pair
#    替代: MonitoringContext + StatePersistence（恢复 grid_positions 和 execution_targets）
#    原因:
#      - 券商账户可以恢复 positions（通过 BrokerageRecoverySetupHandler）
#      - 只需要恢复券商无法提供的状态（网格配置相关）
#
# 📖 如果您需要查看旧版实现，请使用 Git 历史:
#    git log --all --full-history -- arbitrage/strategy/base_strategy.py
#    git show <commit-hash>:arbitrage/strategy/base_strategy.py
#
# ============================================================================
