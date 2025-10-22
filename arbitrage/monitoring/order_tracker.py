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
    time: str  # ISO format

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
            time=order_event.utc_time.isoformat()
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
    timestamp: str  # ISO format

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
    timestamp: str  # ISO format
    execution_target_id: str  # 关联的 ExecutionTarget grid_id

    # LEAN PnL
    lean_pnl: Dict[str, float]  # {"total_unrealized": ..., "total_net": ...}

    # 账户状态
    accounts: Dict[str, Any]  # {account_name: {cash, holdings, ...}}


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

    def __init__(self, algorithm: QCAlgorithm, strategy=None, debug: bool = False):
        """
        初始化 GridOrderTracker

        Args:
            algorithm: QCAlgorithm 实例
            strategy: GridStrategy 实例（用于访问 GridPositionManager）
            debug: 是否启用调试日志
        """
        self.algorithm = algorithm
        self.strategy = strategy
        self.debug_enabled = debug

        # === 数据存储 ===

        # Round Trips: 完整的 Entry → Exit 周期
        self.round_trips: List[RoundTrip] = []  # 已完成的 Round Trips
        self.round_trip_counter: int = 0

        # ExecutionTarget 历史（所有状态变化）
        self.execution_targets: List[ExecutionTargetSnapshot] = []

        # Portfolio 快照（在 ExecutionTarget 终止状态时记录）
        self.portfolio_snapshots: List[PortfolioSnapshot] = []

        # === Round Trip 追踪状态 ===
        # 待配对的 Entry: {entry_level_id: [ExecutionTargetSnapshots]}
        self._pending_entries: Dict[str, List[ExecutionTargetSnapshot]] = {}

        # 进行中的 Round Trip: {entry_level_id: RoundTrip}
        self._open_round_trips: Dict[str, RoundTrip] = {}

        # 最后已知价格: {symbol: last_price}
        self.last_prices: Dict[Symbol, float] = {}

    def debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(message)

    # ========================================================================
    #                      核心追踪方法
    # ========================================================================

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

        # 如果是终止状态，记录 Portfolio 快照
        if target.is_terminal():
            self._record_portfolio_snapshot(target.grid_id)

            # 检查是否有成交
            has_fills = (snapshot.total_filled_qty[0] != 0 or snapshot.total_filled_qty[1] != 0)

            if has_fills:
                # 如果是 Entry，累积到待配对列表
                if target.level.type == "ENTRY":
                    self._accumulate_entry(target, snapshot)

                # 如果是 Exit，累积并尝试配对 Round Trip
                elif target.level.type == "EXIT":
                    self._accumulate_exit(target, snapshot)

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
                    time=self.algorithm.time.isoformat()
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
            timestamp=self.algorithm.time.isoformat(),
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
        记录 Portfolio 快照

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

        # 创建快照
        snapshot = PortfolioSnapshot(
            timestamp=self.algorithm.time.isoformat(),
            execution_target_id=execution_target_id,
            lean_pnl=lean_pnl,
            accounts=accounts
        )

        self.portfolio_snapshots.append(snapshot)
        self.debug(f"  → Portfolio snapshot recorded")

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

    def _accumulate_entry(self, target, snapshot: ExecutionTargetSnapshot):
        """
        累积 Entry ExecutionTarget 到待配对列表

        Args:
            target: Entry ExecutionTarget 实例
            snapshot: ExecutionTargetSnapshot
        """
        level_id = target.level.level_id

        if level_id not in self._pending_entries:
            self._pending_entries[level_id] = []

        self._pending_entries[level_id].append(snapshot)
        self.debug(f"  📥 Entry accumulated | Level: {level_id} | Cost: ${snapshot.total_cost:.2f} | Total entries: {len(self._pending_entries[level_id])}")

    def _accumulate_exit(self, target, snapshot: ExecutionTargetSnapshot):
        """
        累积 Exit ExecutionTarget 并创建/更新 Round Trip

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

        # 检查是否有待配对的 Entry
        if entry_level_id not in self._pending_entries or not self._pending_entries[entry_level_id]:
            self.debug(f"  ⚠️ No pending entries for {entry_level_id}")
            return

        # 检查是否已有 Open Round Trip
        if entry_level_id in self._open_round_trips:
            # 累积到现有 Round Trip
            round_trip = self._open_round_trips[entry_level_id]
            round_trip.exit_targets.append(snapshot)
            round_trip.total_exit_revenue += snapshot.total_cost
            round_trip.total_exit_fee += snapshot.total_fee

            # 更新时间范围
            first_exit_time = round_trip.exit_targets[0].timestamp
            last_exit_time = snapshot.timestamp
            if first_exit_time == last_exit_time:
                round_trip.exit_time_range = first_exit_time
            else:
                round_trip.exit_time_range = f"{first_exit_time} ~ {last_exit_time}"

            # 重新计算 PnL
            round_trip.net_pnl = round_trip.total_exit_revenue - round_trip.total_entry_cost

            self.debug(f"  📤 Exit accumulated | RT #{round_trip.round_trip_id} | Revenue: ${snapshot.total_cost:.2f} | Fee: ${snapshot.total_fee:.4f} | Total exits: {len(round_trip.exit_targets)} | PnL: ${round_trip.net_pnl:.2f}")
        else:
            # 创建新的 Round Trip
            self._create_round_trip(entry_level_id, exit_level_id, snapshot)

    def _create_round_trip(self, entry_level_id: str, exit_level_id: str, exit_snapshot: ExecutionTargetSnapshot):
        """
        创建新的 Round Trip

        Args:
            entry_level_id: Entry GridLevel ID
            exit_level_id: Exit GridLevel ID
            exit_snapshot: Exit ExecutionTargetSnapshot
        """
        entry_snapshots = self._pending_entries[entry_level_id]
        total_entry_cost = sum(e.total_cost for e in entry_snapshots)
        total_entry_fee = sum(e.total_fee for e in entry_snapshots)

        self.round_trip_counter += 1

        # 计算 Entry 时间范围
        first_entry_time = entry_snapshots[0].timestamp
        last_entry_time = entry_snapshots[-1].timestamp
        if first_entry_time == last_entry_time:
            entry_time_range = first_entry_time
        else:
            entry_time_range = f"{first_entry_time} ~ {last_entry_time}"

        round_trip = RoundTrip(
            round_trip_id=self.round_trip_counter,
            pair=self._format_pair_name_from_snapshot(exit_snapshot),
            entry_level_id=entry_level_id,
            entry_targets=entry_snapshots,
            entry_time_range=entry_time_range,
            total_entry_cost=total_entry_cost,
            total_entry_fee=total_entry_fee,
            exit_level_id=exit_level_id,
            exit_targets=[exit_snapshot],
            exit_time_range=exit_snapshot.timestamp,
            total_exit_revenue=exit_snapshot.total_cost,
            total_exit_fee=exit_snapshot.total_fee,
            net_pnl=exit_snapshot.total_cost - total_entry_cost,
            status="OPEN"
        )

        self._open_round_trips[entry_level_id] = round_trip
        self.debug(f"  ✅ Round Trip #{round_trip.round_trip_id} created | Entry: {len(entry_snapshots)} targets (${total_entry_cost:.2f}) | Exit: 1 target (${exit_snapshot.total_cost:.2f}) | PnL: ${round_trip.net_pnl:.2f}")

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
        # 合并已完成的和进行中的 Round Trips
        all_round_trips = self.round_trips + list(self._open_round_trips.values())

        data = {
            "meta": {
                "start_time": self.algorithm.start_date.isoformat(),
                "end_time": self.algorithm.time.isoformat(),
                "total_round_trips": len(all_round_trips),
                "closed_round_trips": len(self.round_trips),
                "open_round_trips": len(self._open_round_trips),
                "total_execution_targets": len(self.execution_targets),
                "total_snapshots": len(self.portfolio_snapshots)
            },
            "round_trips": [asdict(rt) for rt in all_round_trips],
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
        # 计算所有 Round Trip 的总 PnL（包括 Open 和 Closed）
        all_round_trips = self.round_trips + list(self._open_round_trips.values())
        total_pnl = sum(rt.net_pnl for rt in all_round_trips)

        # 计算未配对的 Entry 数量
        pending_entries_count = sum(len(entries) for entries in self._pending_entries.values())

        return {
            "total_round_trips": len(all_round_trips),
            "closed_round_trips": len(self.round_trips),
            "open_round_trips": len(self._open_round_trips),
            "pending_entries": pending_entries_count,
            "open_positions": pending_entries_count,  # 向后兼容：表示未配对的 Entry positions
            "total_pnl": total_pnl,
            "total_execution_targets": len(self.execution_targets),
            "total_snapshots": len(self.portfolio_snapshots)
        }


# 向后兼容：导出别名
OrderTracker = GridOrderTracker
