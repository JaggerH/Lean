"""
HTML Report Generator for OrderTracker - 逐笔订单成交视图

重点展示:
1. 按交易对(pair_symbol)分组的订单列表
2. 每次 on_order_event 触发后的完整账户快照
   - 主账户的 CashBook 和 Portfolio
   - IBKR 子账户的 CashBook 和 Portfolio
   - Kraken 子账户的 CashBook 和 Portfolio
"""
import json
from typing import Dict, List
from pathlib import Path


class HTMLReportGenerator:
    """
    HTML 报告生成器 - 逐笔订单详情视图
    """

    def __init__(self, tracker_data: Dict):
        """
        初始化生成器

        Args:
            tracker_data: OrderTracker.export_json() 导出的数据
        """
        self.data = tracker_data
        self.snapshots = tracker_data.get('snapshots', [])
        self.orders = tracker_data.get('orders', [])
        self.round_trips = tracker_data.get('round_trips', [])
        self.meta = tracker_data.get('meta', {})

        # 准备按时间顺序的快照列表（附加订单信息）
        self.snapshots_with_orders = self._prepare_snapshots()

    def _prepare_snapshots(self) -> List[Dict]:
        """
        准备快照列表，附加订单详情

        Returns:
            按时间顺序的快照列表
        """
        snapshots_list = []

        for snapshot in self.snapshots:
            order_id = snapshot.get('order_id')
            snapshot_copy = snapshot.copy()
            snapshot_copy['order_info'] = next(
                (o for o in self.orders if o['order_id'] == order_id),
                None
            )
            snapshots_list.append(snapshot_copy)

        return snapshots_list

    def _build_round_trips_section(self) -> str:
        """构建 Round Trips 汇总表"""
        if not self.round_trips:
            return """
            <section>
                <h2>Round Trips Summary</h2>
                <p style="color: #858585;">No round trips recorded</p>
            </section>
            """

        # 分离 OPEN 和 CLOSED 的 round trips
        open_trips = [rt for rt in self.round_trips if rt.get('status') == 'OPEN']
        closed_trips = [rt for rt in self.round_trips if rt.get('status') == 'CLOSED']

        # 计算总 PnL
        total_realized_pnl = sum(rt.get('pnl', 0) for rt in closed_trips if rt.get('pnl') is not None)

        # 构建 CLOSED Round Trips 表格
        closed_rows = []
        for rt in closed_trips:
            rt_id = rt.get('round_trip_id', 'N/A')
            pair = rt.get('pair', 'N/A')
            open_time = rt.get('open_time', 'N/A')
            close_time = rt.get('close_time', 'N/A')

            # ✅ 添加详细的配对PnL字段
            crypto_pnl = rt.get('crypto_pnl', 0)
            stock_pnl = rt.get('stock_pnl', 0)
            total_fees = rt.get('total_fees', 0)
            pnl = rt.get('pnl', 0)

            open_orders = ', '.join(map(str, rt.get('open_orders', [])))
            close_orders = ', '.join(map(str, rt.get('close_orders', [])))

            crypto_pnl_class = 'positive' if crypto_pnl >= 0 else 'negative'
            stock_pnl_class = 'positive' if stock_pnl >= 0 else 'negative'
            pnl_class = 'positive' if pnl >= 0 else 'negative'

            closed_rows.append(f"""
            <tr>
                <td class="number">#{rt_id}</td>
                <td>{pair}</td>
                <td>{open_time}</td>
                <td>{close_time}</td>
                <td class="number {crypto_pnl_class}">${crypto_pnl:.2f}</td>
                <td class="number {stock_pnl_class}">${stock_pnl:.2f}</td>
                <td class="number" style="color: #f48771;">${total_fees:.2f}</td>
                <td class="number {pnl_class}"><strong>${pnl:.2f}</strong></td>
                <td style="font-size: 10px; color: #858585;">{open_orders}</td>
                <td style="font-size: 10px; color: #858585;">{close_orders}</td>
            </tr>
            """)

        closed_table = f"""
        <h3 style="color: #4ec9b0; margin-top: 15px;">Closed Round Trips - Detailed Paired PnL</h3>
        <table class="holdings-table" style="font-size: 12px;">
            <thead>
                <tr>
                    <th>RT ID</th>
                    <th>Trading Pair</th>
                    <th>Open Time</th>
                    <th>Close Time</th>
                    <th>Crypto PnL</th>
                    <th>Stock PnL</th>
                    <th>Total Fees</th>
                    <th>Net PnL</th>
                    <th>Open Orders</th>
                    <th>Close Orders</th>
                </tr>
            </thead>
            <tbody>
                {''.join(closed_rows) if closed_rows else '<tr><td colspan="10">No closed round trips</td></tr>'}
            </tbody>
        </table>
        <p style="margin-top: 10px; color: #4ec9b0;">
            <strong>Total Realized PnL: </strong>
            <span class="number {'positive' if total_realized_pnl >= 0 else 'negative'}" style="font-size: 16px;">
                ${total_realized_pnl:.2f}
            </span>
        </p>
        """

        # 构建 OPEN Round Trips 表格
        open_rows = []
        for rt in open_trips:
            rt_id = rt.get('round_trip_id', 'N/A')
            pair = rt.get('pair', 'N/A')
            open_time = rt.get('open_time', 'N/A')
            open_cost = rt.get('open_cost', 0)
            # ✅ 添加未实现盈亏字段
            unrealized_pnl = rt.get('unrealized_pnl', 0)
            open_orders = ', '.join(map(str, rt.get('open_orders', [])))

            unrealized_class = 'positive' if unrealized_pnl >= 0 else 'negative'

            open_rows.append(f"""
            <tr>
                <td class="number">#{rt_id}</td>
                <td>{pair}</td>
                <td>{open_time}</td>
                <td class="number">${open_cost:.2f}</td>
                <td class="number {unrealized_class}">${unrealized_pnl:.2f}</td>
                <td style="font-size: 10px; color: #858585;">{open_orders}</td>
            </tr>
            """)

        open_table = f"""
        <h3 style="color: #dcdcaa; margin-top: 20px;">Open Round Trips</h3>
        <table class="holdings-table" style="font-size: 12px;">
            <thead>
                <tr>
                    <th>RT ID</th>
                    <th>Trading Pair</th>
                    <th>Open Time</th>
                    <th>Open Cost</th>
                    <th>Unrealized PnL</th>
                    <th>Open Orders</th>
                </tr>
            </thead>
            <tbody>
                {''.join(open_rows) if open_rows else '<tr><td colspan="6">No open round trips</td></tr>'}
            </tbody>
        </table>
        """

        return f"""
        <section style="margin-bottom: 30px;">
            <h2>Round Trips Summary - Paired PnL by Trading Pair</h2>
            <div style="background: #2d2d30; padding: 15px; border-radius: 6px; border-left: 4px solid #c586c0;">
                <p style="color: #cccccc; margin-bottom: 10px;">
                    Round Trip = 完整的开仓+平仓周期，按交易对（Crypto + Stock）计算配对 PnL
                </p>
                {closed_table}
                {open_table}
            </div>
        </section>
        """

    def generate_html(self, output_path: str = None) -> str:
        """
        生成完整的 HTML 报告

        Args:
            output_path: 输出文件路径

        Returns:
            HTML 字符串
        """
        if output_path is None:
            output_path = "order_tracker_report.html"

        html = self._build_html()

        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        # Note: Removed emoji to avoid Windows console encoding issues
        return html

    def _build_html(self) -> str:
        """构建完整的 HTML 文档"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OrderTracker - 逐笔订单详情</title>
    <style>
        {self._get_css()}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>OrderTracker - 逐笔订单成交详情</h1>
            <div class="meta-info">
                <p><strong>Start Time:</strong> {self.meta.get('start_time', 'N/A')}</p>
                <p><strong>End Time:</strong> {self.meta.get('end_time', 'N/A')}</p>
                <p><strong>Total Snapshots:</strong> {self.meta.get('total_snapshots', 0)}</p>
                <p><strong>Total Orders:</strong> {self.meta.get('total_orders', 0)}</p>
                <p><strong>Total Round Trips:</strong> {self.meta.get('total_round_trips', 0)}</p>
            </div>
            <div style="margin-top: 15px; padding: 10px; background: #2d2d30; border-radius: 4px;">
                <label style="cursor: pointer; color: #cccccc;">
                    <input type="checkbox" id="cryptoOnlyFilter" style="margin-right: 8px;">
                    Only show Crypto orders
                </label>
            </div>
        </header>

        {self._build_round_trips_section()}

        {self._build_snapshots_section()}
    </div>

    <script>
        {self._get_javascript()}
    </script>
</body>
</html>"""

    def _get_css(self) -> str:
        """返回 CSS 样式"""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            font-size: 13px;
        }

        .container {
            max-width: 1800px;
            margin: 0 auto;
            background: #252526;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.5);
        }

        header {
            border-bottom: 2px solid #007acc;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }

        h1 {
            color: #4ec9b0;
            margin-bottom: 10px;
            font-size: 24px;
        }

        h2 {
            color: #569cd6;
            margin: 25px 0 15px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid #3e3e42;
            font-size: 18px;
        }

        h3 {
            color: #dcdcaa;
            margin: 15px 0 10px 0;
            font-size: 15px;
        }

        .meta-info {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            background: #2d2d30;
            padding: 12px;
            border-radius: 4px;
            border-left: 3px solid #007acc;
        }

        .meta-info p {
            margin: 3px 0;
            color: #cccccc;
        }

        .pair-group {
            margin: 30px 0;
            padding: 20px;
            background: #2d2d30;
            border-radius: 6px;
            border-left: 4px solid #c586c0;
        }

        .pair-group h2 {
            color: #c586c0;
            border-bottom: 2px solid #c586c0;
        }

        .snapshot-card {
            margin: 20px 0;
            padding: 15px;
            background: #1e1e1e;
            border-radius: 4px;
            border-left: 3px solid #4ec9b0;
        }

        .snapshot-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #3e3e42;
        }

        .snapshot-header .timestamp {
            color: #4ec9b0;
            font-weight: bold;
        }

        .snapshot-header .order-info {
            color: #dcdcaa;
        }

        .order-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
            margin-left: 8px;
        }

        .order-badge.buy {
            background: #0e639c;
            color: #4fc3f7;
        }

        .order-badge.sell {
            background: #5a1d1d;
            color: #f48771;
        }

        .accounts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 15px;
            margin: 15px 0;
        }

        .account-panel {
            background: #252526;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #3e3e42;
        }

        .account-panel h3 {
            margin-top: 0;
            padding-bottom: 8px;
            border-bottom: 1px solid #3e3e42;
        }

        .account-panel.ibkr h3 {
            color: #ce9178;
        }

        .account-panel.kraken h3 {
            color: #4fc3f7;
        }

        .cashbook-table, .holdings-table {
            width: 100%;
            margin: 10px 0;
            border-collapse: collapse;
        }

        .cashbook-table th, .holdings-table th {
            background: #37373d;
            color: #cccccc;
            padding: 6px 8px;
            text-align: left;
            font-weight: bold;
            font-size: 11px;
            border-bottom: 1px solid #3e3e42;
        }

        .cashbook-table td, .holdings-table td {
            padding: 5px 8px;
            border-bottom: 1px solid #2d2d30;
            color: #d4d4d4;
        }

        .cashbook-table tr:hover, .holdings-table tr:hover {
            background: #2d2d30;
        }

        .number {
            font-family: 'Consolas', monospace;
            color: #b5cea8;
        }

        .positive {
            color: #4ec9b0;
        }

        .negative {
            color: #f48771;
        }

        .pnl-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            margin: 15px 0;
            padding: 12px;
            background: #2d2d30;
            border-radius: 4px;
        }

        .pnl-item {
            text-align: center;
        }

        .pnl-item .label {
            color: #858585;
            font-size: 11px;
            margin-bottom: 5px;
        }

        .pnl-item .value {
            font-size: 16px;
            font-weight: bold;
        }

        .collapsible {
            cursor: pointer;
            user-select: none;
        }

        .collapsible:hover {
            opacity: 0.8;
        }

        .collapsible::before {
            content: '▼ ';
            display: inline-block;
            transition: transform 0.2s;
        }

        .collapsible.collapsed::before {
            transform: rotate(-90deg);
        }

        .collapsible-content {
            max-height: 3000px;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }

        .collapsible-content.hidden {
            max-height: 0;
        }
        """

    def _build_snapshots_section(self) -> str:
        """构建按时间顺序的所有订单详情"""
        if not self.snapshots_with_orders:
            return "<section><p>No orders found</p></section>"

        snapshot_cards = []

        for i, snapshot in enumerate(self.snapshots_with_orders, 1):
            snapshot_cards.append(self._build_snapshot_card(i, snapshot))

        return f"""
        <section>
            <h2>Order Fill History (Time Order)</h2>
            {''.join(snapshot_cards)}
        </section>
        """

    def _build_snapshot_card(self, index: int, snapshot: Dict) -> str:
        """构建单个快照卡片"""
        order_info = snapshot.get('order_info', {})
        timestamp = snapshot.get('timestamp', 'N/A')
        symbol = snapshot.get('symbol', 'N/A')
        order_id = snapshot.get('order_id', 'N/A')

        # 订单信息
        direction = order_info.get('direction', 'N/A')
        quantity = order_info.get('quantity', 0)
        price = order_info.get('price', 0)
        fee = order_info.get('fee', 0)
        account = order_info.get('account', 'N/A')

        badge_class = 'buy' if direction == 'BUY' else 'sell'

        # PnL 信息
        lean_pnl = snapshot.get('lean_pnl', {})
        tracker_pnl = snapshot.get('tracker_pnl', {})

        lean_unrealized = lean_pnl.get('total_unrealized', 0)
        tracker_unrealized = tracker_pnl.get('total_unrealized', 0)
        tracker_realized = tracker_pnl.get('total_realized', 0)

        lean_class = 'positive' if lean_unrealized >= 0 else 'negative'
        tracker_class = 'positive' if tracker_unrealized >= 0 else 'negative'

        # 查找该订单所属的 Round Trip
        round_trip_info = self._find_round_trip_for_order(order_id)
        round_trip_badge = ""
        if round_trip_info:
            rt_id = round_trip_info.get('round_trip_id', '?')
            rt_status = round_trip_info.get('status', 'UNKNOWN')
            rt_pnl = round_trip_info.get('pnl', None)

            status_color = '#4ec9b0' if rt_status == 'CLOSED' else '#dcdcaa'
            pnl_display = f" | PnL: ${rt_pnl:.2f}" if rt_pnl is not None else ""

            round_trip_badge = f"""
            <span style="color: {status_color}; margin-left: 10px;">
                | Round Trip #{rt_id} [{rt_status}]{pnl_display}
            </span>
            """

        # 判断订单类型（Crypto or Stock）
        symbol_type = 'crypto' if 'USD' in symbol and account == 'Kraken' else 'stock'

        # 账户状态
        accounts = snapshot.get('accounts', {})
        accounts_html = self._build_accounts_panels(accounts)

        return f"""
        <div class="snapshot-card" data-symbol-type="{symbol_type}">
            <div class="snapshot-header">
                <div>
                    <span class="timestamp">#{index} | {timestamp}</span>
                    <span class="order-info">
                        Order #{order_id} | {symbol}
                        <span class="order-badge {badge_class}">{direction}</span>
                        <span class="number">{quantity:.4f} @ ${price:.2f}</span>
                        <span style="color: #858585">| Fee: ${fee:.4f}</span>
                        <span style="color: #dcdcaa">| Account: {account}</span>
                        {round_trip_badge}
                    </span>
                </div>
            </div>

            <div class="pnl-summary">
                <div class="pnl-item">
                    <div class="label">Lean Unrealized PnL</div>
                    <div class="value {lean_class}">${lean_unrealized:.2f}</div>
                </div>
                <div class="pnl-item">
                    <div class="label">Tracker Unrealized PnL</div>
                    <div class="value {tracker_class}">${tracker_unrealized:.2f}</div>
                </div>
                <div class="pnl-item">
                    <div class="label">Tracker Realized PnL</div>
                    <div class="value">${tracker_realized:.2f}</div>
                </div>
                <div class="pnl-item">
                    <div class="label">PnL Difference</div>
                    <div class="value">${(lean_unrealized - tracker_unrealized):.2f}</div>
                </div>
            </div>

            <h3 class="collapsible" onclick="toggleCollapse(this)">Account Snapshots</h3>
            <div class="collapsible-content">
                {accounts_html}
            </div>
        </div>
        """

    def _build_accounts_panels(self, accounts: Dict) -> str:
        """构建账户面板 - 包括主账户和所有子账户"""
        if not accounts:
            return "<p>No account data</p>"

        panels = []

        # 按顺序显示：主账户 → IBKR → Kraken
        account_order = []

        # 主账户（聚合的Portfolio数据）
        if 'IBKR' in accounts or 'Kraken' in accounts:
            # 多账户模式：添加主账户面板（显示聚合数据）
            account_order.append(('Main (Aggregated)', self._build_main_account_panel(accounts), 'main'))

        # 子账户
        if 'IBKR' in accounts:
            account_order.append(('IBKR', accounts['IBKR'], 'ibkr'))
        if 'Kraken' in accounts:
            account_order.append(('Kraken', accounts['Kraken'], 'kraken'))
        if 'Main' in accounts:
            # 单账户模式
            account_order.append(('Main', accounts['Main'], 'main'))

        # 生成面板
        panels.append('<div class="accounts-grid">')
        for name, account_data, css_class in account_order:
            if isinstance(account_data, str):
                # 主账户（已经是HTML字符串）
                panels.append(account_data)
            else:
                panels.append(self._build_single_account_panel(name, account_data, css_class))
        panels.append('</div>')

        return '\n'.join(panels)

    def _build_main_account_panel(self, accounts: Dict) -> str:
        """构建主账户面板（显示聚合的CashBook和Holdings）"""
        # 聚合所有子账户的数据
        total_cash = 0.0
        total_value = 0.0
        aggregated_cashbook = {}
        aggregated_holdings = {}

        for account_name, account_data in accounts.items():
            if account_name in ['IBKR', 'Kraken']:
                total_cash += account_data.get('cash', 0)
                total_value += account_data.get('total_portfolio_value', 0)

                # 聚合 CashBook
                cashbook = account_data.get('cashbook', {})
                for currency, cash_data in cashbook.items():
                    if currency not in aggregated_cashbook:
                        aggregated_cashbook[currency] = {
                            'amount': 0.0,
                            'value_in_account_currency': 0.0,
                        }
                    aggregated_cashbook[currency]['amount'] += cash_data.get('amount', 0)
                    aggregated_cashbook[currency]['value_in_account_currency'] += cash_data.get('value_in_account_currency', 0)

                # 聚合 Holdings
                holdings = account_data.get('holdings', {})
                for symbol, holding_data in holdings.items():
                    if symbol not in aggregated_holdings:
                        aggregated_holdings[symbol] = {
                            'quantity': 0.0,
                            'market_value': 0.0,
                            'unrealized_pnl': 0.0,
                        }
                    aggregated_holdings[symbol]['quantity'] += holding_data.get('quantity', 0)
                    aggregated_holdings[symbol]['market_value'] += holding_data.get('market_value', 0)
                    aggregated_holdings[symbol]['unrealized_pnl'] += holding_data.get('unrealized_pnl', 0)

        # CashBook 表格
        cashbook_rows = []
        for currency, cash_data in aggregated_cashbook.items():
            amount = cash_data['amount']
            value = cash_data['value_in_account_currency']

            cashbook_rows.append(f"""
            <tr>
                <td>{currency}</td>
                <td class="number">{amount:,.4f}</td>
                <td class="number">${value:,.2f}</td>
            </tr>
            """)

        cashbook_html = f"""
        <table class="cashbook-table">
            <thead>
                <tr>
                    <th>Currency</th>
                    <th>Amount</th>
                    <th>Value (USD)</th>
                </tr>
            </thead>
            <tbody>
                {''.join(cashbook_rows) if cashbook_rows else '<tr><td colspan="3">No cash</td></tr>'}
            </tbody>
        </table>
        """ if aggregated_cashbook else "<p style='color: #858585;'>No CashBook data</p>"

        # Holdings 表格
        holdings_rows = []
        for symbol, holding_data in aggregated_holdings.items():
            qty = holding_data['quantity']
            market_value = holding_data['market_value']
            unrealized = holding_data['unrealized_pnl']

            unrealized_class = 'positive' if unrealized >= 0 else 'negative'

            holdings_rows.append(f"""
            <tr>
                <td>{symbol}</td>
                <td class="number">{qty:.4f}</td>
                <td class="number">${market_value:,.2f}</td>
                <td class="number {unrealized_class}">${unrealized:.2f}</td>
            </tr>
            """)

        holdings_html = f"""
        <table class="holdings-table">
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Market Value</th>
                    <th>Unrealized PnL</th>
                </tr>
            </thead>
            <tbody>
                {''.join(holdings_rows) if holdings_rows else '<tr><td colspan="4">No holdings</td></tr>'}
            </tbody>
        </table>
        """ if aggregated_holdings else "<p style='color: #858585;'>No holdings data</p>"

        return f"""
        <div class="account-panel main">
            <h3>Main Account (Aggregated)</h3>
            <p style="margin: 8px 0;">
                <strong>Total Cash:</strong> <span class="number">${total_cash:,.2f}</span> |
                <strong>Total Portfolio Value:</strong> <span class="number">${total_value:,.2f}</span>
            </p>

            <h4 style="color: #858585; margin: 10px 0 5px 0; font-size: 12px;">Aggregated CashBook</h4>
            {cashbook_html}

            <h4 style="color: #858585; margin: 10px 0 5px 0; font-size: 12px;">Aggregated Holdings</h4>
            {holdings_html}
        </div>
        """

    def _build_single_account_panel(self, name: str, account_data: Dict, css_class: str) -> str:
        """构建单个账户面板"""
        cash = account_data.get('cash', 0)
        total_value = account_data.get('total_portfolio_value', 0)
        cashbook = account_data.get('cashbook', {})
        holdings = account_data.get('holdings', {})

        # CashBook 表格
        cashbook_rows = []
        for currency, cash_data in cashbook.items():
            amount = cash_data.get('amount', 0)
            rate = cash_data.get('conversion_rate', 0)
            value = cash_data.get('value_in_account_currency', 0)

            cashbook_rows.append(f"""
            <tr>
                <td>{currency}</td>
                <td class="number">{amount:,.4f}</td>
                <td class="number">{rate:.6f}</td>
                <td class="number">${value:,.2f}</td>
            </tr>
            """)

        cashbook_html = f"""
        <table class="cashbook-table">
            <thead>
                <tr>
                    <th>Currency</th>
                    <th>Amount</th>
                    <th>Rate</th>
                    <th>Value (USD)</th>
                </tr>
            </thead>
            <tbody>
                {''.join(cashbook_rows) if cashbook_rows else '<tr><td colspan="4">No cash</td></tr>'}
            </tbody>
        </table>
        """ if cashbook else "<p style='color: #858585;'>No CashBook data</p>"

        # Holdings 表格
        holdings_rows = []
        for symbol, holding_data in holdings.items():
            qty = holding_data.get('quantity', 0)
            avg_price = holding_data.get('average_price', 0)
            market_price = holding_data.get('market_price', 0)
            market_value = holding_data.get('market_value', 0)
            unrealized = holding_data.get('unrealized_pnl', 0)

            unrealized_class = 'positive' if unrealized >= 0 else 'negative'

            holdings_rows.append(f"""
            <tr>
                <td>{symbol}</td>
                <td class="number">{qty:.4f}</td>
                <td class="number">${avg_price:.2f}</td>
                <td class="number">${market_price:.2f}</td>
                <td class="number">${market_value:,.2f}</td>
                <td class="number {unrealized_class}">${unrealized:.2f}</td>
            </tr>
            """)

        holdings_html = f"""
        <table class="holdings-table">
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Avg Price</th>
                    <th>Market Price</th>
                    <th>Market Value</th>
                    <th>Unrealized PnL</th>
                </tr>
            </thead>
            <tbody>
                {''.join(holdings_rows) if holdings_rows else '<tr><td colspan="6">No holdings</td></tr>'}
            </tbody>
        </table>
        """ if holdings else "<p style='color: #858585;'>No holdings data</p>"

        return f"""
        <div class="account-panel {css_class}">
            <h3>{name} Account</h3>
            <p style="margin: 8px 0;">
                <strong>Cash:</strong> <span class="number">${cash:,.2f}</span> |
                <strong>Total Value:</strong> <span class="number">${total_value:,.2f}</span>
            </p>

            <h4 style="color: #858585; margin: 10px 0 5px 0; font-size: 12px;">CashBook</h4>
            {cashbook_html}

            <h4 style="color: #858585; margin: 10px 0 5px 0; font-size: 12px;">Holdings</h4>
            {holdings_html}
        </div>
        """

    def _find_round_trip_for_order(self, order_id: int) -> Dict:
        """
        查找指定订单所属的 Round Trip

        Args:
            order_id: 订单ID

        Returns:
            Round Trip 信息字典，如果未找到则返回 None
        """
        for rt in self.round_trips:
            open_orders = rt.get('open_orders', [])
            close_orders = rt.get('close_orders', [])

            if order_id in open_orders or order_id in close_orders:
                return rt

        return None

    def _get_javascript(self) -> str:
        """生成 JavaScript 代码"""
        return """
        function toggleCollapse(element) {
            element.classList.toggle('collapsed');
            const content = element.nextElementSibling;
            content.classList.toggle('hidden');
        }

        // Crypto订单过滤功能
        document.addEventListener('DOMContentLoaded', function() {
            // Account Snapshots 默认展开，不需要额外操作

            // 添加过滤器事件监听
            const filterCheckbox = document.getElementById('cryptoOnlyFilter');
            if (filterCheckbox) {
                filterCheckbox.addEventListener('change', function(e) {
                    const cards = document.querySelectorAll('.snapshot-card');
                    cards.forEach(card => {
                        const symbolType = card.getAttribute('data-symbol-type');
                        if (e.target.checked && symbolType !== 'crypto') {
                            card.style.display = 'none';
                        } else {
                            card.style.display = 'block';
                        }
                    });
                });
            }
        });
        """


def generate_html_report(json_filepath: str, output_filepath: str = None):
    """
    从 JSON 文件生成 HTML 报告

    Args:
        json_filepath: OrderTracker 导出的 JSON 文件路径
        output_filepath: HTML 输出文件路径
    """
    # 读取 JSON 数据
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 生成 HTML
    generator = HTMLReportGenerator(data)

    if output_filepath is None:
        output_filepath = json_filepath.replace('.json', '.html')

    generator.generate_html(output_filepath)
    # Note: Removed emoji to avoid Windows console encoding issues
    print(f"HTML report generated: {output_filepath}")
