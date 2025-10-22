"""
Grid HTML Report Generator - 可视化 Grid Trading Framework 执行数据

专门为 GridOrderTracker 设计的 HTML 报告生成器

核心功能:
1. ExecutionTarget Timeline - 按时间顺序展示所有 ExecutionTarget
2. OrderGroup 详情卡片 - 展示每个 OrderGroup 的订单执行历史
3. Round Trip 汇总表 - 展示完整的 Entry → Exit 周期
4. Portfolio 快照对比 - 展示账户状态变化
"""
import json
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime


class GridHTMLReportGenerator:
    """
    Grid Trading Framework HTML 报告生成器

    数据结构要求:
    - execution_targets: List[ExecutionTargetSnapshot]
    - round_trips: List[RoundTrip]
    - portfolio_snapshots: List[PortfolioSnapshot]
    - meta: Dict (metadata)
    """

    def __init__(self, tracker_data: Dict):
        """
        初始化生成器

        Args:
            tracker_data: GridOrderTracker.export_json() 导出的数据
        """
        self.data = tracker_data
        self.execution_targets = tracker_data.get('execution_targets', [])
        self.round_trips = tracker_data.get('round_trips', [])
        self.portfolio_snapshots = tracker_data.get('portfolio_snapshots', [])
        self.meta = tracker_data.get('meta', {})

        # 状态映射
        self.status_map = {
            '0': 'Invalid',
            '1': 'New',
            '2': 'Submitted',
            '3': 'PartiallyFilled',
            '4': 'Filled',
            '5': 'Canceled',
            '6': 'None',
            '7': 'UpdateSubmitted',
            '8': 'CancelPending'
        }

    def generate_html(self, output_path: str = None) -> str:
        """
        生成完整的 HTML 报告

        Args:
            output_path: 输出文件路径

        Returns:
            HTML 字符串
        """
        if output_path is None:
            output_path = "grid_report.html"

        html = self._build_html()

        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        return html

    def _build_html(self) -> str:
        """构建完整的 HTML 文档"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grid Trading Report - ExecutionTarget Analysis</title>
    <style>
        {self._get_css()}
    </style>
</head>
<body>
    <div class="container">
        {self._build_header()}
        {self._build_round_trips_section()}
        {self._build_execution_targets_section()}
        {self._build_portfolio_timeline()}
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
            font-family: 'Segoe UI', 'Consolas', 'Monaco', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            font-size: 13px;
        }

        .container {
            max-width: 1600px;
            margin: 0 auto;
            background: #252526;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.5);
        }

        header {
            border-bottom: 3px solid #007acc;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }

        h1 {
            color: #4ec9b0;
            margin-bottom: 15px;
            font-size: 28px;
            font-weight: 600;
        }

        h2 {
            color: #569cd6;
            margin: 30px 0 15px 0;
            padding-bottom: 10px;
            border-bottom: 2px solid #3e3e42;
            font-size: 20px;
        }

        h3 {
            color: #dcdcaa;
            margin: 15px 0 10px 0;
            font-size: 16px;
        }

        .meta-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }

        .meta-card {
            background: #2d2d30;
            padding: 15px;
            border-radius: 6px;
            border-left: 3px solid #007acc;
        }

        .meta-card .label {
            color: #858585;
            font-size: 11px;
            margin-bottom: 5px;
            text-transform: uppercase;
        }

        .meta-card .value {
            color: #d4d4d4;
            font-size: 18px;
            font-weight: bold;
        }

        /* Round Trip 样式 */
        .round-trip-table {
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background: #1e1e1e;
        }

        .round-trip-table th {
            background: #37373d;
            color: #cccccc;
            padding: 10px;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid #007acc;
        }

        .round-trip-table td {
            padding: 10px;
            border-bottom: 1px solid #2d2d30;
        }

        .round-trip-table tr:hover {
            background: #2d2d30;
        }

        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }

        .status-badge.open {
            background: #1a472a;
            color: #4ec9b0;
        }

        .status-badge.closed {
            background: #37373d;
            color: #858585;
        }

        /* ExecutionTarget Timeline */
        .execution-timeline {
            position: relative;
            padding-left: 40px;
            margin: 20px 0;
        }

        .execution-timeline::before {
            content: '';
            position: absolute;
            left: 15px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: #3e3e42;
        }

        .execution-card {
            position: relative;
            margin-bottom: 30px;
            background: #1e1e1e;
            border-radius: 6px;
            border-left: 4px solid #4ec9b0;
            padding: 20px;
        }

        .execution-card.entry {
            border-left-color: #4fc3f7;
        }

        .execution-card.exit {
            border-left-color: #f48771;
        }

        .execution-card.canceled {
            border-left-color: #858585;
            opacity: 0.7;
        }

        .execution-card::before {
            content: '';
            position: absolute;
            left: -44px;
            top: 20px;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #4ec9b0;
            border: 3px solid #1e1e1e;
        }

        .execution-card.entry::before {
            background: #4fc3f7;
        }

        .execution-card.exit::before {
            background: #f48771;
        }

        .execution-card.canceled::before {
            background: #858585;
        }

        .execution-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #3e3e42;
        }

        .execution-header .title {
            color: #4ec9b0;
            font-size: 16px;
            font-weight: bold;
        }

        .execution-header .timestamp {
            color: #858585;
            font-size: 12px;
        }

        .execution-info {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 15px 0;
            padding: 15px;
            background: #2d2d30;
            border-radius: 4px;
        }

        .info-item {
            display: flex;
            flex-direction: column;
        }

        .info-item .label {
            color: #858585;
            font-size: 11px;
            margin-bottom: 5px;
        }

        .info-item .value {
            color: #d4d4d4;
            font-size: 14px;
            font-weight: bold;
        }

        /* OrderGroup 卡片 */
        .order-groups {
            margin-top: 15px;
        }

        .order-group-card {
            background: #2d2d30;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 10px;
            border-left: 3px solid #dcdcaa;
        }

        .order-group-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .order-group-header .title {
            color: #dcdcaa;
            font-weight: bold;
        }

        .orders-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 12px;
        }

        .orders-table th {
            background: #37373d;
            color: #cccccc;
            padding: 8px;
            text-align: left;
            font-size: 11px;
        }

        .orders-table td {
            padding: 8px;
            border-bottom: 1px solid #252526;
        }

        .orders-table tr:hover {
            background: #37373d;
        }

        .direction-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: bold;
        }

        .direction-badge.buy {
            background: #0e639c;
            color: #4fc3f7;
        }

        .direction-badge.sell {
            background: #5a1d1d;
            color: #f48771;
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

        /* 折叠功能 */
        .collapsible {
            cursor: pointer;
            user-select: none;
            padding: 10px;
            background: #2d2d30;
            border-radius: 4px;
            margin: 10px 0;
        }

        .collapsible:hover {
            background: #37373d;
        }

        .collapsible::before {
            content: '▼ ';
            display: inline-block;
            transition: transform 0.2s;
            margin-right: 8px;
        }

        .collapsible.collapsed::before {
            transform: rotate(-90deg);
        }

        .collapsible-content {
            max-height: 5000px;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }

        .collapsible-content.hidden {
            max-height: 0;
        }

        /* Portfolio 对比 */
        .portfolio-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 15px;
            margin: 15px 0;
        }

        .account-card {
            background: #2d2d30;
            padding: 15px;
            border-radius: 6px;
            border-left: 3px solid #c586c0;
        }

        .account-card.ibkr {
            border-left-color: #ce9178;
        }

        .account-card.kraken {
            border-left-color: #4fc3f7;
        }

        .holdings-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 11px;
        }

        .holdings-table th {
            background: #37373d;
            color: #cccccc;
            padding: 6px;
            text-align: left;
        }

        .holdings-table td {
            padding: 6px;
            border-bottom: 1px solid #252526;
        }

        /* 过滤器 */
        .filter-panel {
            background: #2d2d30;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
        }

        .filter-panel label {
            display: inline-block;
            margin-right: 20px;
            cursor: pointer;
            color: #cccccc;
        }

        .filter-panel input[type="checkbox"] {
            margin-right: 8px;
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #858585;
            background: #2d2d30;
            border-radius: 6px;
            margin: 20px 0;
        }

        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        """

    def _build_header(self) -> str:
        """构建报告头部"""
        total_targets = len(self.execution_targets)
        entry_targets = len([t for t in self.execution_targets if t.get('level_type') == 'ENTRY'])
        exit_targets = len([t for t in self.execution_targets if t.get('level_type') == 'EXIT'])
        filled_targets = len([t for t in self.execution_targets if self._get_status_name(t.get('status')) in ['Filled', 'PartiallyFilled']])
        canceled_targets = len([t for t in self.execution_targets if self._get_status_name(t.get('status')) == 'Canceled'])

        return f"""
        <header>
            <h1>Grid Trading Execution Report</h1>
            <div class="meta-grid">
                <div class="meta-card">
                    <div class="label">Test Period</div>
                    <div class="value" style="font-size: 14px;">
                        {self.meta.get('start_time', 'N/A')} <br>
                        to {self.meta.get('end_time', 'N/A')}
                    </div>
                </div>
                <div class="meta-card">
                    <div class="label">Total ExecutionTargets</div>
                    <div class="value">{total_targets}</div>
                    <div style="font-size: 11px; color: #858585; margin-top: 5px;">
                        Entry: {entry_targets} | Exit: {exit_targets}
                    </div>
                </div>
                <div class="meta-card">
                    <div class="label">Execution Status</div>
                    <div class="value" style="font-size: 14px;">
                        <span style="color: #4ec9b0;">Filled: {filled_targets}</span><br>
                        <span style="color: #858585;">Canceled: {canceled_targets}</span>
                    </div>
                </div>
                <div class="meta-card">
                    <div class="label">Round Trips</div>
                    <div class="value">{len(self.round_trips)}</div>
                    <div style="font-size: 11px; color: #858585; margin-top: 5px;">
                        Completed Entry-Exit Cycles
                    </div>
                </div>
            </div>
        </header>
        """

    def _build_round_trips_section(self) -> str:
        """构建 Round Trips 汇总区域"""
        if not self.round_trips:
            return """
            <section>
                <h2>Round Trips Summary</h2>
                <div class="empty-state">
                    <div class="empty-state-icon">📊</div>
                    <p>No Round Trips completed yet</p>
                    <p style="font-size: 11px; margin-top: 10px;">
                        Round Trip = ENTRY (filled) → EXIT (filled)
                    </p>
                </div>
            </section>
            """

        # 分离 OPEN 和 CLOSED
        open_trips = [rt for rt in self.round_trips if rt.get('status') == 'OPEN']
        closed_trips = [rt for rt in self.round_trips if rt.get('status') == 'CLOSED']

        total_pnl = sum(rt.get('net_pnl', 0) for rt in closed_trips if rt.get('net_pnl') is not None)

        # Closed Round Trips 表格
        closed_rows = []
        for rt in closed_trips:
            rt_id = rt.get('round_trip_id', 'N/A')
            pair = rt.get('pair', 'N/A')
            entry_level = rt.get('entry_level_id', 'N/A')
            exit_level = rt.get('exit_level_id', 'N/A')

            # 新数据结构字段
            entry_targets_count = len(rt.get('entry_targets', []))
            exit_targets_count = len(rt.get('exit_targets', []))
            entry_time_range = rt.get('entry_time_range', 'N/A')
            exit_time_range = rt.get('exit_time_range', 'N/A')
            total_entry_cost = rt.get('total_entry_cost', 0)
            total_exit_revenue = rt.get('total_exit_revenue', 0)
            total_entry_fee = rt.get('total_entry_fee', 0)
            total_exit_fee = rt.get('total_exit_fee', 0)
            total_fee = total_entry_fee + total_exit_fee
            net_pnl = rt.get('net_pnl', 0)

            pnl_class = 'positive' if net_pnl >= 0 else 'negative'

            closed_rows.append(f"""
            <tr>
                <td class="number">#{rt_id}</td>
                <td>{pair}</td>
                <td>{entry_level} <span style="color: #858585;">({entry_targets_count})</span></td>
                <td>{exit_level} <span style="color: #858585;">({exit_targets_count})</span></td>
                <td style="font-size: 11px;">{entry_time_range}</td>
                <td style="font-size: 11px;">{exit_time_range}</td>
                <td class="number">${total_entry_cost:.2f}</td>
                <td class="number">${total_exit_revenue:.2f}</td>
                <td class="number" style="color: #f48771;">${total_fee:.4f}</td>
                <td class="number {pnl_class}"><strong>${net_pnl:.2f}</strong></td>
            </tr>
            """)

        closed_table = f"""
        <h3>Closed Round Trips ({len(closed_trips)})</h3>
        <table class="round-trip-table">
            <thead>
                <tr>
                    <th>RT ID</th>
                    <th>Pair</th>
                    <th>Entry Level</th>
                    <th>Exit Level</th>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Entry Cost</th>
                    <th>Exit Revenue</th>
                    <th>Total Fee</th>
                    <th>Net PnL</th>
                </tr>
            </thead>
            <tbody>
                {''.join(closed_rows) if closed_rows else '<tr><td colspan="10">No closed round trips</td></tr>'}
            </tbody>
        </table>
        <p style="margin-top: 15px; font-size: 16px;">
            <strong>Total Realized PnL: </strong>
            <span class="number {'positive' if total_pnl >= 0 else 'negative'}">
                ${total_pnl:.2f}
            </span>
        </p>
        """ if closed_trips else ""

        # Open Round Trips 表格
        open_rows = []
        for rt in open_trips:
            rt_id = rt.get('round_trip_id', 'N/A')
            pair = rt.get('pair', 'N/A')
            entry_level = rt.get('entry_level_id', 'N/A')
            exit_level = rt.get('exit_level_id', 'N/A')

            # 新数据结构字段
            entry_targets_count = len(rt.get('entry_targets', []))
            exit_targets_count = len(rt.get('exit_targets', []))
            entry_time_range = rt.get('entry_time_range', 'N/A')
            exit_time_range = rt.get('exit_time_range', 'N/A')
            total_entry_cost = rt.get('total_entry_cost', 0)
            total_exit_revenue = rt.get('total_exit_revenue', 0)
            total_entry_fee = rt.get('total_entry_fee', 0)
            total_exit_fee = rt.get('total_exit_fee', 0)
            total_fee = total_entry_fee + total_exit_fee
            net_pnl = rt.get('net_pnl', 0)

            pnl_class = 'positive' if net_pnl >= 0 else 'negative'

            open_rows.append(f"""
            <tr>
                <td class="number">#{rt_id}</td>
                <td>{pair}</td>
                <td>{entry_level} <span style="color: #858585;">({entry_targets_count})</span></td>
                <td>{exit_level} <span style="color: #858585;">({exit_targets_count})</span></td>
                <td style="font-size: 11px;">{entry_time_range}</td>
                <td style="font-size: 11px;">{exit_time_range}</td>
                <td class="number">${total_entry_cost:.2f}</td>
                <td class="number">${total_exit_revenue:.2f}</td>
                <td class="number" style="color: #f48771;">${total_fee:.4f}</td>
                <td class="number {pnl_class}">${net_pnl:.2f}</td>
                <td><span class="status-badge open">OPEN</span></td>
            </tr>
            """)

        open_table = f"""
        <h3 style="margin-top: 25px;">Open Round Trips ({len(open_trips)})</h3>
        <table class="round-trip-table">
            <thead>
                <tr>
                    <th>RT ID</th>
                    <th>Pair</th>
                    <th>Entry Level</th>
                    <th>Exit Level</th>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Entry Cost</th>
                    <th>Exit Revenue</th>
                    <th>Total Fee</th>
                    <th>Net PnL</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {''.join(open_rows) if open_rows else '<tr><td colspan="11">No open round trips</td></tr>'}
            </tbody>
        </table>
        """ if open_trips else ""

        return f"""
        <section>
            <h2>Round Trips Summary</h2>
            {closed_table}
            {open_table}
        </section>
        """

    def _build_execution_targets_section(self) -> str:
        """构建 ExecutionTarget Timeline"""
        if not self.execution_targets:
            return """
            <section>
                <h2>ExecutionTarget Timeline</h2>
                <div class="empty-state">
                    <div class="empty-state-icon">📝</div>
                    <p>No ExecutionTargets recorded</p>
                </div>
            </section>
            """

        # 添加过滤器
        filter_html = """
        <div class="filter-panel">
            <strong style="margin-right: 20px;">Filter:</strong>
            <label>
                <input type="checkbox" id="showEntry" checked>
                Show ENTRY Targets
            </label>
            <label>
                <input type="checkbox" id="showExit" checked>
                Show EXIT Targets
            </label>
            <label>
                <input type="checkbox" id="showCanceled" checked>
                Show Canceled
            </label>
        </div>
        """

        # 生成 ExecutionTarget 卡片
        target_cards = []
        for target in self.execution_targets:
            target_cards.append(self._build_execution_target_card(target))

        return f"""
        <section>
            <h2>ExecutionTarget Timeline</h2>
            {filter_html}
            <div class="execution-timeline">
                {''.join(target_cards)}
            </div>
        </section>
        """

    def _build_execution_target_card(self, target: Dict) -> str:
        """构建单个 ExecutionTarget 卡片"""
        grid_id = target.get('grid_id', 'N/A')
        level_type = target.get('level_type', 'N/A')
        status_code = target.get('status', '0')
        status_name = self._get_status_name(status_code)
        timestamp = target.get('timestamp', 'N/A')
        target_qty = target.get('target_qty', {})
        total_filled_qty = target.get('total_filled_qty', [0, 0])
        total_cost = target.get('total_cost', 0)
        total_fee = target.get('total_fee', 0)
        order_groups = target.get('order_groups', [])

        # CSS 类
        type_class = level_type.lower()
        status_class = 'canceled' if status_name == 'Canceled' else ''

        # 目标数量显示
        symbols = list(target_qty.keys())
        crypto_symbol = symbols[0] if len(symbols) > 0 else 'N/A'
        stock_symbol = symbols[1] if len(symbols) > 1 else 'N/A'

        target_crypto = target_qty.get(crypto_symbol, 0)
        target_stock = target_qty.get(stock_symbol, 0)
        filled_crypto = total_filled_qty[0]
        filled_stock = total_filled_qty[1]

        # 填充进度
        crypto_fill_pct = (abs(filled_crypto) / abs(target_crypto) * 100) if target_crypto != 0 else 0
        stock_fill_pct = (abs(filled_stock) / abs(target_stock) * 100) if target_stock != 0 else 0

        # ExecutionTarget 信息
        info_html = f"""
        <div class="execution-info">
            <div class="info-item">
                <div class="label">Grid ID</div>
                <div class="value">{grid_id}</div>
            </div>
            <div class="info-item">
                <div class="label">Type</div>
                <div class="value">{level_type}</div>
            </div>
            <div class="info-item">
                <div class="label">Status</div>
                <div class="value">
                    <span class="status-badge {'open' if status_name == 'Filled' else 'closed'}">
                        {status_name}
                    </span>
                </div>
            </div>
            <div class="info-item">
                <div class="label">Target Qty</div>
                <div class="value" style="font-size: 12px;">
                    {crypto_symbol}: {target_crypto:.2f}<br>
                    {stock_symbol}: {target_stock:.2f}
                </div>
            </div>
            <div class="info-item">
                <div class="label">Filled Qty</div>
                <div class="value" style="font-size: 12px;">
                    {filled_crypto:.2f} ({crypto_fill_pct:.1f}%)<br>
                    {filled_stock:.2f} ({stock_fill_pct:.1f}%)
                </div>
            </div>
            <div class="info-item">
                <div class="label">Total Cost</div>
                <div class="value">${total_cost:.2f}</div>
            </div>
            <div class="info-item">
                <div class="label">Total Fee</div>
                <div class="value" style="color: #f48771;">${total_fee:.4f}</div>
            </div>
            <div class="info-item">
                <div class="label">OrderGroups</div>
                <div class="value">{len(order_groups)}</div>
            </div>
        </div>
        """

        # OrderGroups
        order_groups_html = ""
        if order_groups:
            order_groups_html = '<div class="order-groups">'
            order_groups_html += '<h3 class="collapsible" onclick="toggleCollapse(this)">Order Groups Details</h3>'
            order_groups_html += '<div class="collapsible-content">'

            for i, og in enumerate(order_groups, 1):
                order_groups_html += self._build_order_group_card(i, og)

            order_groups_html += '</div></div>'

        return f"""
        <div class="execution-card {type_class} {status_class}"
             data-level-type="{level_type}"
             data-status="{status_name}">
            <div class="execution-header">
                <div class="title">{level_type} - {grid_id}</div>
                <div class="timestamp">{timestamp}</div>
            </div>
            {info_html}
            {order_groups_html}
        </div>
        """

    def _build_order_group_card(self, index: int, order_group: Dict) -> str:
        """构建 OrderGroup 卡片"""
        og_type = order_group.get('type', 'N/A')
        og_status = self._get_status_name(order_group.get('status', '0'))
        expected_spread = order_group.get('expected_spread_pct', 0)
        actual_spread = order_group.get('actual_spread_pct', None)
        orders = order_group.get('orders', [])
        filled_qty = order_group.get('filled_qty', [0, 0])
        total_fee = order_group.get('total_fee', 0)

        spread_display = f"{actual_spread*100:.4f}%" if actual_spread is not None else "N/A"

        # OrderGroup 头部
        header_html = f"""
        <div class="order-group-header">
            <div class="title">OrderGroup #{index}</div>
            <div style="font-size: 11px; color: #858585;">
                Status: {og_status} | Expected Spread: {expected_spread*100:.2f}% |
                Actual Spread: {spread_display} | Total Fee: ${total_fee:.2f}
            </div>
        </div>
        """

        # Orders 表格
        order_rows = []
        for order in orders:
            order_id = order.get('order_id', 'N/A')
            symbol = order.get('symbol', 'N/A')
            direction = order.get('direction', 'N/A')
            quantity = order.get('quantity', 0)
            fill_price = order.get('fill_price', 0)
            fee = order.get('fee', 0)
            status = order.get('status', 'N/A')
            time = order.get('time', 'N/A')

            direction_class = 'buy' if direction == 'BUY' else 'sell'

            order_rows.append(f"""
            <tr>
                <td class="number">#{order_id}</td>
                <td>{symbol}</td>
                <td><span class="direction-badge {direction_class}">{direction}</span></td>
                <td class="number">{quantity:.4f}</td>
                <td class="number">${fill_price:.2f}</td>
                <td class="number">${fee:.4f}</td>
                <td>{status}</td>
                <td style="font-size: 10px; color: #858585;">{time}</td>
            </tr>
            """)

        orders_table = f"""
        <table class="orders-table">
            <thead>
                <tr>
                    <th>Order ID</th>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Quantity</th>
                    <th>Fill Price</th>
                    <th>Fee</th>
                    <th>Status</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
                {''.join(order_rows) if order_rows else '<tr><td colspan="8">No orders</td></tr>'}
            </tbody>
        </table>
        """

        return f"""
        <div class="order-group-card">
            {header_html}
            {orders_table}
        </div>
        """

    def _build_portfolio_timeline(self) -> str:
        """构建 Portfolio 快照时间线"""
        if not self.portfolio_snapshots:
            return """
            <section>
                <h2>Portfolio Snapshots</h2>
                <div class="empty-state">
                    <div class="empty-state-icon">💼</div>
                    <p>No portfolio snapshots recorded</p>
                </div>
            </section>
            """

        # 只显示第一个和最后一个快照
        first_snapshot = self.portfolio_snapshots[0]
        last_snapshot = self.portfolio_snapshots[-1]

        first_html = self._build_portfolio_snapshot(first_snapshot, "Initial State")
        last_html = self._build_portfolio_snapshot(last_snapshot, "Final State")

        return f"""
        <section>
            <h2>Portfolio Snapshots</h2>
            <p style="color: #858585; margin-bottom: 15px;">
                Showing initial and final portfolio states. Total snapshots: {len(self.portfolio_snapshots)}
            </p>

            <h3>Initial State - {first_snapshot.get('timestamp', 'N/A')}</h3>
            {first_html}

            <h3 style="margin-top: 30px;">Final State - {last_snapshot.get('timestamp', 'N/A')}</h3>
            {last_html}
        </section>
        """

    def _build_portfolio_snapshot(self, snapshot: Dict, title: str) -> str:
        """构建单个 Portfolio 快照"""
        accounts = snapshot.get('accounts', {})

        if not accounts:
            return "<p>No account data</p>"

        cards = []

        for account_name, account_data in accounts.items():
            css_class = account_name.lower()
            cards.append(self._build_account_card(account_name, account_data, css_class))

        return f"""
        <div class="portfolio-grid">
            {''.join(cards)}
        </div>
        """

    def _build_account_card(self, name: str, account_data: Dict, css_class: str) -> str:
        """构建账户卡片"""
        cash = account_data.get('cash', 0)
        total_value = account_data.get('total_portfolio_value', 0)
        holdings = account_data.get('holdings', {})

        # Holdings 表格
        holdings_rows = []
        for symbol, holding in holdings.items():
            qty = holding.get('quantity', 0)
            market_value = holding.get('market_value', 0)
            unrealized = holding.get('unrealized_pnl', 0)

            unrealized_class = 'positive' if unrealized >= 0 else 'negative'

            holdings_rows.append(f"""
            <tr>
                <td>{symbol}</td>
                <td class="number">{qty:.4f}</td>
                <td class="number">${market_value:,.2f}</td>
                <td class="number {unrealized_class}">${unrealized:.2f}</td>
            </tr>
            """)

        holdings_table = f"""
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
        """ if holdings else "<p style='color: #858585;'>No holdings</p>"

        return f"""
        <div class="account-card {css_class}">
            <h3>{name} Account</h3>
            <p style="margin: 10px 0;">
                <strong>Cash:</strong> <span class="number">${cash:,.2f}</span><br>
                <strong>Total Value:</strong> <span class="number">${total_value:,.2f}</span>
            </p>
            {holdings_table}
        </div>
        """

    def _get_status_name(self, status_code: str) -> str:
        """获取状态名称"""
        return self.status_map.get(str(status_code), 'Unknown')

    def _get_javascript(self) -> str:
        """返回 JavaScript 代码"""
        return """
        function toggleCollapse(element) {
            element.classList.toggle('collapsed');
            const content = element.nextElementSibling;
            content.classList.toggle('hidden');
        }

        // 页面加载后初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 默认折叠所有 OrderGroup
            const collapsibles = document.querySelectorAll('.collapsible');
            collapsibles.forEach(el => {
                el.classList.add('collapsed');
                el.nextElementSibling.classList.add('hidden');
            });

            // 过滤器事件
            const showEntry = document.getElementById('showEntry');
            const showExit = document.getElementById('showExit');
            const showCanceled = document.getElementById('showCanceled');

            function applyFilters() {
                const cards = document.querySelectorAll('.execution-card');

                cards.forEach(card => {
                    const levelType = card.getAttribute('data-level-type');
                    const status = card.getAttribute('data-status');

                    let visible = true;

                    if (levelType === 'ENTRY' && !showEntry.checked) {
                        visible = false;
                    }
                    if (levelType === 'EXIT' && !showExit.checked) {
                        visible = false;
                    }
                    if (status === 'Canceled' && !showCanceled.checked) {
                        visible = false;
                    }

                    card.style.display = visible ? 'block' : 'none';
                });
            }

            if (showEntry) showEntry.addEventListener('change', applyFilters);
            if (showExit) showExit.addEventListener('change', applyFilters);
            if (showCanceled) showCanceled.addEventListener('change', applyFilters);
        });
        """


def generate_grid_html_report(json_filepath: str, output_filepath: str = None):
    """
    从 JSON 文件生成 Grid HTML 报告

    Args:
        json_filepath: GridOrderTracker 导出的 JSON 文件路径
        output_filepath: HTML 输出文件路径
    """
    # 读取 JSON 数据
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 生成 HTML
    generator = GridHTMLReportGenerator(data)

    if output_filepath is None:
        output_filepath = json_filepath.replace('.json', '_grid.html')

    generator.generate_html(output_filepath)
    print(f"Grid HTML report generated: {output_filepath}")


# CLI 入口
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python grid_html_generator.py <json_filepath> [output_filepath]")
        sys.exit(1)

    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    generate_grid_html_report(json_file, output_file)
