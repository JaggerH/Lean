"""
Grid Order Tracker - Grid 框架专用的订单追踪器

功能:
1. Round Trip 追踪 - Entry GridLevel → Exit GridLevel 配对
2. ExecutionTarget 追踪 - 每次 GridLevel 触发的执行目标
3. OrderGroup 追踪 - ExecutionTarget 内的订单组（可能多次提交）
4. Portfolio Snapshot - 每次 ExecutionTarget 状态变化时记录

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
class RoundTrip:
    """Grid Round Trip - Entry → Exit 配对（支持同 GridLevel 多次执行累积）"""
    round_trip_id: int
    pair: str  # "TSLAxUSD <-> TSLA"

    # Entry 组（同 GridLevel 的多个 ExecutionTarget）
    entry_level_id: str
    entry_targets: List[ExecutionTargetSnapshot]  # 多个 Entry targets
    entry_time_range: str  # "start_time ~ end_time" or single timestamp
    total_entry_cost: float  # 累加所有 Entry 的成本（包含手续费）

    # Exit 组（同 GridLevel 的多个 ExecutionTarget）
    exit_level_id: str
    exit_targets: List[ExecutionTargetSnapshot]  # 多个 Exit targets
    exit_time_range: str  # "start_time ~ end_time" or single timestamp
    total_exit_revenue: float  # 累加所有 Exit 的收入（扣除手续费）

    # PnL
    net_pnl: float  # total_exit_revenue - total_entry_cost

    # 费用（带默认值的字段必须在最后）
    total_entry_fee: float = 0.0  # 累加所有 Entry 的手续费
    total_exit_fee: float = 0.0  # 累加所有 Exit 的手续费

    # 状态
    status: str = "OPEN"  # "OPEN" | "CLOSED"


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
    1. Round Trip 级别 - Entry GridLevel → Exit GridLevel 配对
    2. ExecutionTarget 级别 - 每次 GridLevel 触发的执行目标
    3. OrderGroup 级别 - ExecutionTarget 内的订单组（可能多次提交）
    4. Portfolio Snapshot - 每次 ExecutionTarget 状态变化时记录
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

        # Round Trips: 完整的 Entry → Exit 周期
        self.round_trips: List[RoundTrip] = []  # 已完成的 Round Trips
        self.round_trip_counter: int = 0

        # ExecutionTarget 历史（所有状态变化）
        self.execution_targets: List[ExecutionTargetSnapshot] = []

        # Portfolio 快照（在 ExecutionTarget 终止状态时记录）
        self.portfolio_snapshots: List[PortfolioSnapshot] = []

        # GridPosition 快照（在 ExecutionTarget 终止状态时记录）
        self.grid_position_snapshots: List[GridPositionSnapshot] = []

        # === Round Trip 追踪状态 ===
        # 最后一个有效的 Entry: {entry_level_id: ExecutionTargetSnapshot}
        self._last_entry: Dict[str, ExecutionTargetSnapshot] = {}

        # 最后已知价格: {symbol: last_price}
        self.last_prices: Dict[Symbol, float] = {}

    def debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(message)

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
                # 构造活跃 target 数据
                active_target_data = {
                    "grid_id": target.grid_id,
                    "level_type": target.level.type,
                    "pair_symbol": f"{target.pair_symbol[0].value}/{target.pair_symbol[1].value}",
                    "status": str(target.status),
                    "target_qty_crypto": target.target_qty.get(target.pair_symbol[0], 0.0),
                    "target_qty_stock": target.target_qty.get(target.pair_symbol[1], 0.0),
                    "timestamp": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S")
                }

                # 写入 Redis (使用 grid_id 作为 hash field)
                self.redis_client.set_active_target(target.grid_id, active_target_data)
                self.debug(f"  ✅ Written to Redis: active_target:{target.grid_id}")
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
                active_target_data = {
                    "grid_id": target.grid_id,
                    "level_type": target.level.type,
                    "pair_symbol": f"{target.pair_symbol[0].value}/{target.pair_symbol[1].value}",
                    "status": str(target.status),
                    "filled_qty_crypto": target.quantity_filled[0],
                    "filled_qty_stock": target.quantity_filled[1],
                    "target_qty_crypto": target.target_qty.get(target.pair_symbol[0], 0.0),
                    "target_qty_stock": target.target_qty.get(target.pair_symbol[1], 0.0),
                    "timestamp": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S")
                }

                # 如果是终止状态，从活跃列表移除；否则更新
                if target.is_terminal():
                    self.redis_client.remove_active_target(target.grid_id)
                    self.debug(f"  ✅ Removed from Redis active targets: {target.grid_id}")
                else:
                    self.redis_client.set_active_target(target.grid_id, active_target_data)
                    self.debug(f"  ✅ Updated Redis active target: {target.grid_id}")
            except Exception as e:
                self.algorithm.error(f"❌ Failed to update active target in Redis: {e}")

        # 如果是终止状态，记录 Portfolio 快照
        if target.is_terminal():
            self._record_portfolio_snapshot(target.grid_id)

            # Rule 1: 如果 Canceled 且 filled_quantity = (0,0)，忽略
            is_canceled = (str(target.status) == "5")  # Status 5 = Canceled
            has_no_fills = (snapshot.total_filled_qty[0] == 0 and snapshot.total_filled_qty[1] == 0)

            if is_canceled and has_no_fills:
                self.debug(f"  ⊗ Skipping canceled target with no fills | Grid: {target.grid_id}")
                return

            # 检查是否有成交
            has_fills = (snapshot.total_filled_qty[0] != 0 or snapshot.total_filled_qty[1] != 0)

            if has_fills:
                # 如果是 Entry，记录为最后一个有效 Entry
                if target.level.type == "ENTRY":
                    self._record_entry(target, snapshot)

                # 如果是 Exit，尝试匹配 Round Trip
                elif target.level.type == "EXIT":
                    self._try_match_round_trip(target, snapshot)

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
                        self.redis_client.set_grid_position(grid_position.grid_id, snapshot)
                    except Exception as e:
                        self.algorithm.error(f"❌ Failed to write grid position to Redis: {e}")

            self.debug(f"  → GridPosition snapshots recorded ({len(position_manager.grid_positions)} positions)")

        except Exception as e:
            self.algorithm.error(f"❌ Failed to record grid position snapshots: {e}")

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

    def _record_entry(self, target, snapshot: ExecutionTargetSnapshot):
        """
        记录最后一个有效的 Entry ExecutionTarget

        Args:
            target: Entry ExecutionTarget 实例
            snapshot: ExecutionTargetSnapshot
        """
        level_id = target.level.level_id
        self._last_entry[level_id] = snapshot
        self.debug(f"  📥 Entry recorded | Level: {level_id} | Cost: ${snapshot.total_cost:.2f} | Filled: {snapshot.total_filled_qty}")

    def _try_match_round_trip(self, target, snapshot: ExecutionTargetSnapshot):
        """
        尝试将 Exit 与最后的 Entry 匹配创建 Round Trip

        Rule 2: Entry/Exit filled_quantity 完全相等且相邻时匹配

        Args:
            target: Exit ExecutionTarget 实例
            snapshot: ExecutionTargetSnapshot
        """
        exit_level_id = target.level.level_id

        # 从 Strategy 获取配对的 Entry Level ID
        entry_level_id = self._get_paired_entry_level_id(target.level)

        if not entry_level_id:
            self.debug(f"  ⚠️ No paired entry level for {exit_level_id}")
            return

        # 检查是否有最后记录的 Entry
        if entry_level_id not in self._last_entry:
            self.debug(f"  ⚠️ No recorded entry for {entry_level_id}")
            return

        entry_snapshot = self._last_entry[entry_level_id]

        # Rule 2: 检查 filled_quantity 是否完全相等
        entry_qty = entry_snapshot.total_filled_qty
        exit_qty = snapshot.total_filled_qty

        quantities_match = (abs(entry_qty[0] - exit_qty[0]) < 0.0001 and
                           abs(entry_qty[1] - exit_qty[1]) < 0.0001)

        if not quantities_match:
            self.debug(f"  ⚠️ Quantities don't match | Entry: {entry_qty} | Exit: {exit_qty}")
            return

        # Rule 2: 检查是否相邻（简化版：如果 quantities match，就创建 Round Trip）
        # 注意：严格的"相邻"检查需要检查 execution_targets 列表中的顺序
        # 这里简化为：只要有匹配的 Entry 就创建 Round Trip

        # 创建 Round Trip
        self._create_simple_round_trip(entry_level_id, exit_level_id, entry_snapshot, snapshot)

        # 清除已使用的 Entry，避免重复匹配
        del self._last_entry[entry_level_id]

    def _create_simple_round_trip(self, entry_level_id: str, exit_level_id: str,
                                   entry_snapshot: ExecutionTargetSnapshot,
                                   exit_snapshot: ExecutionTargetSnapshot):
        """
        创建简单的 1:1 Round Trip

        Args:
            entry_level_id: Entry GridLevel ID
            exit_level_id: Exit GridLevel ID
            entry_snapshot: Entry ExecutionTargetSnapshot
            exit_snapshot: Exit ExecutionTargetSnapshot
        """
        self.round_trip_counter += 1

        round_trip = RoundTrip(
            round_trip_id=self.round_trip_counter,
            pair=self._format_pair_name_from_snapshot(exit_snapshot),
            entry_level_id=entry_level_id,
            entry_targets=[entry_snapshot],  # 只有一个 Entry
            entry_time_range=entry_snapshot.timestamp,
            total_entry_cost=entry_snapshot.total_cost,
            total_entry_fee=entry_snapshot.total_fee,
            exit_level_id=exit_level_id,
            exit_targets=[exit_snapshot],  # 只有一个 Exit
            exit_time_range=exit_snapshot.timestamp,
            total_exit_revenue=exit_snapshot.total_cost,
            total_exit_fee=exit_snapshot.total_fee,
            net_pnl=exit_snapshot.total_cost - entry_snapshot.total_cost,
            status="CLOSED"  # 1:1 匹配直接设为 CLOSED
        )

        self.round_trips.append(round_trip)
        self.debug(f"  ✅ Round Trip #{round_trip.round_trip_id} created | Entry: ${entry_snapshot.total_cost:.2f} | Exit: ${exit_snapshot.total_cost:.2f} | PnL: ${round_trip.net_pnl:.2f}")

    def _get_paired_entry_level_id(self, exit_level) -> Optional[str]:
        """
        从 Exit GridLevel 获取配对的 Entry Level ID

        Args:
            exit_level: Exit GridLevel 实例

        Returns:
            Entry Level ID 或 None
        """
        # 方法 1: 使用 GridLevelManager 的 exit_to_entry 索引
        if self.strategy and hasattr(self.strategy, 'grid_level_manager'):
            try:
                entry_level = self.strategy.grid_level_manager.exit_to_entry.get(exit_level)
                if entry_level:
                    return entry_level.level_id
            except Exception as e:
                self.debug(f"  ⚠️ Error finding paired entry level from exit_to_entry: {e}")

        # 方法 2: 备用 - 遍历所有 grid_levels（按 pair）
        if self.strategy and hasattr(self.strategy, 'grid_level_manager'):
            try:
                for pair_symbol, levels in self.strategy.grid_level_manager.grid_levels.items():
                    for level in levels:
                        if (level.type == "ENTRY" and
                            hasattr(level, 'paired_exit_level_id') and
                            level.paired_exit_level_id == exit_level.level_id):
                            return level.level_id
            except Exception as e:
                self.debug(f"  ⚠️ Error finding paired entry level from grid_levels: {e}")

        return None

    def _format_pair_name_from_snapshot(self, snapshot: ExecutionTargetSnapshot) -> str:
        """
        从 ExecutionTargetSnapshot 格式化交易对名称

        Args:
            snapshot: ExecutionTargetSnapshot

        Returns:
            交易对名称，如 "AAPLXUSD <-> AAPL"
        """
        symbols = list(snapshot.target_qty.keys())
        if len(symbols) >= 2:
            return f"{symbols[0]} <-> {symbols[1]}"
        elif len(symbols) == 1:
            return symbols[0]
        return "N/A"


    # ========================================================================
    #                      导出方法
    # ========================================================================

    def export_json(self, filepath: str, generate_html: bool = True):
        """
        导出所有数据到 JSON 文件（可选生成 HTML 报告）

        Args:
            filepath: 输出文件路径
            generate_html: 是否自动生成 HTML 报告（默认 True）
        """
        # 所有 Round Trips 都是 CLOSED (1:1 匹配)
        data = {
            "meta": {
                "start_time": self.algorithm.start_date.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self.algorithm.time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_round_trips": len(self.round_trips),
                "closed_round_trips": len(self.round_trips),
                "open_round_trips": 0,
                "total_execution_targets": len(self.execution_targets),
                "total_snapshots": len(self.portfolio_snapshots)
            },
            "round_trips": [asdict(rt) for rt in self.round_trips],
            "execution_targets": [asdict(et) for et in self.execution_targets],
            "portfolio_snapshots": [asdict(ps) for ps in self.portfolio_snapshots]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.debug(f"✅ Exported Grid tracking data to: {filepath}")

        # 自动生成 HTML 报告
        if generate_html:
            try:
                from monitoring.grid_html_generator import generate_grid_html_report
                html_filepath = filepath.replace('.json', '_grid.html')
                generate_grid_html_report(filepath, html_filepath)
                self.debug(f"✅ Generated HTML report: {html_filepath}")
            except Exception as e:
                self.debug(f"⚠️ Failed to generate HTML report: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        # 所有 Round Trips 都是 CLOSED (1:1 匹配)
        total_pnl = sum(rt.net_pnl for rt in self.round_trips)

        # 计算未配对的 Entry 数量 (最后记录的 Entry)
        pending_entries_count = len(self._last_entry)

        return {
            "total_round_trips": len(self.round_trips),
            "closed_round_trips": len(self.round_trips),
            "open_round_trips": 0,
            "pending_entries": pending_entries_count,
            "open_positions": pending_entries_count,  # 向后兼容：表示未配对的 Entry positions
            "total_pnl": total_pnl,
            "total_execution_targets": len(self.execution_targets),
            "total_snapshots": len(self.portfolio_snapshots)
        }


# 向后兼容：导出别名
OrderTracker = GridOrderTracker
