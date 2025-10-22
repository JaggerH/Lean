/**
 * Backtest Report Renderer - 动态生成Grid Trading回测报告
 *
 * 从JSON数据动态生成HTML报告,无需后端生成静态HTML
 * 支持交互功能:筛选、排序、搜索
 */

class BacktestReportRenderer {
    constructor(jsonData, containerId = 'report-container') {
        this.data = jsonData;
        this.executionTargets = jsonData.execution_targets || [];
        this.portfolioSnapshots = jsonData.portfolio_snapshots || [];
        this.gridPositionSnapshots = jsonData.grid_position_snapshots || [];
        this.meta = jsonData.meta || {};
        this.containerId = containerId;

        // 状态映射
        this.statusMap = {
            '0': 'Invalid',
            '1': 'New',
            '2': 'Submitted',
            '3': 'PartiallyFilled',
            '4': 'Filled',
            '5': 'Canceled',
            '6': 'None',
            '7': 'UpdateSubmitted',
            '8': 'CancelPending'
        };

        // 过滤状态
        this.filters = {
            showEntry: true,
            showExit: true,
            showCanceled: true
        };
    }

    /**
     * 渲染完整报告
     */
    render() {
        const container = document.getElementById(this.containerId);
        if (!container) {
            console.error(`Container #${this.containerId} not found`);
            return;
        }

        // 按正确顺序渲染: 1.头部统计 → 2.账户快照 → 3.ExecutionTarget Timeline
        container.innerHTML = `
            ${this.buildHeader()}
            ${this.buildPortfolioTimeline()}
            ${this.buildExecutionTargetsSection()}
        `;

        // 绑定事件
        this.attachEventListeners();

        // 默认折叠所有OrderGroup
        this.collapseAllOrderGroups();
    }

    /**
     * 构建报告头部
     */
    buildHeader() {
        const totalTargets = this.executionTargets.length;
        const entryTargets = this.executionTargets.filter(t => t.level_type === 'ENTRY').length;
        const exitTargets = this.executionTargets.filter(t => t.level_type === 'EXIT').length;
        const filledTargets = this.executionTargets.filter(t =>
            ['Filled', 'PartiallyFilled'].includes(this.getStatusName(t.status))
        ).length;
        const canceledTargets = this.executionTargets.filter(t =>
            this.getStatusName(t.status) === 'Canceled'
        ).length;

        return `
        <header>
            <h1>Grid Trading Execution Report</h1>
            <div class="meta-grid">
                <div class="meta-card">
                    <div class="label">Test Period</div>
                    <div class="value" style="font-size: 14px;">
                        ${this.meta.start_time || 'N/A'} <br>
                        to ${this.meta.end_time || 'N/A'}
                    </div>
                </div>
                <div class="meta-card">
                    <div class="label">Total ExecutionTargets</div>
                    <div class="value">${totalTargets}</div>
                    <div style="font-size: 11px; color: #858585; margin-top: 5px;">
                        Entry: ${entryTargets} | Exit: ${exitTargets}
                    </div>
                </div>
                <div class="meta-card">
                    <div class="label">Execution Status</div>
                    <div class="value" style="font-size: 14px;">
                        <span style="color: #4ec9b0;">Filled: ${filledTargets}</span><br>
                        <span style="color: #858585;">Canceled: ${canceledTargets}</span>
                    </div>
                </div>
                <div class="meta-card">
                    <div class="label">Grid Positions</div>
                    <div class="value">${this.gridPositionSnapshots.length}</div>
                    <div style="font-size: 11px; color: #858585; margin-top: 5px;">
                        Portfolio Snapshots: ${this.portfolioSnapshots.length}
                    </div>
                </div>
            </div>
        </header>
        `;
    }

    /**
     * 构建ExecutionTarget Timeline区域
     */
    buildExecutionTargetsSection() {
        if (this.executionTargets.length === 0) {
            return `
            <section>
                <h2>ExecutionTarget Timeline</h2>
                <div class="empty-state">
                    <div class="empty-state-icon">📝</div>
                    <p>No ExecutionTargets recorded</p>
                </div>
            </section>
            `;
        }

        const filterPanel = `
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
        `;

        const targetCards = this.executionTargets.map(target =>
            this.buildExecutionTargetCard(target)
        ).join('');

        return `
        <section>
            <h2>ExecutionTarget Timeline</h2>
            ${filterPanel}
            <div class="execution-timeline">
                ${targetCards}
            </div>
        </section>
        `;
    }

    /**
     * 构建单个ExecutionTarget卡片
     */
    buildExecutionTargetCard(target) {
        const gridId = target.grid_id || 'N/A';
        const levelType = target.level_type || 'N/A';
        const statusCode = target.status || '0';
        const statusName = this.getStatusName(statusCode);
        const timestamp = target.timestamp || 'N/A';
        const targetQty = target.target_qty || {};
        const totalFilledQty = target.total_filled_qty || [0, 0];
        const totalCost = target.total_cost || 0;
        const totalFee = target.total_fee || 0;
        const orderGroups = target.order_groups || [];

        // CSS类
        const typeClass = levelType.toLowerCase();
        const statusClass = statusName === 'Canceled' ? 'canceled' : '';

        // 目标数量
        const symbols = Object.keys(targetQty);
        const cryptoSymbol = symbols[0] || 'N/A';
        const stockSymbol = symbols[1] || 'N/A';
        const targetCrypto = targetQty[cryptoSymbol] || 0;
        const targetStock = targetQty[stockSymbol] || 0;
        const filledCrypto = totalFilledQty[0];
        const filledStock = totalFilledQty[1];

        // 填充进度
        const cryptoFillPct = targetCrypto !== 0 ? (Math.abs(filledCrypto) / Math.abs(targetCrypto) * 100) : 0;
        const stockFillPct = targetStock !== 0 ? (Math.abs(filledStock) / Math.abs(targetStock) * 100) : 0;

        // ExecutionTarget信息
        const infoHtml = `
        <div class="execution-info">
            <div class="info-item">
                <div class="label">Grid ID</div>
                <div class="value">${gridId}</div>
            </div>
            <div class="info-item">
                <div class="label">Type</div>
                <div class="value">${levelType}</div>
            </div>
            <div class="info-item">
                <div class="label">Status</div>
                <div class="value">
                    <span class="status-badge ${statusName === 'Filled' ? 'open' : 'closed'}">
                        ${statusName}
                    </span>
                </div>
            </div>
            <div class="info-item">
                <div class="label">Target Qty</div>
                <div class="value" style="font-size: 12px;">
                    ${cryptoSymbol}: ${targetCrypto.toFixed(2)}<br>
                    ${stockSymbol}: ${targetStock.toFixed(2)}
                </div>
            </div>
            <div class="info-item">
                <div class="label">Filled Qty</div>
                <div class="value" style="font-size: 12px;">
                    ${filledCrypto.toFixed(2)} (${cryptoFillPct.toFixed(1)}%)<br>
                    ${filledStock.toFixed(2)} (${stockFillPct.toFixed(1)}%)
                </div>
            </div>
            <div class="info-item">
                <div class="label">Total Cost</div>
                <div class="value">$${totalCost.toFixed(2)}</div>
            </div>
            <div class="info-item">
                <div class="label">Total Fee</div>
                <div class="value" style="color: #f48771;">$${totalFee.toFixed(4)}</div>
            </div>
            <div class="info-item">
                <div class="label">OrderGroups</div>
                <div class="value">${orderGroups.length}</div>
            </div>
        </div>
        `;

        // OrderGroups
        let orderGroupsHtml = '';
        if (orderGroups.length > 0) {
            const groupCards = orderGroups.map((og, i) =>
                this.buildOrderGroupCard(i + 1, og)
            ).join('');

            orderGroupsHtml = `
            <div class="order-groups">
                <h3 class="collapsible" onclick="window.reportRenderer.toggleCollapse(event)">Order Groups Details</h3>
                <div class="collapsible-content">
                    ${groupCards}
                </div>
            </div>
            `;
        }

        return `
        <div class="execution-card ${typeClass} ${statusClass}"
             data-level-type="${levelType}"
             data-status="${statusName}">
            <div class="execution-header">
                <div class="title">${levelType} - ${gridId}</div>
                <div class="timestamp">${timestamp}</div>
            </div>
            ${infoHtml}
            ${orderGroupsHtml}
        </div>
        `;
    }

    /**
     * 构建OrderGroup卡片
     */
    buildOrderGroupCard(index, orderGroup) {
        const ogType = orderGroup.type || 'N/A';
        const ogStatus = this.getStatusName(orderGroup.status || '0');
        const expectedSpread = orderGroup.expected_spread_pct || 0;
        const actualSpread = orderGroup.actual_spread_pct;
        const orders = orderGroup.orders || [];
        const filledQty = orderGroup.filled_qty || [0, 0];
        const totalFee = orderGroup.total_fee || 0;

        const spreadDisplay = actualSpread !== null && actualSpread !== undefined ?
            `${(actualSpread * 100).toFixed(4)}%` : 'N/A';

        // 计算AVG Prices
        const avgPrices = this.calculateAvgPrices(orders);
        const avgPricesHtml = Object.entries(avgPrices)
            .map(([symbol, price]) => `${symbol}: $${price.toFixed(2)}`)
            .join(' | ');

        // OrderGroup头部
        const headerHtml = `
        <div class="order-group-header">
            <div class="title">OrderGroup #${index}</div>
            <div style="font-size: 11px; color: #858585;">
                Status: ${ogStatus} | Expected Spread: ${(expectedSpread * 100).toFixed(2)}% |
                Actual Spread: ${spreadDisplay} | Total Fee: $${totalFee.toFixed(2)}
            </div>
            ${avgPricesHtml ? `
            <div style="font-size: 11px; color: #dcdcaa; margin-top: 5px;">
                AVG Prices: ${avgPricesHtml}
            </div>
            ` : ''}
        </div>
        `;

        // Orders表格
        const orderRows = orders.map(order => {
            const orderId = order.order_id || 'N/A';
            const symbol = order.symbol || 'N/A';
            const direction = order.direction || 'N/A';
            const quantity = order.quantity || 0;
            const fillPrice = order.fill_price || 0;
            const status = order.status || 'N/A';
            const time = order.time || 'N/A';
            const directionClass = direction === 'BUY' ? 'buy' : 'sell';

            return `
            <tr>
                <td class="number">#${orderId}</td>
                <td>${symbol}</td>
                <td><span class="direction-badge ${directionClass}">${direction}</span></td>
                <td class="number">${quantity.toFixed(4)}</td>
                <td class="number">$${fillPrice.toFixed(2)}</td>
                <td>${status}</td>
                <td style="font-size: 10px; color: #858585;">${time}</td>
            </tr>
            `;
        }).join('');

        const ordersTable = `
        <table class="orders-table">
            <thead>
                <tr>
                    <th>Order ID</th>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Quantity</th>
                    <th>Fill Price</th>
                    <th>Status</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
                ${orderRows.length > 0 ? orderRows : '<tr><td colspan="7">No orders</td></tr>'}
            </tbody>
        </table>
        `;

        return `
        <div class="order-group-card">
            ${headerHtml}
            ${ordersTable}
        </div>
        `;
    }

    /**
     * 构建Portfolio快照时间线
     */
    buildPortfolioTimeline() {
        if (this.portfolioSnapshots.length === 0) {
            return `
            <section>
                <h2>Portfolio Snapshots</h2>
                <div class="empty-state">
                    <div class="empty-state-icon">💼</div>
                    <p>No portfolio snapshots recorded</p>
                </div>
            </section>
            `;
        }

        // 只显示第一个和最后一个快照
        const firstSnapshot = this.portfolioSnapshots[0];
        const lastSnapshot = this.portfolioSnapshots[this.portfolioSnapshots.length - 1];

        const firstHtml = this.buildPortfolioSnapshot(firstSnapshot);
        const lastHtml = this.buildPortfolioSnapshot(lastSnapshot);

        return `
        <section>
            <h2>Portfolio Snapshots</h2>
            <p style="color: #858585; margin-bottom: 15px;">
                Showing initial and final portfolio states. Total snapshots: ${this.portfolioSnapshots.length}
            </p>

            <h3>Initial State - ${firstSnapshot.timestamp || 'N/A'}</h3>
            ${firstHtml}

            <h3 style="margin-top: 30px;">Final State - ${lastSnapshot.timestamp || 'N/A'}</h3>
            ${lastHtml}
        </section>
        `;
    }

    /**
     * 构建单个Portfolio快照
     */
    buildPortfolioSnapshot(snapshot) {
        const accounts = snapshot.accounts || {};

        if (Object.keys(accounts).length === 0) {
            return '<p>No account data</p>';
        }

        const cards = Object.entries(accounts).map(([accountName, accountData]) => {
            const cssClass = accountName.toLowerCase();
            return this.buildAccountCard(accountName, accountData, cssClass);
        }).join('');

        return `
        <div class="portfolio-grid">
            ${cards}
        </div>
        `;
    }

    /**
     * 构建账户卡片
     */
    buildAccountCard(name, accountData, cssClass) {
        const cash = accountData.cash || 0;
        const totalValue = accountData.total_portfolio_value || 0;
        const holdings = accountData.holdings || {};

        // Holdings表格
        const holdingsRows = Object.entries(holdings).map(([symbol, holding]) => {
            const qty = holding.quantity || 0;
            const marketValue = holding.market_value || 0;
            const unrealized = holding.unrealized_pnl || 0;
            const unrealizedClass = unrealized >= 0 ? 'positive' : 'negative';

            return `
            <tr>
                <td>${symbol}</td>
                <td class="number">${qty.toFixed(4)}</td>
                <td class="number">$${marketValue.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                <td class="number ${unrealizedClass}">$${unrealized.toFixed(2)}</td>
            </tr>
            `;
        }).join('');

        const holdingsTable = Object.keys(holdings).length > 0 ? `
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
                ${holdingsRows}
            </tbody>
        </table>
        ` : '<p style="color: #858585;">No holdings</p>';

        return `
        <div class="account-card ${cssClass}">
            <h3>${name} Account</h3>
            <p style="margin: 10px 0;">
                <strong>Cash:</strong> <span class="number">$${cash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span><br>
                <strong>Total Value:</strong> <span class="number">$${totalValue.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
            </p>
            ${holdingsTable}
        </div>
        `;
    }

    /**
     * 计算每个symbol的加权平均价格
     */
    calculateAvgPrices(orders) {
        const symbolTotals = {};

        orders.forEach(order => {
            const symbol = order.symbol || '';
            const quantity = order.quantity || 0;
            const fillPrice = order.fill_price || 0;

            if (!symbolTotals[symbol]) {
                symbolTotals[symbol] = { total_value: 0, total_qty: 0 };
            }

            symbolTotals[symbol].total_value += quantity * fillPrice;
            symbolTotals[symbol].total_qty += quantity;
        });

        const avgPrices = {};
        Object.entries(symbolTotals).forEach(([symbol, totals]) => {
            if (totals.total_qty > 0) {
                avgPrices[symbol] = totals.total_value / totals.total_qty;
            }
        });

        return avgPrices;
    }

    /**
     * 获取状态名称
     */
    getStatusName(statusCode) {
        return this.statusMap[String(statusCode)] || 'Unknown';
    }

    /**
     * 绑定事件监听器
     */
    attachEventListeners() {
        // 过滤器事件
        const showEntry = document.getElementById('showEntry');
        const showExit = document.getElementById('showExit');
        const showCanceled = document.getElementById('showCanceled');

        if (showEntry) showEntry.addEventListener('change', () => this.applyFilters());
        if (showExit) showExit.addEventListener('change', () => this.applyFilters());
        if (showCanceled) showCanceled.addEventListener('change', () => this.applyFilters());
    }

    /**
     * 应用过滤器
     */
    applyFilters() {
        const showEntry = document.getElementById('showEntry');
        const showExit = document.getElementById('showExit');
        const showCanceled = document.getElementById('showCanceled');

        const cards = document.querySelectorAll('.execution-card');

        cards.forEach(card => {
            const levelType = card.getAttribute('data-level-type');
            const status = card.getAttribute('data-status');

            let visible = true;

            if (levelType === 'ENTRY' && showEntry && !showEntry.checked) {
                visible = false;
            }
            if (levelType === 'EXIT' && showExit && !showExit.checked) {
                visible = false;
            }
            if (status === 'Canceled' && showCanceled && !showCanceled.checked) {
                visible = false;
            }

            card.style.display = visible ? 'block' : 'none';
        });
    }

    /**
     * 切换折叠状态
     */
    toggleCollapse(event) {
        const element = event.target;
        element.classList.toggle('collapsed');
        const content = element.nextElementSibling;
        if (content) {
            content.classList.toggle('hidden');
        }
    }

    /**
     * 默认折叠所有OrderGroup
     */
    collapseAllOrderGroups() {
        const collapsibles = document.querySelectorAll('.collapsible');
        collapsibles.forEach(el => {
            el.classList.add('collapsed');
            const content = el.nextElementSibling;
            if (content) {
                content.classList.add('hidden');
            }
        });
    }
}

// 导出到全局作用域
window.BacktestReportRenderer = BacktestReportRenderer;
