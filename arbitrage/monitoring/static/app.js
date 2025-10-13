/**
 * LEAN交易监控前端逻辑
 * 处理WebSocket连接、API调用和UI更新
 */

class TradingMonitor {
    constructor() {
        this.ws = null;
        this.reconnectInterval = 3000; // 3秒重连
        this.reconnectTimer = null;
        this.pollingInterval = null; // 轮询定时器
        this.pollingEnabled = false; // 轮询是否启用
        this.wsConnected = false; // WebSocket连接状态

        this.init();
    }

    init() {
        this.connectWebSocket();
        this.initialLoad();
        this.startHeartbeat();

        // 3秒后如果WebSocket还没连接，启动轮询
        setTimeout(() => {
            if (!this.wsConnected) {
                console.log('[INFO] WebSocket连接失败，启用轮询模式');
                this.startPolling();
            }
        }, 3000);
    }

    // === WebSocket连接 ===

    connectWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws`;
        console.log(`🔌 尝试连接 WebSocket: ${wsUrl}`);

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('✓ WebSocket已连接');
                this.wsConnected = true;
                this.updateConnectionStatus(true, 'WebSocket');

                if (this.reconnectTimer) {
                    clearTimeout(this.reconnectTimer);
                    this.reconnectTimer = null;
                }

                // 停止轮询（如果正在运行）
                if (this.pollingEnabled) {
                    this.stopPolling();
                }

                // 立即加载一次数据
                this.initialLoad();
            };

            this.ws.onmessage = (event) => {
                this.handleWebSocketMessage(event.data);
            };

            this.ws.onerror = (error) => {
                console.error('❌ WebSocket错误:', error);
                console.error('   URL:', wsUrl);
                console.error('   ReadyState:', this.ws?.readyState);
                this.wsConnected = false;
                this.updateConnectionStatus(false);
            };

            this.ws.onclose = (event) => {
                console.log('✗ WebSocket连接关闭');
                console.log('   Code:', event.code);
                console.log('   Reason:', event.reason || '(无)');
                console.log('   Clean:', event.wasClean);
                this.wsConnected = false;
                this.updateConnectionStatus(false);
                this.scheduleReconnect();

                // 启动轮询作为备选方案
                if (!this.pollingEnabled) {
                    console.log('[INFO] 启动轮询作为备选方案');
                    this.startPolling();
                }
            };

        } catch (error) {
            console.error('❌ WebSocket连接失败:', error);
            this.updateConnectionStatus(false);
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        if (!this.reconnectTimer) {
            console.log(`⏳ ${this.reconnectInterval / 1000}秒后重连...`);
            this.reconnectTimer = setTimeout(() => {
                this.connectWebSocket();
            }, this.reconnectInterval);
        }
    }

    handleWebSocketMessage(data) {
        try {
            const event = JSON.parse(data);

            console.log('📨 收到事件:', event.type);

            switch (event.type) {
                case 'snapshot_update':
                    this.loadSnapshot();
                    break;
                case 'spread_update':
                case 'spreads_batch_update':
                    this.loadSpreads();
                    break;
                case 'order_update':
                    this.loadOrders();
                    break;
            }

            this.updateLastUpdateTime();

        } catch (error) {
            console.error('❌ 解析WebSocket消息失败:', error);
        }
    }

    // === API调用 ===

    async fetchAPI(endpoint) {
        try {
            const response = await fetch(`/api/${endpoint}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error(`❌ API调用失败 (${endpoint}):`, error);
            return null;
        }
    }

    // === 初始加载 ===

    async initialLoad() {
        console.log('📥 初始加载数据...');
        await Promise.all([
            this.loadSnapshot(),
            this.loadSpreads(),
            this.loadOrders(),
            this.loadStats()
        ]);
    }

    // === 数据加载 ===

    async loadSnapshot() {
        const data = await this.fetchAPI('snapshot');
        if (data && !data.error) {
            this.renderAccounts(data.accounts);
            this.renderPnL(data.pnl);
            this.renderPositions(data);
        }
    }

    async loadSpreads() {
        const data = await this.fetchAPI('spreads');
        if (data && !data.error) {
            this.renderSpreads(data);
        }
    }

    async loadOrders() {
        const data = await this.fetchAPI('orders?limit=10');
        if (data && !data.error) {
            this.renderOrders(data);
        }
    }

    async loadStats() {
        const data = await this.fetchAPI('stats');
        if (data && !data.error) {
            this.renderStats(data);
        }
    }

    // === UI渲染 ===

    renderPnL(pnl) {
        if (!pnl) return;

        const realizedEl = document.getElementById('realized-pnl');
        const unrealizedEl = document.getElementById('unrealized-pnl');
        const totalEl = document.getElementById('total-pnl');

        const realized = parseFloat(pnl.realized || 0);
        const unrealized = parseFloat(pnl.unrealized || 0);
        const total = realized + unrealized;

        realizedEl.textContent = this.formatMoney(realized);
        realizedEl.className = `stat-value ${realized >= 0 ? 'positive' : 'negative'}`;

        unrealizedEl.textContent = this.formatMoney(unrealized);
        unrealizedEl.className = `stat-value ${unrealized >= 0 ? 'positive' : 'negative'}`;

        totalEl.textContent = this.formatMoney(total);
        totalEl.className = `stat-value ${total >= 0 ? 'positive' : 'negative'}`;
    }

    renderAccounts(accounts) {
        const container = document.getElementById('accounts-container');
        if (!accounts || Object.keys(accounts).length === 0) {
            container.innerHTML = '<div class="loader">暂无账户数据</div>';
            return;
        }

        let html = '';
        for (const [name, account] of Object.entries(accounts)) {
            const cash = parseFloat(account.cash || 0);
            const totalValue = parseFloat(account.total_portfolio_value || 0);

            html += `
                <div class="stat-row">
                    <span class="stat-label">${name}</span>
                    <span class="stat-value">${this.formatMoney(totalValue)}</span>
                </div>
                <div class="stat-row" style="font-size: 12px; opacity: 0.8;">
                    <span>现金</span>
                    <span>${this.formatMoney(cash)}</span>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    renderPositions(snapshot) {
        const container = document.getElementById('positions-container');

        if (!snapshot || !snapshot.accounts) {
            container.innerHTML = '<div class="loader">暂无持仓数据</div>';
            return;
        }

        // 提取所有accounts中的holdings
        let allHoldings = {};
        for (const [accountName, account] of Object.entries(snapshot.accounts)) {
            if (account.holdings) {
                allHoldings = { ...allHoldings, ...account.holdings };
            }
        }

        if (Object.keys(allHoldings).length === 0) {
            container.innerHTML = '<div class="loader">暂无持仓</div>';
            return;
        }

        let html = '<table><thead><tr><th>标的</th><th>数量</th><th>市值</th><th>未实现盈亏</th></tr></thead><tbody>';

        for (const [symbol, holding] of Object.entries(allHoldings)) {
            const qty = parseFloat(holding.quantity || 0);
            const value = parseFloat(holding.market_value || 0);
            const unrealizedPnl = parseFloat(holding.unrealized_pnl || 0);

            html += `
                <tr>
                    <td><strong>${symbol}</strong></td>
                    <td>${qty.toFixed(2)}</td>
                    <td>${this.formatMoney(value)}</td>
                    <td class="${unrealizedPnl >= 0 ? 'positive' : 'negative'}">
                        ${this.formatMoney(unrealizedPnl)}
                    </td>
                </tr>
            `;
        }

        html += '</tbody></table>';
        container.innerHTML = html;
    }

    renderSpreads(spreads) {
        const container = document.getElementById('spreads-container');

        if (!spreads || Object.keys(spreads).length === 0) {
            container.innerHTML = '<div class="loader">暂无价差数据</div>';
            return;
        }

        let html = '';
        for (const [pair, spread] of Object.entries(spreads)) {
            const spreadPct = parseFloat(spread.spread_pct || 0) * 100;
            const spreadClass = spreadPct >= 0 ? 'positive' : 'negative';

            html += `
                <div class="spread-item">
                    <div class="spread-header">${pair}</div>
                    <div class="spread-value ${spreadClass}">
                        ${spreadPct >= 0 ? '+' : ''}${spreadPct.toFixed(2)}%
                    </div>
                    <div style="font-size: 12px; margin-top: 5px; color: #888;">
                        Crypto Bid: $${parseFloat(spread.crypto_bid || 0).toFixed(2)} |
                        Ask: $${parseFloat(spread.crypto_ask || 0).toFixed(2)} |
                        Stock: $${parseFloat(spread.stock_price || 0).toFixed(2)}
                    </div>
                    <div class="timestamp">${spread.timestamp || '-'}</div>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    renderOrders(orders) {
        const container = document.getElementById('orders-container');

        if (!orders || orders.length === 0) {
            container.innerHTML = '<div class="loader">暂无订单数据</div>';
            return;
        }

        let html = '';
        for (const order of orders.slice(0, 10)) {
            const direction = order.direction || 'UNKNOWN';
            const orderClass = direction === 'BUY' ? 'order-buy' : 'order-sell';
            const qty = parseFloat(order.quantity || 0);
            const price = parseFloat(order.price || 0);

            html += `
                <div class="order-item ${orderClass}">
                    <div>
                        <strong>${order.symbol || 'N/A'}</strong> |
                        ${direction} ${qty.toFixed(2)} @ $${price.toFixed(2)}
                        ${order.account ? `<span style="color: #888;"> (${order.account})</span>` : ''}
                    </div>
                    <div class="timestamp">${order.time || '-'}</div>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    renderStats(stats) {
        const orderCountEl = document.getElementById('order-count');
        if (stats.order_count) {
            orderCountEl.textContent = stats.order_count;
        }
    }

    // === 辅助方法 ===

    formatMoney(value) {
        const num = parseFloat(value);
        if (isNaN(num)) return '$0.00';
        return `$${num.toFixed(2)}`;
    }

    updateConnectionStatus(connected, mode = '') {
        const statusEl = document.getElementById('connection-status');
        if (connected) {
            statusEl.textContent = mode ? `已连接 (${mode})` : '已连接';
            statusEl.style.color = '#4ade80';
        } else {
            statusEl.textContent = '未连接';
            statusEl.style.color = '#f87171';
        }
    }

    // === 轮询模式 ===

    startPolling() {
        if (this.pollingEnabled) return;

        console.log('[INFO] 轮询模式已启动 (每3秒)');
        this.pollingEnabled = true;
        this.updateConnectionStatus(true, '轮询');

        // 立即加载一次
        this.pollData();

        // 每3秒轮询一次
        this.pollingInterval = setInterval(() => {
            this.pollData();
        }, 3000);
    }

    stopPolling() {
        if (!this.pollingEnabled) return;

        console.log('[INFO] 轮询模式已停止');
        this.pollingEnabled = false;

        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }

    async pollData() {
        // 轮询所有数据
        await Promise.all([
            this.loadSpreads(),
            this.loadSnapshot(),
            this.loadOrders()
        ]);
        this.updateLastUpdateTime();
    }

    updateLastUpdateTime() {
        const timeEl = document.getElementById('last-update');
        const now = new Date();
        timeEl.textContent = now.toLocaleTimeString('zh-CN');
    }

    // === 心跳检测 ===

    startHeartbeat() {
        setInterval(async () => {
            const health = await this.fetchAPI('health');
            if (health && health.status === 'ok') {
                // 连接正常
            } else {
                console.warn('⚠️ 心跳检测失败');
            }
        }, 30000); // 每30秒检测一次
    }

    // === 清理资源 ===

    cleanup() {
        console.log('[INFO] 清理资源...');

        // 关闭 WebSocket
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[INFO] 关闭 WebSocket 连接');
            this.ws.close(1000, 'Page unload'); // 正常关闭
        }

        // 停止轮询
        if (this.pollingEnabled) {
            this.stopPolling();
        }

        // 清除定时器
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }
}

// 启动监控
let monitorInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Trading Monitor 启动');
    monitorInstance = new TradingMonitor();
});

// 页面卸载时清理资源
window.addEventListener('beforeunload', () => {
    if (monitorInstance) {
        monitorInstance.cleanup();
    }
});

// 页面隐藏时也清理（处理移动端和标签切换）
document.addEventListener('visibilitychange', () => {
    if (document.hidden && monitorInstance) {
        console.log('[INFO] 页面隐藏，暂停连接');
        if (monitorInstance.ws && monitorInstance.ws.readyState === WebSocket.OPEN) {
            monitorInstance.ws.close(1000, 'Page hidden');
        }
        if (monitorInstance.pollingEnabled) {
            monitorInstance.stopPolling();
        }
    } else if (!document.hidden && monitorInstance) {
        console.log('[INFO] 页面可见，恢复连接');
        // 恢复连接
        if (!monitorInstance.wsConnected) {
            monitorInstance.connectWebSocket();
        }
        // 立即加载一次数据
        monitorInstance.initialLoad();
    }
});
