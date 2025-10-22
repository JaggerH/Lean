"""
Grid Order Tracker - Grid 框架专用的订单追踪器

功能:
1. ExecutionTarget 追踪 - 记录每次 GridLevel 触发的执行目标及其状态变化
2. OrderGroup 追踪 - ExecutionTarget 内的订单组（可能多次提交）
3. Portfolio Snapshot - 每次 ExecutionTarget 终止状态时记录账户快照
4. GridPosition Snapshot - 记录网格持仓状态

数据层次:
    GridLevel (配置)
       ↓ 触发
    ExecutionTarget (执行目标 - 有状态)
       ├─ order_groups: List[OrderGroup]
       └─ status: ExecutionStatus
          ↓
    OrderGroup (订单组 - 一次提交的配对订单)
       ├─ order_tickets: List[OrderTicket]
       ├─ type: OrderGroupType
       └─ status: OrderGroupStatus
          ↓
    OrderTicket (单个订单票据 - LEAN 原生)

注意:
- 本追踪器只负责记录ExecutionTarget事件,不做Entry-Exit配对逻辑
- Round Trip计算应由前端或分析工具根据ExecutionTarget历史计算
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict
import json


# ============================================================================
#                      数据结构定义
# ============================================================================

@dataclass
class OrderSnapshot:
    """单个订单快照"""
    order_id: int
    symbol: str
    direction: str  # "BUY" | "SELL"
    quantity: float
    fill_price: float
    fee: float
    status: str
    time: str  # YYYY-mm-dd HH:MM:SS format

    @classmethod
    def from_order_event(cls, order_event: OrderEvent):
        """从 OrderEvent 创建快照"""
        return cls(
            order_id=order_event.order_id,
            symbol=str(order_event.symbol.value),
            direction="BUY" if order_event.quantity > 0 else "SELL",
            quantity=abs(order_event.fill_quantity),
            fill_price=order_event.fill_price,
            fee=order_event.order_fee.value.amount if order_event.order_fee else 0.0,
            status=str(order_event.status),
            time=order_event.utc_time.strftime("%Y-%m-%d %H:%M:%S")
        )


@dataclass
class OrderGroupSnapshot:
    """OrderGroup 快照"""
    type: str  # "MarketOrder" | "LimitOrder" | ...
    status: str  # OrderGroupStatus

    # 价差
    expected_spread_pct: float
    actual_spread_pct: Optional[float]

    # 订单列表
    orders: List[OrderSnapshot]

    # 成交汇总
    filled_qty: Tuple[float, float]  # (crypto_qty, stock_qty)
    total_fee: float


@dataclass
class ExecutionTargetSnapshot:
    """ExecutionTarget 快照（某个时刻的状态）"""
    grid_id: str
    level_type: str  # "ENTRY" | "EXIT"
    status: str  # ExecutionStatus
    timestamp: str  # YYYY-mm-dd HH:MM:SS format

    # 目标数量
    target_qty: Dict[str, float]  # {symbol: qty}

    # OrderGroup 列表
    order_groups: List[OrderGroupSnapshot]

    # 成交汇总
    total_filled_qty: Tuple[float, float]  # (crypto_qty, stock_qty)
    total_cost: float  # 总成本/收入（包含手续费）
    total_fee: float = 0.0  # 总手续费（账户货币）


@dataclass
class PortfolioSnapshot:
    """Portfolio 快照（在 ExecutionTarget 终止状态时记录）"""
    timestamp: str  # YYYY-mm-dd HH:MM:SS format
    execution_target_id: str  # 关联的 ExecutionTarget grid_id

    # LEAN PnL
    lean_pnl: Dict[str, float]  # {"total_unrealized": ..., "total_net": ...}

    # 账户状态
    accounts: Dict[str, Any]  # {account_name: {cash, holdings, ...}}


@dataclass
class GridPositionSnapshot:
    """网格持仓快照"""
    grid_id: str  # 网格线ID
    pair_symbol: Tuple[str, str]  # (leg1, leg2)
    level_type: str  # "ENTRY" | "EXIT"
    spread_pct: float  # 网格线触发价差

    # 持仓数量
    leg1_qty: float
    leg2_qty: float

    # 时间戳
    timestamp: str


# ============================================================================
#                      GridOrderTracker 主类
# ============================================================================

class GridOrderTracker:
    """
    Grid 框架专用的订单追踪器

    追踪粒度：
    1. ExecutionTarget 级别 - 每次 GridLevel 触发的执行目标及其状态变化
    2. OrderGroup 级别 - ExecutionTarget 内的订单组（可能多次提交）
    3. Portfolio Snapshot - ExecutionTarget 终止状态时记录账户快照
    4. GridPosition Snapshot - 记录网格持仓状态

    注意：不做Entry-Exit配对，Round Trip计算交由前端/分析工具处理
    """

    def __init__(self, algorithm: QCAlgorithm, strategy=None, debug: bool = False,
                 realtime_mode: bool = False, redis_client=None):
        """
        初始化 GridOrderTracker

        Args:
            algorithm: QCAlgorithm 实例
            strategy: GridStrategy 实例（用于访问 GridPositionManager）
            debug: 是否启用调试日志
            realtime_mode: 是否为实时模式（Live/Paper），实时模式下会写入 Redis
            redis_client: TradingRedis 客户端实例（可选，仅实时模式需要）
        """
        self.algorithm = algorithm
        self.strategy = strategy
        self.debug_enabled = debug
        self.realtime_mode = realtime_mode
        self.redis_client = redis_client

        # === 数据存储 ===

        # ExecutionTarget 历史（所有状态变化）
        self.execution_targets: List[ExecutionTargetSnapshot] = []

        # Portfolio 快照（在 ExecutionTarget 终止状态时记录）
        self.portfolio_snapshots: List[PortfolioSnapshot] = []

        # GridPosition 快照（在 ExecutionTarget 终止状态时记录）
        self.grid_position_snapshots: List[GridPositionSnapshot] = []

        # 最后已知价格: {symbol: last_price}
        self.last_prices: Dict[Symbol, float] = {}

    def debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(message)

    def capture_initial_snapshot(self):
        """
        捕获初始账户快照（在算法初始化完成后调用）

        用途：记录算法启动时的账户状态，作为后续对比的基准
        """
        self.debug("📸 Capturing initial portfolio snapshot...")

        try:
            # 记录初始 Portfolio 快照
            self._record_portfolio_snapshot("INITIAL")

            # 如果启用实时模式，也写入 Redis
            if self.realtime_mode and self.redis_client:
                self._update_portfolio_snapshot_to_redis()

            self.debug("✅ Initial snapshot captured")
        except Exception as e:
            self.algorithm.error(f"❌ Failed to capture initial snapshot: {e}")

    # ========================================================================
    #                      核心追踪方法
    # ========================================================================

    def on_execution_target_registered(self, target):
        """
        当 ExecutionTarget 注册时调用（在 register_execution_target 后立即调用）

        Args:
            target: ExecutionTarget 实例

        功能:
        - Live 模式：写入 Redis 显示正在执行的 ExecutionTarget
        - Backtest 模式：仅记录日志
        """
        self.debug(f"📝 ExecutionTarget Registered | Grid: {target.grid_id} | Status: {target.status}")

        # 实时模式：写入 Redis 显示活跃的 ExecutionTarget
        if self.realtime_mode and self.redis_client:
            try:
                # 使用 hash(GridLevel) 作为唯一标识符
                hash_key = str(hash(target.level))

                # 构造活跃 target 数据
                active_target_data = {
                    "hash": hash_key,  # 唯一标识符（前端索引用）
                    "grid_id": target.grid_id,  # 人类可读标识（UI 显示用）
                    "level_type": target.level.type,
                    "pair_symbol": f"{target.pair_symbol[0].value}/{target.pair_symbol[1].value}",
                    "status": str(target.status),
                    "filled_qty_crypto": 0.0,  # 注册时初始为 0
                    "filled_qty_stock": 0.0,  # 注册时初始为 0
                    "target_qty_crypto": target.target_qty.get(target.pair_symbol[0], 0.0),
                    "target_qty_stock": target.target_qty.get(target.pair_symbol[1], 0.0),
                    "expected_spread_pct": target.expected_spread_pct,  # 预期价差
                    "direction": target.spread_direction,  # 方向
                    "timestamp": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S")
                }

                # 写入 Redis (使用 hash 作为 hash field)
                self.redis_client.set_active_target(hash_key, active_target_data)
                self.debug(f"  ✅ Written to Redis: active_target (hash={hash_key}, grid_id={target.grid_id})")
            except Exception as e:
                self.algorithm.error(f"❌ Failed to write active target to Redis: {e}")

    def on_execution_target_update(self, target):
        """
        当 ExecutionTarget 状态更新时调用

        Args:
            target: ExecutionTarget 实例 (from strategy/execution_models.py)

        记录内容:
        - ExecutionTarget 当前状态
        - 所有 OrderGroup 的状态
        - 如果是终止状态（Filled/Canceled），记录 Portfolio 快照
        - 如果有成交，累积到 Round Trip
        """
        # 创建 ExecutionTarget 快照
        snapshot = self._create_execution_target_snapshot(target)

        # 存储到历史
        self.execution_targets.append(snapshot)

        self.debug(f"📊 ExecutionTarget Update | Grid: {target.grid_id} | Status: {target.status}")

        # 实时模式：更新 Redis 中的活跃 ExecutionTarget 状态
        if self.realtime_mode and self.redis_client:
            try:
                # 使用 hash(GridLevel) 作为唯一标识符
                hash_key = str(hash(target.level))

                # 如果是终止状态，从活跃列表移除；否则更新
                if target.is_terminal():
                    self.redis_client.remove_active_target(hash_key)
                    self.debug(f"  ✅ Removed from Redis active targets (hash={hash_key}, grid_id={target.grid_id})")
                else:
                    # 构造活跃 target 数据
                    active_target_data = {
                        "hash": hash_key,  # 唯一标识符
                        "grid_id": target.grid_id,  # UI 显示
                        "level_type": target.level.type,
                        "pair_symbol": f"{target.pair_symbol[0].value}/{target.pair_symbol[1].value}",
                        "status": str(target.status),
                        "filled_qty_crypto": target.quantity_filled[0],
                        "filled_qty_stock": target.quantity_filled[1],
                        "target_qty_crypto": target.target_qty.get(target.pair_symbol[0], 0.0),
                        "target_qty_stock": target.target_qty.get(target.pair_symbol[1], 0.0),
                        "expected_spread_pct": target.expected_spread_pct,  # 预期价差
                        "direction": target.spread_direction,  # 方向
                        "timestamp": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    self.redis_client.set_active_target(hash_key, active_target_data)
                    self.debug(f"  ✅ Updated Redis active target (hash={hash_key}, grid_id={target.grid_id})")

                # 实时更新 Portfolio 快照（账户状态、PnL）
                self._update_portfolio_snapshot_to_redis()
            except Exception as e:
                self.algorithm.error(f"❌ Failed to update active target in Redis: {e}")

        # 如果是终止状态，记录 Portfolio 快照
        if target.is_terminal():
            self._record_portfolio_snapshot(target.grid_id)

    # ========================================================================
    #                      内部辅助方法
    # ========================================================================

    def _create_execution_target_snapshot(self, target) -> ExecutionTargetSnapshot:
        """
        从 ExecutionTarget 创建快照

        Args:
            target: ExecutionTarget 实例

        Returns:
            ExecutionTargetSnapshot
        """
        crypto_symbol, stock_symbol = target.pair_symbol

        # 创建 OrderGroup 快照列表
        order_group_snapshots = []

        for order_group in target.order_groups:
            # 创建订单快照列表
            order_snapshots = []

            for ticket in order_group.order_tickets:
                order_snap = OrderSnapshot(
                    order_id=ticket.order_id,
                    symbol=str(ticket.symbol.value),
                    direction="BUY" if ticket.quantity > 0 else "SELL",
                    quantity=abs(ticket.quantity_filled),
                    fill_price=ticket.average_fill_price,
                    fee=0.0,  # 单笔订单手续费不重要，在 target 层级统计
                    status=str(ticket.status),
                    time=self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S")
                )
                order_snapshots.append(order_snap)

            # 创建 OrderGroup 快照
            group_snapshot = OrderGroupSnapshot(
                type=str(order_group.type),
                status=str(order_group.status),
                expected_spread_pct=order_group.expected_spread_pct,
                actual_spread_pct=order_group.actual_spread_pct,
                orders=order_snapshots,
                filled_qty=order_group.quantity_filled,
                total_fee=0.0  # OrderGroup 级别不统计，在 ExecutionTarget 层统计
            )
            order_group_snapshots.append(group_snapshot)

        # 计算总成本（使用真实手续费）
        total_value = sum(
            abs(ticket.quantity_filled * ticket.average_fill_price)
            for order_group in target.order_groups
            for ticket in order_group.order_tickets
        )
        total_fee = target.total_fee_in_account_currency
        total_cost = total_value + total_fee

        # 创建 ExecutionTarget 快照
        return ExecutionTargetSnapshot(
            grid_id=target.grid_id,
            level_type=target.level.type,
            status=str(target.status),
            timestamp=self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S"),
            target_qty={
                str(crypto_symbol.value): target.target_qty[crypto_symbol],
                str(stock_symbol.value): target.target_qty[stock_symbol]
            },
            order_groups=order_group_snapshots,
            total_filled_qty=target.quantity_filled,
            total_cost=total_cost,
            total_fee=total_fee
        )

    def _record_portfolio_snapshot(self, execution_target_id: str):
        """
        记录 Portfolio 快照和 GridPosition 快照

        Args:
            execution_target_id: ExecutionTarget 的 grid_id
        """
        # 获取 LEAN PnL
        lean_pnl = {
            "total_unrealized": float(self.algorithm.portfolio.total_unrealized_profit),
            "total_net": float(self.algorithm.portfolio.total_profit)
        }

        # 获取账户状态
        accounts = self._capture_accounts_state()

        # 创建 Portfolio 快照
        portfolio_snapshot = PortfolioSnapshot(
            timestamp=self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S"),
            execution_target_id=execution_target_id,
            lean_pnl=lean_pnl,
            accounts=accounts
        )

        self.portfolio_snapshots.append(portfolio_snapshot)
        self.debug(f"  → Portfolio snapshot recorded")

        # 记录 GridPosition 快照（如果 strategy 可用）
        if self.strategy and hasattr(self.strategy, 'grid_position_manager'):
            self._record_grid_positions_snapshot()

    def _record_grid_positions_snapshot(self):
        """
        记录所有 GridPosition 的快照

        从 strategy.grid_position_manager 获取所有持仓并创建快照
        """
        try:
            position_manager = self.strategy.grid_position_manager
            timestamp = self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S")

            # 遍历所有 GridPosition
            for entry_level, grid_position in position_manager.grid_positions.items():
                # 使用 hash(GridLevel) 作为唯一标识符
                hash_key = str(hash(entry_level))

                # 创建快照
                snapshot = GridPositionSnapshot(
                    grid_id=grid_position.grid_id,
                    pair_symbol=(
                        str(grid_position.pair_symbol[0].value),
                        str(grid_position.pair_symbol[1].value)
                    ),
                    level_type=entry_level.type,
                    spread_pct=entry_level.spread_pct,
                    leg1_qty=grid_position._leg1_qty,
                    leg2_qty=grid_position._leg2_qty,
                    timestamp=timestamp
                )

                self.grid_position_snapshots.append(snapshot)

                # 实时模式：写入 Redis
                if self.realtime_mode and self.redis_client:
                    try:
                        from dataclasses import asdict
                        # 转换为字典并添加 hash 字段
                        snapshot_dict = asdict(snapshot)
                        snapshot_dict["hash"] = hash_key  # 添加唯一标识符
                        self.redis_client.set_grid_position(hash_key, snapshot_dict)
                    except Exception as e:
                        self.algorithm.error(f"❌ Failed to write grid position to Redis: {e}")

            self.debug(f"  → GridPosition snapshots recorded ({len(position_manager.grid_positions)} positions)")

        except Exception as e:
            self.algorithm.error(f"❌ Failed to record grid position snapshots: {e}")

    def _update_portfolio_snapshot_to_redis(self):
        """
        实时更新 Portfolio 快照到 Redis（Live 模式）

        在每次 ExecutionTarget 更新时调用，确保前端账户状态实时更新
        """
        if not self.realtime_mode or not self.redis_client:
            return

        try:
            # 构造快照数据
            snapshot_data = {
                "timestamp": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S"),
                "pnl": {
                    "realized": float(self.algorithm.portfolio.total_profit),
                    "unrealized": float(self.algorithm.portfolio.total_unrealized_profit)
                },
                "accounts": self._capture_accounts_state()
            }

            # 写入 Redis
            self.redis_client.set_snapshot(snapshot_data)
            self.debug(f"  ✅ Updated portfolio snapshot to Redis")
        except Exception as e:
            self.algorithm.error(f"❌ Failed to update portfolio snapshot: {e}")

    def _capture_accounts_state(self) -> Dict[str, Any]:
        """捕获所有账户的状态"""
        accounts = {}

        # 检查是否是多账户模式
        if hasattr(self.algorithm.portfolio, 'GetAccount'):
            # 多账户模式：遍历所有账户
            try:
                for account_name in ['IBKR', 'Kraken']:
                    try:
                        account = self.algorithm.portfolio.GetAccount(account_name)
                        accounts[account_name] = self._serialize_account(account)
                    except:
                        pass
            except:
                pass

        # 单账户模式或备选方案：记录主账户
        if not accounts:
            accounts['Main'] = self._serialize_account(self.algorithm.portfolio)

        return accounts

    def _serialize_account(self, account) -> Dict[str, Any]:
        """序列化账户状态"""
        try:
            holdings = {}
            for kvp in account.securities:
                security = kvp.value
                if security.invested:
                    # 使用 Holdings 对象获取持仓信息
                    holding = security.holdings
                    holdings[str(kvp.key.value)] = {
                        "quantity": float(holding.quantity),
                        "average_price": float(holding.average_price),
                        "market_price": float(security.price),
                        "market_value": float(holding.holdings_value),
                        "unrealized_pnl": float(holding.unrealized_profit)
                    }

            cashbook = {}
            try:
                for kvp in account.cash_book:
                    cashbook[str(kvp.key)] = {
                        "amount": float(kvp.value.amount),
                        "conversion_rate": float(kvp.value.conversion_rate),
                        "value_in_account_currency": float(kvp.value.value_in_account_currency)
                    }
            except Exception as e:
                self.debug(f"⚠️ Error serializing cashbook: {e}")

            return {
                "cash": float(account.cash),
                "total_portfolio_value": float(account.total_portfolio_value),
                "holdings": holdings,
                "cashbook": cashbook
            }
        except Exception as e:
            self.debug(f"❌ Error serializing account: {e}")
            return {
                "cash": 0.0,
                "total_portfolio_value": 0.0,
                "holdings": {},
                "cashbook": {}
            }

    # ========================================================================
    #                      导出方法
    # ========================================================================

    def export_json(self, filepath: str):
        """
        导出ExecutionTarget历史和Portfolio快照到JSON文件

        Args:
            filepath: 输出文件路径
        """
        data = {
            "meta": {
                "start_time": self.algorithm.start_date.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_execution_targets": len(self.execution_targets),
                "total_snapshots": len(self.portfolio_snapshots),
                "total_grid_positions": len(self.grid_position_snapshots)
            },
            "execution_targets": [asdict(et) for et in self.execution_targets],
            "portfolio_snapshots": [asdict(ps) for ps in self.portfolio_snapshots],
            "grid_position_snapshots": [asdict(gps) for gps in self.grid_position_snapshots]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.debug(f"✅ Exported Grid tracking data to: {filepath}")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_execution_targets": len(self.execution_targets),
            "total_snapshots": len(self.portfolio_snapshots),
            "total_grid_positions": len(self.grid_position_snapshots)
        }


# 向后兼容：导出别名
OrderTracker = GridOrderTracker
