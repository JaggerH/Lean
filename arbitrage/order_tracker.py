"""
OrderTracker - 独立的订单和Portfolio追踪系统

功能:
1. 记录每次订单成交时的完整 Portfolio 状态（快照）
2. 双重 PnL 计算:
   - Lean 官方 PnL (Portfolio 计算)
   - OrderTracker 自己的 PnL (基于订单配对)
3. 支持多账户追踪
4. 导出 JSON 格式数据
5. 生成 HTML 可视化报告
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
import json


class OrderTracker:
    """
    完整的订单和Portfolio追踪系统

    与 BaseStrategy 集成,利用其 order_to_pair 映射来追踪交易对的开平仓。
    """

    def __init__(self, algorithm: QCAlgorithm, strategy=None, debug: bool = False):
        """
        初始化 OrderTracker

        Args:
            algorithm: QCAlgorithm 实例
            strategy: BaseStrategy 实例 (用于访问 order_to_pair 和 positions)
            debug: 是否启用调试日志输出，默认 False
        """
        self.algorithm = algorithm
        self.strategy = strategy
        self.debug_enabled = debug

        # ============ 数据存储 ============

        # Portfolio 状态快照历史
        self.snapshots: List[Dict] = []

        # 订单详情: {order_id: order_info}
        self.orders: Dict[int, Dict] = {}

        # 交易对追踪: {(crypto_symbol, stock_symbol): trade_info}
        self.pair_trades: Dict[Tuple[Symbol, Symbol], Dict] = {}

        # 最后已知价格: {symbol: last_price}
        self.last_prices: Dict[Symbol, float] = {}

        # ============ Round Trip 追踪 ============

        # 简化的交易对订单追踪 (Simplified Round Trip Tracking)
        # 格式: {(crypto_symbol, stock_symbol): current_round_trip}
        # current_round_trip = {
        #   'round_trip_id': int,
        #   'pair': str,  # "BTCUSD <-> BTC"
        #   'orders': [order_id1, order_id2, order_id3, order_id4],  # 4个订单ID
        #   'open_time': datetime,  # 第一个订单时间
        #   'close_time': datetime | None,  # 第四个订单时间
        #   'status': 'OPEN' | 'CLOSED',  # OPEN: 未满4个订单, CLOSED: 4个订单完成
        #   'pnl': float | None,  # 仅当 status='CLOSED' 时有值
        #   'open_cost': float,  # 前2个订单的成本（包含手续费）
        #   'close_revenue': float,  # 后2个订单的收入（扣除手续费）
        # }
        self.pair_round_trips: Dict[Tuple[Symbol, Symbol], List[Dict]] = {}  # 所有已完成的round trips
        self.active_round_trips: Dict[Tuple[Symbol, Symbol], Dict] = {}  # 当前活跃的round trip (每个pair一个)
        self.round_trip_counter: int = 0  # 全局 round trip ID 计数器

        # ============ PnL 追踪 ============

        # Tracker 自己计算的 PnL 历史
        self.tracker_pnl_history: List[Dict] = []

        # 已实现盈亏 (基于平仓订单)
        self.realized_pnl: float = 0.0

        self.debug("📊 OrderTracker initialized (enhanced version with round trip tracking)")

    def debug(self, message: str):
        """
        调试日志输出方法

        只有当 debug_enabled=True 时才会输出日志

        Args:
            message: 日志消息
        """
        if self.debug_enabled:
            self.debug(message)

    def record_order_fill(self, order_event: OrderEvent):
        """
        记录订单成交事件

        Args:
            order_event: 订单成交事件
        """
        if order_event.status != OrderStatus.Filled:
            return

        order_id = order_event.order_id
        symbol = order_event.symbol

        # 确定账户归属
        account = self._determine_account(symbol)

        # 获取费用并转换为账户货币 (与 STATISTICS 相同的逻辑)
        fee_cash_amount = order_event.order_fee.value
        fee_in_account_currency = float(
            self.algorithm.portfolio.cash_book.convert_to_account_currency(fee_cash_amount).amount
        )

        # 创建订单记录
        order_info = {
            'order_id': order_id,
            'symbol': str(symbol.value),  # 序列化为字符串
            'symbol_obj': symbol,  # 保留对象用于内部处理
            'account': account,
            'direction': 'BUY' if order_event.direction == OrderDirection.Buy else 'SELL',
            'quantity': abs(order_event.fill_quantity),
            'signed_quantity': order_event.fill_quantity,
            'price': float(order_event.fill_price),
            'fee': fee_in_account_currency,  # 使用转换后的费用（账户货币）
            'fee_currency': fee_cash_amount.currency,  # 保存原始货币供调试
            'fee_amount_original': float(fee_cash_amount.amount),  # 保存原始金额供调试
            'time': self._serialize_datetime(order_event.utc_time),
            'time_obj': order_event.utc_time,
            'status': 'OPEN',
        }

        # 存储订单信息
        self.orders[order_id] = order_info

        # 更新最后已知价格
        self.last_prices[symbol] = float(order_event.fill_price)

        # 🔍 DEBUG: 记录手续费（显示原始费用和转换后费用）
        self.debug(
            f"💳 Fee Recorded | Order={order_id} | Symbol={symbol.value} | "
            f"Fee(Original)={order_info['fee_amount_original']:.4f} {order_info['fee_currency']} | "
            f"Fee(USD)=${order_info['fee']:.4f}"
        )

        # ========== Round Trip 追踪 ==========
        if self.strategy:
            self._track_round_trip(order_id, order_info)

        # ========== 核心：捕获 Portfolio 快照 ==========
        self.capture_snapshot(order_event)

        self.debug(
            f"📝 OrderTracker: Recorded fill | OrderID={order_id} | "
            f"Symbol={symbol.value} | Account={account} | "
            f"Direction={order_info['direction']} | "
            f"Qty={order_info['quantity']:.2f} @ ${order_info['price']:.2f}"
        )

    def capture_snapshot(self, order_event: OrderEvent):
        """
        捕获当前 Portfolio 的完整快照

        包括:
        - 所有账户的现金和持仓
        - Lean 官方计算的 PnL
        - OrderTracker 自己计算的 PnL

        Args:
            order_event: 触发快照的订单事件
        """
        snapshot = {
            'timestamp': self._serialize_datetime(self.algorithm.time),
            'event_type': 'order_fill',
            'order_id': order_event.order_id,
            'symbol': str(order_event.symbol.value),
            'accounts': {},
            'lean_pnl': {},
            'tracker_pnl': {},
        }

        # ========== 1. 捕获账户状态 ==========
        snapshot['accounts'] = self._capture_accounts_state()

        # ========== 2. Lean 官方 PnL ==========
        snapshot['lean_pnl'] = self._capture_lean_pnl()

        # ========== 3. OrderTracker 自己计算的 PnL ==========
        snapshot['tracker_pnl'] = self._calculate_tracker_pnl()

        # 添加到快照历史
        self.snapshots.append(snapshot)

        self.debug(
            f"📸 Snapshot captured | Total snapshots: {len(self.snapshots)} | "
            f"Lean PnL: ${snapshot['lean_pnl']['total_unrealized']:.2f} | "
            f"Tracker PnL: ${snapshot['tracker_pnl']['total_unrealized']:.2f}"
        )

    def _capture_accounts_state(self) -> Dict:
        """
        捕获所有账户的状态

        Returns:
            账户状态字典
        """
        accounts_state = {}

        # 检查是否是多账户模式
        if hasattr(self.algorithm.portfolio, 'GetAccount'):
            # 多账户模式
            for account_name in ['IBKR', 'Kraken']:
                try:
                    account = self.algorithm.portfolio.GetAccount(account_name)
                    accounts_state[account_name] = self._capture_single_account(account, account_name)
                except Exception as e:
                    self.debug(f"⚠️ Error capturing {account_name} account: {e}")
        else:
            # 单账户模式
            accounts_state['Main'] = self._capture_single_account(self.algorithm.portfolio, 'Main')

        return accounts_state

    def _capture_single_account(self, account, account_name: str) -> Dict:
        """
        捕获单个账户的状态

        Args:
            account: Portfolio 或子账户对象
            account_name: 账户名称

        Returns:
            账户状态字典
        """
        account_state = {
            'cash': float(account.cash) if hasattr(account, 'cash') else float(account.Cash),
            'total_portfolio_value': float(account.total_portfolio_value) if hasattr(account, 'total_portfolio_value') else float(account.TotalPortfolioValue),
            'cashbook': {},
            'holdings': {},
        }

        # 捕获 CashBook
        try:
            cashbook = account.cash_book if hasattr(account, 'cash_book') else account.CashBook
            for currency_kvp in cashbook:
                currency_symbol = str(currency_kvp.Key)
                cash_obj = currency_kvp.Value
                account_state['cashbook'][currency_symbol] = {
                    'amount': float(cash_obj.Amount),
                    'conversion_rate': float(cash_obj.ConversionRate),
                    'value_in_account_currency': float(cash_obj.ValueInAccountCurrency),
                }
        except Exception as e:
            self.debug(f"⚠️ Error capturing CashBook for {account_name}: {e}")

        # 捕获 Holdings (注意：多账户模式下 Holdings 是共享的)
        try:
            portfolio = account if hasattr(account, 'items') else self.algorithm.portfolio
            for symbol, holding in portfolio.items():
                if holding.quantity != 0:
                    account_state['holdings'][str(symbol.value)] = {
                        'quantity': float(holding.quantity),
                        'average_price': float(holding.average_price),
                        'market_price': float(holding.price),
                        'market_value': float(holding.holdings_value),
                        'unrealized_pnl': float(holding.unrealized_profit),
                    }
        except Exception as e:
            self.debug(f"⚠️ Error capturing Holdings for {account_name}: {e}")

        return account_state

    def _capture_lean_pnl(self) -> Dict:
        """
        捕获 Lean 官方计算的 PnL

        Returns:
            Lean PnL 字典
        """
        lean_pnl = {
            'total_unrealized': 0.0,
            'total_realized': 0.0,
            'by_symbol': {},
        }

        try:
            # 遍历所有持仓计算未实现盈亏
            for symbol, holding in self.algorithm.portfolio.items():
                if holding.quantity != 0:
                    unrealized = float(holding.unrealized_profit)
                    lean_pnl['total_unrealized'] += unrealized
                    lean_pnl['by_symbol'][str(symbol.value)] = {
                        'unrealized_pnl': unrealized,
                        'quantity': float(holding.quantity),
                        'average_price': float(holding.average_price),
                        'market_price': float(holding.price),
                    }

            # TODO: Lean 的 RealizedProfit 可能需要从其他地方获取
            # 目前使用我们自己追踪的 realized_pnl
            lean_pnl['total_realized'] = self.realized_pnl

        except Exception as e:
            self.debug(f"⚠️ Error capturing Lean PnL: {e}")

        return lean_pnl

    def _calculate_tracker_pnl(self) -> Dict:
        """
        计算 OrderTracker 自己的 PnL (基于 Round Trip) - 简化版本

        使用简化的 Round Trip 追踪:
        - Active Round Trips: 当前活跃的 round trips (未满4个订单)
        - Completed Round Trips: 已完成的 round trips (4个订单完成)
        - Unrealized PnL: 基于开仓成本和当前市价
        - Realized PnL: 已完成 round trips 的 PnL 总和

        Returns:
            Tracker PnL 字典
        """
        tracker_pnl = {
            'total_unrealized': 0.0,
            'total_realized': self.realized_pnl,
            'open_trades': [],
            'closed_trades': [],
            'round_trips': [],  # 所有 round trip 详情
        }

        # 如果没有 strategy 引用，无法计算配对 PnL
        if not self.strategy:
            return tracker_pnl

        try:
            # ========== 1. 处理活跃的 Round Trips (未完成) ==========
            for pair_symbol, rt in self.active_round_trips.items():
                crypto_symbol, stock_symbol = pair_symbol

                # 添加到 round_trips 列表
                tracker_pnl['round_trips'].append({
                    'round_trip_id': rt['round_trip_id'],
                    'pair': rt['pair'],
                    'status': 'OPEN',
                    'open_time': self._serialize_datetime(rt['open_time']),
                    'close_time': None,
                    'orders': rt['orders'],
                    'order_count': len(rt['orders']),
                    'open_cost': rt['open_cost'],
                    'close_revenue': rt['close_revenue'],
                    'pnl': None,
                })

                # 计算未实现盈亏
                crypto_price = self.last_prices.get(crypto_symbol, 0.0)
                stock_price = self.last_prices.get(stock_symbol, 0.0)

                # 获取持仓数量
                position = self.strategy.positions.get(pair_symbol, (0.0, 0.0))
                crypto_qty, stock_qty = position

                # 计算当前市值（如果平仓能获得的收入，未扣除手续费）
                estimated_close_revenue = abs(crypto_price * crypto_qty) + abs(stock_price * stock_qty)

                # 未实现盈亏 = 预估平仓收入 - 已发生的开仓成本
                unrealized_pnl = estimated_close_revenue - rt['open_cost']
                tracker_pnl['total_unrealized'] += unrealized_pnl

                tracker_pnl['open_trades'].append({
                    'round_trip_id': rt['round_trip_id'],
                    'pair': rt['pair'],
                    'open_time': self._serialize_datetime(rt['open_time']),
                    'order_count': len(rt['orders']),
                    'crypto_qty': crypto_qty,
                    'stock_qty': stock_qty,
                    'crypto_market_price': crypto_price,
                    'stock_market_price': stock_price,
                    'open_cost': rt['open_cost'],
                    'estimated_close_revenue': estimated_close_revenue,
                    'unrealized_pnl': unrealized_pnl,
                })

            # ========== 2. 处理已完成的 Round Trips ==========
            for pair_symbol, round_trips in self.pair_round_trips.items():
                for rt in round_trips:
                    # 添加到 round_trips 列表
                    tracker_pnl['round_trips'].append({
                        'round_trip_id': rt['round_trip_id'],
                        'pair': rt['pair'],
                        'status': 'CLOSED',
                        'open_time': self._serialize_datetime(rt['open_time']),
                        'close_time': self._serialize_datetime(rt['close_time']),
                        'orders': rt['orders'],
                        'order_count': len(rt['orders']),
                        'open_cost': rt['open_cost'],
                        'close_revenue': rt['close_revenue'],
                        'pnl': rt['pnl'],
                    })

                    # 添加到 closed_trades
                    tracker_pnl['closed_trades'].append({
                        'round_trip_id': rt['round_trip_id'],
                        'pair': rt['pair'],
                        'open_time': self._serialize_datetime(rt['open_time']),
                        'close_time': self._serialize_datetime(rt['close_time']),
                        'open_cost': rt['open_cost'],
                        'close_revenue': rt['close_revenue'],
                        'realized_pnl': rt['pnl'],
                    })

        except Exception as e:
            self.debug(f"⚠️ Error calculating Tracker PnL: {e}")

        return tracker_pnl

    def _get_average_entry_price(self, symbol: Symbol, quantity: float) -> float:
        """
        计算某个 Symbol 的平均开仓价格

        Args:
            symbol: Symbol 对象
            quantity: 当前持仓数量（带符号）

        Returns:
            平均开仓价格
        """
        if abs(quantity) < 1e-8:
            return 0.0

        # 找到该 symbol 的所有订单
        relevant_orders = [
            order for order in self.orders.values()
            if order['symbol_obj'] == symbol and order['status'] == 'OPEN'
        ]

        if not relevant_orders:
            return 0.0

        # 计算加权平均价格
        total_value = sum(order['price'] * order['signed_quantity'] for order in relevant_orders)
        total_qty = sum(order['signed_quantity'] for order in relevant_orders)

        if abs(total_qty) < 1e-8:
            return 0.0

        return abs(total_value / total_qty)

    def _track_round_trip(self, order_id: int, order_info: Dict):
        """
        追踪交易轮次 (Round Trip) - 简化版本

        逻辑：
        1. 每个交易对一次只追踪一个 round trip
        2. 一个 round trip = 4个订单（2个开仓 + 2个平仓）
        3. 使用 Portfolio.is_invested 判断是开仓还是平仓
        4. 当第4个订单完成时，计算 PnL 并标记为 CLOSED

        Args:
            order_id: 订单ID
            order_info: 订单信息字典
        """
        if not self.strategy:
            return

        # 获取订单所属的交易对
        pair_symbol = self.strategy.get_pair_by_order_id(order_id)
        if not pair_symbol:
            return

        crypto_symbol, stock_symbol = pair_symbol
        symbol = order_info['symbol_obj']

        self.debug(
            f"🔍 Round Trip Tracking | Order {order_id} | Pair: {crypto_symbol.value} <-> {stock_symbol.value}"
        )

        # 判断是开仓还是平仓：使用 Portfolio.is_invested
        # 在订单填充之前检查持仓状态来判断
        # 如果这个symbol在填充前没有持仓，这是开仓订单；如果有持仓，这是平仓订单
        # 注意：由于这是在订单填充后调用，我们需要看订单方向和当前持仓来推断

        # 简单判断：检查当前是否有活跃的 round trip
        # - 如果没有活跃 round trip → 这是第1个订单（开仓）
        # - 如果有活跃 round trip 且订单数 < 2 → 这是第2个订单（开仓）
        # - 如果有活跃 round trip 且订单数 >= 2 → 这是第3或第4个订单（平仓）

        active_trip = self.active_round_trips.get(pair_symbol)

        if active_trip is None:
            # ========== 创建新的 Round Trip ==========
            self.round_trip_counter += 1
            active_trip = {
                'round_trip_id': self.round_trip_counter,
                'pair': f"{crypto_symbol.value} <-> {stock_symbol.value}",
                'orders': [order_id],
                'open_time': order_info['time_obj'],
                'close_time': None,
                'status': 'OPEN',
                'pnl': None,
                'open_cost': 0.0,
                'close_revenue': 0.0,
            }
            self.active_round_trips[pair_symbol] = active_trip
            self.debug(
                f"🆕 Round Trip #{active_trip['round_trip_id']}: Created for {active_trip['pair']}"
            )

        # 添加订单到当前 round trip
        if order_id not in active_trip['orders']:
            active_trip['orders'].append(order_id)

        order_count = len(active_trip['orders'])

        self.debug(
            f"📊 Round Trip #{active_trip['round_trip_id']}: Added order {order_count}/4 | "
            f"Symbol: {symbol.value} | Direction: {order_info['direction']} | "
            f"Price: ${order_info['price']:.2f} | Qty: {order_info['quantity']:.2f} | Fee: ${order_info['fee']:.2f}"
        )

        # ========== 检查是否完成（4个订单） ==========
        if order_count == 4:
            # Round Trip 完成 - 使用配对计算 PnL
            active_trip['status'] = 'CLOSED'
            active_trip['close_time'] = order_info['time_obj']

            # 🔍 DEBUG: 打印要计算的订单列表
            self.debug(
                f"🔍 Calculating PnL for Round Trip #{active_trip['round_trip_id']} | Orders: {active_trip['orders']}"
            )

            # 配对计算 PnL
            pnl_result = self._calculate_paired_pnl(active_trip['orders'], crypto_symbol, stock_symbol)
            active_trip['pnl'] = pnl_result['net_pnl']  # ← 使用 net_pnl

            # ✅ 保存配对PnL详情（用于HTML显示）
            active_trip['crypto_pnl'] = pnl_result['crypto_pnl']
            active_trip['stock_pnl'] = pnl_result['stock_pnl']
            active_trip['total_fees'] = pnl_result['total_fees']

            self.debug(
                f"✅ Round Trip #{active_trip['round_trip_id']}: CLOSED | "
                f"Crypto PnL: ${pnl_result['crypto_pnl']:.2f} | "
                f"Stock PnL: ${pnl_result['stock_pnl']:.2f} | "
                f"Total Fees: ${pnl_result['total_fees']:.2f} | "
                f"Net PnL: ${active_trip['pnl']:.2f}"
            )

            # 更新已实现盈亏
            self.realized_pnl += active_trip['pnl']

            # 标记相关订单为已平仓
            for oid in active_trip['orders']:
                if oid in self.orders:
                    self.orders[oid]['status'] = 'CLOSED'

            # 将完成的 round trip 移到历史列表
            if pair_symbol not in self.pair_round_trips:
                self.pair_round_trips[pair_symbol] = []
            self.pair_round_trips[pair_symbol].append(active_trip)

            # 清除活跃 round trip
            del self.active_round_trips[pair_symbol]

    def _calculate_paired_pnl(self, order_ids: List[int], crypto_symbol: Symbol, stock_symbol: Symbol) -> Dict:
        """
        配对计算 Round Trip 的 PnL (两两结对计算)

        逻辑：
        1. 将4个订单分为 crypto 和 stock 两组
        2. 配对每组的 BUY 和 SELL 订单
        3. 计算每组的 realized PnL = (sell_price - buy_price) × quantity
        4. 累加所有手续费
        5. Net PnL = crypto_pnl + stock_pnl - total_fees

        Args:
            order_ids: 4个订单ID列表
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol

        Returns:
            PnL 计算结果字典:
            {
                'crypto_pnl': float,  # Crypto realized PnL (不含手续费)
                'stock_pnl': float,   # Stock realized PnL (不含手续费)
                'total_fees': float,  # 总手续费（4个订单）
                'net_pnl': float,     # 净盈亏 = crypto_pnl + stock_pnl - total_fees
            }
        """
        # 初始化结果
        result = {
            'crypto_pnl': 0.0,
            'stock_pnl': 0.0,
            'total_fees': 0.0,
            'net_pnl': 0.0,
        }

        # 分组：crypto 和 stock 订单
        crypto_orders = []
        stock_orders = []

        self.debug(f"🔍 Processing {len(order_ids)} orders for PnL calculation")

        for order_id in order_ids:
            order = self.orders.get(order_id)
            if not order:
                self.debug(f"⚠️ Order {order_id} not found in tracker")
                continue

            if order['symbol_obj'] == crypto_symbol:
                crypto_orders.append(order)
            elif order['symbol_obj'] == stock_symbol:
                stock_orders.append(order)

            # 累加手续费
            result['total_fees'] += order['fee']

            # 🔍 DEBUG: 打印每个订单的手续费
            self.debug(
                f"  📝 Order {order_id}: {order['symbol']} | Direction={order['direction']} | "
                f"Qty={order['quantity']:.2f} | Price=${order['price']:.2f} | "
                f"Fee=${order['fee']:.4f} | Total Fees So Far=${result['total_fees']:.4f}"
            )

        # 验证订单数量
        if len(crypto_orders) != 2 or len(stock_orders) != 2:
            self.debug(
                f"⚠️ Invalid order count: crypto={len(crypto_orders)}, stock={len(stock_orders)} (expected 2 each)"
            )
            return result

        # ========== 1. 计算 Crypto PnL（纯价差，不含手续费）==========
        crypto_buy = next((o for o in crypto_orders if o['direction'] == 'BUY'), None)
        crypto_sell = next((o for o in crypto_orders if o['direction'] == 'SELL'), None)

        if crypto_buy and crypto_sell:
            result['crypto_pnl'] = (crypto_sell['price'] - crypto_buy['price']) * crypto_sell['quantity']
            self.debug(
                f"💰 Crypto PnL: ({crypto_sell['price']:.2f} - {crypto_buy['price']:.2f}) × {crypto_sell['quantity']:.2f} "
                f"= ${result['crypto_pnl']:.2f}"
            )
        else:
            self.debug(f"⚠️ Crypto BUY/SELL pair incomplete")

        # ========== 2. 计算 Stock PnL（纯价差，不含手续费）==========
        stock_buy = next((o for o in stock_orders if o['direction'] == 'BUY'), None)
        stock_sell = next((o for o in stock_orders if o['direction'] == 'SELL'), None)

        if stock_buy and stock_sell:
            # 对于做空策略: PnL = (sell_price - buy_price) × quantity
            result['stock_pnl'] = (stock_sell['price'] - stock_buy['price']) * stock_buy['quantity']
            self.debug(
                f"💰 Stock PnL: ({stock_sell['price']:.2f} - {stock_buy['price']:.2f}) × {stock_buy['quantity']:.2f} "
                f"= ${result['stock_pnl']:.2f}"
            )
        else:
            self.debug(f"⚠️ Stock BUY/SELL pair incomplete")

        # ========== 3. 计算净盈亏（价差 - 手续费）==========
        result['net_pnl'] = result['crypto_pnl'] + result['stock_pnl'] - result['total_fees']

        self.debug(
            f"📊 Round Trip PnL Summary | Crypto: ${result['crypto_pnl']:.2f} | "
            f"Stock: ${result['stock_pnl']:.2f} | Total Fees: ${result['total_fees']:.2f} | "
            f"Net PnL: ${result['net_pnl']:.2f}"
        )

        return result

    def finalize_open_round_trips(self):
        """
        算法结束时计算所有 Open Round Trips 的 Unrealized PnL

        为每个活跃的 round trip 添加 'unrealized_pnl' 字段，用于最终显示。
        """
        if not self.strategy:
            return

        self.debug("🔚 Finalizing Open Round Trips...")

        for pair_symbol, rt in self.active_round_trips.items():
            crypto_symbol, stock_symbol = pair_symbol

            # 获取当前持仓
            position = self.strategy.positions.get(pair_symbol, (0.0, 0.0))
            crypto_qty, stock_qty = position

            if abs(crypto_qty) < 1e-8 and abs(stock_qty) < 1e-8:
                rt['unrealized_pnl'] = 0.0
                continue

            # 从 Portfolio 获取 unrealized profit
            crypto_unrealized = 0.0
            stock_unrealized = 0.0

            try:
                if abs(crypto_qty) > 1e-8:
                    crypto_holding = self.algorithm.portfolio[crypto_symbol]
                    crypto_unrealized = float(crypto_holding.unrealized_profit)

                if abs(stock_qty) > 1e-8:
                    stock_holding = self.algorithm.portfolio[stock_symbol]
                    stock_unrealized = float(stock_holding.unrealized_profit)

                # 总的未实现盈亏 = crypto + stock (Lean已经包含了手续费估算)
                rt['unrealized_pnl'] = crypto_unrealized + stock_unrealized

                self.debug(
                    f"📊 Round Trip #{rt['round_trip_id']} | {rt['pair']} | "
                    f"Unrealized PnL: ${rt['unrealized_pnl']:.2f} "
                    f"(Crypto: ${crypto_unrealized:.2f}, Stock: ${stock_unrealized:.2f})"
                )

            except Exception as e:
                self.debug(f"⚠️ Error calculating unrealized PnL for RT #{rt['round_trip_id']}: {e}")
                rt['unrealized_pnl'] = 0.0

        self.debug(f"✅ Finalized {len(self.active_round_trips)} Open Round Trips")

    def _calculate_round_trip_pnl(self, round_trip: Dict) -> float:
        """
        计算 Round Trip 的 PnL

        PnL = Close Revenue - Open Cost

        Args:
            round_trip: Round Trip 信息字典

        Returns:
            PnL 金额
        """
        return round_trip['close_revenue'] - round_trip['open_cost']

    def mark_position_closed(self, pair_symbol: Tuple[Symbol, Symbol], close_pnl: float):
        """
        标记一个交易对已平仓，并计算已实现盈亏

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            close_pnl: 平仓盈亏
        """
        self.realized_pnl += close_pnl

        # 标记相关订单为已平仓
        for order in self.orders.values():
            if self.strategy and order['order_id'] in self.strategy.order_to_pair:
                if self.strategy.order_to_pair[order['order_id']] == pair_symbol:
                    order['status'] = 'CLOSED'

    def _determine_account(self, symbol: Symbol) -> str:
        """
        根据 Symbol 确定账户归属

        Args:
            symbol: 交易标的

        Returns:
            账户名称
        """
        if symbol.security_type == SecurityType.Equity and symbol.id.market == Market.USA:
            return 'IBKR'
        elif symbol.security_type == SecurityType.Crypto and symbol.id.market == Market.Kraken:
            return 'Kraken'
        else:
            return 'Unknown'

    def _serialize_datetime(self, dt) -> str:
        """
        序列化 C# DateTime 为字符串

        Args:
            dt: C# DateTime 对象

        Returns:
            ISO 格式字符串
        """
        try:
            # C# DateTime 转 Python datetime
            return str(dt)[:19]  # 取前19个字符 "YYYY-MM-DD HH:MM:SS"
        except:
            return str(dt)

    def export_json(self, filepath: str = None):
        """
        导出所有数据为 JSON 文件 - 简化版本

        Args:
            filepath: 文件路径，如果为 None 则使用默认路径
        """
        if filepath is None:
            filepath = "order_tracker_export.json"

        # 收集所有 round trips 数据（活跃的 + 已完成的）
        all_round_trips = []

        # 1. 添加活跃的 round trips
        for pair_symbol, rt in self.active_round_trips.items():
            all_round_trips.append({
                'round_trip_id': rt['round_trip_id'],
                'pair': rt['pair'],
                'status': 'OPEN',
                'open_time': self._serialize_datetime(rt['open_time']),
                'close_time': None,
                'orders': rt['orders'],
                'order_count': len(rt['orders']),
                'pnl': None,
                'unrealized_pnl': rt.get('unrealized_pnl'),  # 从 finalize_open_round_trips() 获取
                'crypto_pnl': rt.get('crypto_pnl', 0.0),
                'stock_pnl': rt.get('stock_pnl', 0.0),
                'total_fees': rt.get('total_fees', 0.0),
            })

        # 2. 添加已完成的 round trips
        for pair_symbol, trips in self.pair_round_trips.items():
            for rt in trips:
                all_round_trips.append({
                    'round_trip_id': rt['round_trip_id'],
                    'pair': rt['pair'],
                    'status': 'CLOSED',
                    'open_time': self._serialize_datetime(rt['open_time']),
                    'close_time': self._serialize_datetime(rt['close_time']) if rt['close_time'] else None,
                    'orders': rt['orders'],
                    'order_count': len(rt['orders']),
                    'pnl': rt['pnl'],
                    # ✅ 详细的配对PnL字段
                    'crypto_pnl': rt.get('crypto_pnl', 0.0),
                    'stock_pnl': rt.get('stock_pnl', 0.0),
                    'total_fees': rt.get('total_fees', 0.0),
                })

        export_data = {
            'meta': {
                'start_time': self.snapshots[0]['timestamp'] if self.snapshots else None,
                'end_time': self.snapshots[-1]['timestamp'] if self.snapshots else None,
                'total_snapshots': len(self.snapshots),
                'total_orders': len(self.orders),
                'total_round_trips': len(all_round_trips),
                'active_round_trips': len(self.active_round_trips),
                'completed_round_trips': sum(len(trips) for trips in self.pair_round_trips.values()),
            },
            'snapshots': self.snapshots,
            'orders': [order for order in self.orders.values()],
            'round_trips': all_round_trips,  # 所有 round trip（活跃 + 完成）
            'summary': {
                'final_realized_pnl': self.realized_pnl,
                'final_snapshot': self.snapshots[-1] if self.snapshots else None,
            }
        }

        try:
            # 移除不可序列化的对象
            export_data_clean = self._clean_for_json(export_data)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data_clean, f, indent=2, ensure_ascii=False)

            self.debug(f"✅ Data exported to {filepath}")

        except Exception as e:
            self.debug(f"❌ Error exporting JSON: {e}")

    def _clean_for_json(self, obj):
        """
        清理对象，移除不可序列化的部分（如 Symbol 对象）

        Args:
            obj: 要清理的对象

        Returns:
            清理后的对象
        """
        if isinstance(obj, dict):
            return {k: self._clean_for_json(v) for k, v in obj.items() if not k.endswith('_obj')}
        elif isinstance(obj, list):
            return [self._clean_for_json(item) for item in obj]
        elif isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        else:
            return str(obj)

    def generate_report(self) -> str:
        """
        生成文本格式的报告

        Returns:
            格式化的报告字符串
        """
        report = []
        report.append("=" * 100)
        report.append("📊 OrderTracker - Enhanced Report")
        report.append("=" * 100)

        # 基本统计
        report.append(f"\n【基本统计】")
        report.append(f"总快照数: {len(self.snapshots)}")
        report.append(f"总订单数: {len(self.orders)}")

        if self.snapshots:
            final_snapshot = self.snapshots[-1]
            report.append(f"\n【最终状态】")
            report.append(f"时间: {final_snapshot['timestamp']}")
            report.append(f"Lean 未实现盈亏: ${final_snapshot['lean_pnl']['total_unrealized']:.2f}")
            report.append(f"Tracker 未实现盈亏: ${final_snapshot['tracker_pnl']['total_unrealized']:.2f}")
            report.append(f"Tracker 已实现盈亏: ${final_snapshot['tracker_pnl']['total_realized']:.2f}")

            # PnL 差异分析
            pnl_diff = final_snapshot['lean_pnl']['total_unrealized'] - final_snapshot['tracker_pnl']['total_unrealized']
            report.append(f"PnL 差异: ${pnl_diff:.2f}")

        report.append("=" * 100)
        report.append("✅ OrderTracker 报告生成完成")
        report.append("=" * 100)

        return "\n".join(report)
