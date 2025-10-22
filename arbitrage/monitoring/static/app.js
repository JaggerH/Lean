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

        // Broadcast Channel 用于跨标签页通信
        this.bc = null;
        this.setupBroadcastChannel();

        // 缓存价差数据，用于在持仓中显示
        this.spreadsCache = {};

        // 当前模式: 'live' 或 'backtest'
        this.currentMode = 'live';

        // 当前选中的回测ID
        this.selectedBacktestId = null;

        this.init();
    }

    setupBroadcastChannel() {
        // 检查是否支持 Broadcast Channel API
        if ('BroadcastChannel' in window) {
            try {
                this.bc = new BroadcastChannel('trading_monitor_channel');

                // 监听来自其他标签页的消息
                this.bc.onmessage = (event) => {
                    if (event.data.type === 'new_tab_opened') {
                        console.log('[INFO] 检测到新标签页打开，刷新当前页面');
                        // 延迟100ms刷新，让新标签页有时间加载
                        setTimeout(() => {
                            window.location.reload();
                        }, 100);
                    }
                };

                // 通知其他标签页：新标签页已打开
                this.bc.postMessage({ type: 'new_tab_opened', timestamp: Date.now() });

                console.log('[INFO] Broadcast Channel 已启用（支持多标签页刷新）');
            } catch (e) {
                console.warn('[WARN] Broadcast Channel 初始化失败:', e);
            }
        } else {
            console.log('[INFO] 浏览器不支持 Broadcast Channel（多标签页刷新功能不可用）');
        }
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
                    this.loadPositions();  // 快照更新时也更新持仓
                    break;
                case 'spread_update':
                case 'spreads_batch_update':
                    this.loadSpreads();
                    break;
                case 'order_update':
                    this.loadOrders();
                    break;
                case 'execution_target_registered':
                case 'execution_target_update':
                    this.loadActiveTargets();
                    break;
                case 'grid_position_update':
                    this.loadGridPositions();
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
            this.loadPositions(),
            this.loadSpreads(),
            this.loadOrders(),
            this.loadStats(),
            this.loadActiveTargets(),
            this.loadGridPositions()
        ]);
    }

    // === 数据加载 ===

    async loadSnapshot() {
        const data = await this.fetchAPI('snapshot');
        if (data && !data.error) {
            this.renderAccounts(data.accounts);
            this.renderPnL(data.pnl);
        }
    }

    async loadPositions() {
        const data = await this.fetchAPI('positions');
        if (data && !data.error) {
            this.renderPositions(data);
        }
    }

    async loadSpreads() {
        const data = await this.fetchAPI('spreads');
        if (data && !data.error) {
            this.spreadsCache = data; // 缓存价差数据
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

    async loadActiveTargets() {
        const data = await this.fetchAPI('active_targets');
        if (data && !data.error) {
            this.renderActiveTargets(data);
        }
    }

    async loadGridPositions() {
        const data = await this.fetchAPI('grid_positions');
        if (data && !data.error) {
            this.renderGridPositions(data);
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

    renderPositions(positions) {
        const container = document.getElementById('positions-container');

        if (!positions || positions.length === 0) {
            container.innerHTML = '<div class="loader">暂无持仓</div>';
            return;
        }

        let html = '<table class="positions-table"><thead><tr><th>交易对</th><th>Crypto</th><th>Stock</th><th>配对盈亏</th><th>持仓时长</th></tr></thead><tbody>';

        for (const pos of positions) {
            const totalPnlClass = pos.total_pnl >= 0 ? 'positive' : 'negative';

            // 计算持仓时长显示
            const duration = this.formatDuration(pos.hold_duration_seconds);

            // Crypto 持仓信息
            const cryptoQty = pos.crypto.quantity.toFixed(2);
            const cryptoAvgPrice = pos.crypto.average_price.toFixed(2);
            const cryptoMktPrice = pos.crypto.market_price.toFixed(2);
            const cryptoPnl = pos.crypto.unrealized_pnl;
            const cryptoPnlClass = cryptoPnl >= 0 ? 'positive' : 'negative';
            const cryptoOpenValue = (pos.crypto.quantity * pos.crypto.average_price).toFixed(2);
            const cryptoMktValue = (pos.crypto.quantity * pos.crypto.market_price).toFixed(2);

            // Stock 持仓信息
            const stockQty = pos.stock.quantity.toFixed(2);
            const stockAvgPrice = pos.stock.average_price.toFixed(2);
            const stockMktPrice = pos.stock.market_price.toFixed(2);
            const stockPnl = pos.stock.unrealized_pnl;
            const stockPnlClass = stockPnl >= 0 ? 'positive' : 'negative';
            const stockOpenValue = (pos.stock.quantity * pos.stock.average_price).toFixed(2);
            const stockMktValue = (pos.stock.quantity * pos.stock.market_price).toFixed(2);

            // 查找对应的价差数据
            const spread = this.spreadsCache[pos.pair];
            let spreadInfo = '';
            let priceInfo = '';
            if (spread) {
                const spreadPct = parseFloat(spread.spread_pct || 0) * 100;
                const spreadClass = spreadPct >= 0 ? 'positive' : 'negative';
                spreadInfo = `<div style="margin-top: 4px;">
                    <span class="${spreadClass}" style="font-weight: 600; font-size: 13px;">
                        ${spreadPct >= 0 ? '+' : ''}${spreadPct.toFixed(2)}%
                    </span>
                </div>`;

                // 添加最新价格显示 (Crypto / Stock)
                const cryptoLast = parseFloat(spread.crypto_last || pos.crypto.market_price).toFixed(2);
                const stockLast = parseFloat(spread.stock_last || pos.stock.market_price).toFixed(2);
                priceInfo = `<div style="margin-top: 4px; font-size: 12px; color: #b0b0b0;">
                    $${cryptoLast} / $${stockLast}
                </div>`;
            }

            html += `
                <tr>
                    <td style="text-align: left; vertical-align: middle;">
                        <div>
                            <strong style="font-size: 14px;">${pos.pair}</strong>
                            ${spreadInfo}
                            ${priceInfo}
                        </div>
                    </td>
                    <td style="padding: 12px 16px;">
                        <div style="margin-bottom: 8px;">
                            <strong style="font-size: 13px; color: #a0a0ff;">${pos.crypto.symbol}</strong>
                            <span style="color: #e0e0e0; font-size: 13px; font-weight: 500; margin: 0 6px;">
                                ${cryptoQty}
                            </span>
                            <span style="color: #888; font-size: 12px;">@</span>
                            <span style="color: #e0e0e0; font-size: 13px; font-weight: 500; margin-left: 6px;">
                                $${cryptoAvgPrice}
                            </span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 12px;">
                            <span style="color: #888;">开仓市值:</span>
                            <span style="color: #e0e0e0; font-size: 14px; font-weight: 500;">$${cryptoOpenValue}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 12px;">
                            <span style="color: #888;">持仓市值:</span>
                            <span style="color: #e0e0e0; font-size: 14px; font-weight: 500;">$${cryptoMktValue}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 12px;">
                            <span style="color: #888;">盈亏:</span>
                            <span class="${cryptoPnlClass}" style="font-size: 14px; font-weight: 600;">${this.formatMoney(cryptoPnl)}</span>
                        </div>
                    </td>
                    <td style="padding: 12px 16px;">
                        <div style="margin-bottom: 8px;">
                            <strong style="font-size: 13px; color: #a0a0ff;">${pos.stock.symbol}</strong>
                            <span style="color: #e0e0e0; font-size: 13px; font-weight: 500; margin: 0 6px;">
                                ${stockQty}
                            </span>
                            <span style="color: #888; font-size: 12px;">@</span>
                            <span style="color: #e0e0e0; font-size: 13px; font-weight: 500; margin-left: 6px;">
                                $${stockAvgPrice}
                            </span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 12px;">
                            <span style="color: #888;">开仓市值:</span>
                            <span style="color: #e0e0e0; font-size: 14px; font-weight: 500;">$${stockOpenValue}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 12px;">
                            <span style="color: #888;">持仓市值:</span>
                            <span style="color: #e0e0e0; font-size: 14px; font-weight: 500;">$${stockMktValue}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 12px;">
                            <span style="color: #888;">盈亏:</span>
                            <span class="${stockPnlClass}" style="font-size: 14px; font-weight: 600;">${this.formatMoney(stockPnl)}</span>
                        </div>
                    </td>
                    <td class="${totalPnlClass}" style="font-weight: bold; font-size: 16px; text-align: center; vertical-align: middle;">
                        ${this.formatMoney(pos.total_pnl)}
                    </td>
                    <td style="color: #b0b0b0; font-size: 13px; text-align: center; vertical-align: middle;">
                        ${duration}
                    </td>
                </tr>
            `;
        }

        html += '</tbody></table>';
        container.innerHTML = html;
    }

    formatDuration(seconds) {
        if (!seconds || seconds < 0) return '-';

        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);

        if (hours > 0) {
            return `${hours}小时${minutes}分钟`;
        } else if (minutes > 0) {
            return `${minutes}分钟`;
        } else {
            return `${seconds}秒`;
        }
    }

    renderSpreads(spreads) {
        const container = document.getElementById('spreads-container');

        if (!spreads || Object.keys(spreads).length === 0) {
            container.innerHTML = '<div class="loader">暂无价差数据</div>';
            return;
        }

        // 使用网格布局包裹所有交易对
        let html = '<div class="spreads-grid">';

        for (const [pair, spread] of Object.entries(spreads)) {
            const spreadPct = parseFloat(spread.spread_pct || 0) * 100;
            const spreadClass = spreadPct >= 0 ? 'positive' : 'negative';

            const cryptoBid = parseFloat(spread.crypto_bid || 0);
            const cryptoAsk = parseFloat(spread.crypto_ask || 0);
            const stockBid = parseFloat(spread.stock_bid || 0);
            const stockAsk = parseFloat(spread.stock_ask || 0);

            // 格式化时间戳
            const timestamp = spread.timestamp ? new Date(spread.timestamp).toLocaleTimeString('zh-CN') : '-';

            html += `
                <div class="spread-item">
                    <!-- 左侧：交易对信息 -->
                    <div class="spread-left">
                        <div class="spread-pair-name">${pair}</div>
                        <div class="spread-quotes">
                            <div class="quote-item">
                                <span class="quote-label">Crypto</span>
                                <span class="quote-value">$${cryptoBid.toFixed(2)} / $${cryptoAsk.toFixed(2)}</span>
                            </div>
                            <div class="quote-item">
                                <span class="quote-label">Stock</span>
                                <span class="quote-value">$${stockBid.toFixed(2)} / $${stockAsk.toFixed(2)}</span>
                            </div>
                        </div>
                    </div>

                    <!-- 右侧：价差百分比 -->
                    <div class="spread-right">
                        <div class="spread-value ${spreadClass}">
                            ${spreadPct >= 0 ? '+' : ''}${spreadPct.toFixed(2)}%
                        </div>
                        <div class="spread-timestamp">${timestamp}</div>
                    </div>
                </div>
            `;
        }

        html += '</div>';
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

    renderActiveTargets(targets) {
        const container = document.getElementById('active-targets-container');

        if (!targets || Object.keys(targets).length === 0) {
            container.innerHTML = '<div class="loader">暂无活跃订单</div>';
            return;
        }

        let html = '';
        // 使用 hash 作为 key 遍历，从数据中获取 grid_id 用于显示
        for (const [hashKey, target] of Object.entries(targets)) {
            const gridId = target.grid_id;  // 人类可读的 grid_id（用于 UI 显示）

            // 安全获取数量，避免 undefined
            const cryptoFilled = target.filled_qty_crypto || 0;
            const stockFilled = target.filled_qty_stock || 0;
            const cryptoTarget = target.target_qty_crypto || 0;
            const stockTarget = target.target_qty_stock || 0;

            html += `
                <div class="active-target-item" data-hash="${hashKey}" style="
                    padding: 15px;
                    background: #1e1e1e;
                    border-radius: 4px;
                    margin-bottom: 10px;
                    border-left: 3px solid #4ec9b0;
                ">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <strong style="color: #4ec9b0; font-size: 14px;">${gridId}</strong>
                        <span style="
                            padding: 2px 8px;
                            border-radius: 3px;
                            background: #569cd633;
                            color: #569cd6;
                            font-weight: 600;
                            font-size: 12px;
                        ">${target.status}</span>
                    </div>
                    <div style="font-size: 12px; color: #888; margin-bottom: 6px;">
                        ${target.pair_symbol} | ${target.level_type}
                    </div>
                    <div style="font-size: 12px; color: #b0b0b0; margin-bottom: 4px;">
                        Crypto: ${cryptoFilled.toFixed(2)} / ${cryptoTarget.toFixed(2)}
                    </div>
                    <div style="font-size: 12px; color: #b0b0b0; margin-bottom: 6px;">
                        Stock: ${stockFilled.toFixed(2)} / ${stockTarget.toFixed(2)}
                    </div>
                    <div style="font-size: 11px; color: #666;">
                        ${target.timestamp}
                    </div>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    renderGridPositions(positions) {
        const container = document.getElementById('grid-positions-container');

        if (!positions || Object.keys(positions).length === 0) {
            container.innerHTML = '<div class="loader">暂无网格持仓</div>';
            return;
        }

        let html = '<table><thead><tr><th>Grid ID</th><th>Pair</th><th>Type</th><th>Spread</th><th>Leg1 Qty</th><th>Leg2 Qty</th><th>Time</th></tr></thead><tbody>';

        // 使用 hash 作为 key 遍历，从数据中获取 grid_id 用于显示
        for (const [hashKey, pos] of Object.entries(positions)) {
            const gridId = pos.grid_id;  // 人类可读的 grid_id（用于 UI 显示）
            const spreadClass = pos.spread_pct >= 0 ? 'positive' : 'negative';
            html += `
                <tr data-hash="${hashKey}">
                    <td style="color: #4ec9b0; font-weight: 600;">${gridId}</td>
                    <td>${pos.pair_symbol[0]} <-> ${pos.pair_symbol[1]}</td>
                    <td><span style="
                        padding: 2px 6px;
                        border-radius: 3px;
                        font-size: 11px;
                        background: ${pos.level_type === 'ENTRY' ? '#4ec9b033' : '#ce917833'};
                        color: ${pos.level_type === 'ENTRY' ? '#4ec9b0' : '#ce9178'};
                    ">${pos.level_type}</span></td>
                    <td class="${spreadClass}">${(pos.spread_pct * 100).toFixed(2)}%</td>
                    <td>${pos.leg1_qty.toFixed(2)}</td>
                    <td>${pos.leg2_qty.toFixed(2)}</td>
                    <td style="color: #888; font-size: 11px;">${pos.timestamp}</td>
                </tr>
            `;
        }

        html += '</tbody></table>';
        container.innerHTML = html;
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
            this.loadPositions(),
            this.loadOrders(),
            this.loadActiveTargets(),
            this.loadGridPositions()
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

        // 关闭 Broadcast Channel
        if (this.bc) {
            this.bc.close();
            console.log('[INFO] 关闭 Broadcast Channel');
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

    // === 模式切换 ===

    switchMode(mode) {
        if (this.currentMode === mode) return;

        console.log(`[INFO] 切换模式: ${this.currentMode} -> ${mode}`);
        this.currentMode = mode;

        // 更新按钮状态
        document.getElementById('mode-live').classList.toggle('active', mode === 'live');
        document.getElementById('mode-backtest').classList.toggle('active', mode === 'backtest');

        // 更新徽章
        const badge = document.getElementById('mode-badge');
        badge.textContent = mode === 'live' ? 'Live' : 'Backtest';
        badge.className = `mode-badge ${mode}`;

        if (mode === 'live') {
            // 显示 Live 内容，隐藏 Backtest 内容
            document.getElementById('live-content').style.display = 'block';
            document.getElementById('backtest-content').style.display = 'none';

            // 重新连接 WebSocket 和加载实时数据
            if (!this.wsConnected) {
                this.connectWebSocket();
            }
            this.initialLoad();
        } else {
            // 显示 Backtest 内容，隐藏 Live 内容
            document.getElementById('live-content').style.display = 'none';
            document.getElementById('backtest-content').style.display = 'block';

            // 加载回测历史并自动选择第一个
            this.loadBacktestHistory();
        }
    }

    // === 回测历史管理 ===

    async loadBacktestHistory() {
        console.log('[INFO] 加载回测历史...');
        const data = await this.fetchAPI('backtests?sort_by=created_at&limit=20');
        console.log('[DEBUG] 回测数据:', data);
        if (data && !data.error) {
            console.log(`[INFO] 找到 ${data.backtests.length} 个回测`);
            this.renderBacktestList(data.backtests);

            // 自动选择第一个回测
            if (data.backtests && data.backtests.length > 0) {
                console.log('[INFO] 自动选择第一个回测');
                this.viewBacktestDetail(data.backtests[0].backtest_id);
            }
        } else {
            console.error('[ERROR] 加载回测历史失败:', data);
        }
    }

    renderBacktestList(backtests) {
        console.log('[INFO] 渲染回测列表, 数量:', backtests ? backtests.length : 0);
        const container = document.getElementById('backtest-list-container');

        if (!container) {
            console.error('[ERROR] 找不到 backtest-list-container 元素');
            return;
        }

        if (!backtests || backtests.length === 0) {
            console.log('[INFO] 没有回测数据，显示空状态');
            container.innerHTML = '<div class="loader">暂无回测历史</div>';
            return;
        }

        let html = '';
        for (const bt of backtests) {
            const createdTime = new Date(bt.created_at).toLocaleString('zh-CN');
            const startDate = bt.start_date !== 'N/A' ? new Date(bt.start_date).toLocaleDateString('zh-CN') : 'N/A';
            const endDate = bt.end_date !== 'N/A' ? new Date(bt.end_date).toLocaleDateString('zh-CN') : 'N/A';
            const pnlClass = bt.total_pnl >= 0 ? 'positive' : 'negative';
            const hasReport = bt.has_html_report ? '📊' : '📄';

            html += `
                <div class="backtest-item" data-backtest-id="${bt.backtest_id}" onclick="monitorInstance.viewBacktestDetail('${bt.backtest_id}')">
                    <div class="backtest-header">
                        <div class="backtest-name">${hasReport} ${bt.name || 'Unnamed Backtest'}</div>
                        <div class="backtest-time">${createdTime}</div>
                    </div>
                    ${bt.description ? `<div class="backtest-desc">${bt.description}</div>` : ''}
                    <div class="backtest-meta">
                        <span>🤖 ${bt.algorithm || 'N/A'}</span>
                        <span>📅 ${startDate} ~ ${endDate}</span>
                        <span>🎯 RT: ${bt.total_round_trips}</span>
                        <span>📈 ET: ${bt.total_execution_targets}</span>
                        <span class="${pnlClass}">💰 $${bt.total_pnl.toFixed(2)}</span>
                    </div>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    async viewBacktestDetail(backtestId) {
        console.log(`[INFO] 查看回测详情: ${backtestId}`);
        this.selectedBacktestId = backtestId;

        // 更新列表选中状态
        document.querySelectorAll('.backtest-item').forEach(item => {
            if (item.dataset.backtestId === backtestId) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });

        // 加载回测元数据
        const metadata = await this.fetchAPI(`backtests/${backtestId}`);
        if (metadata && !metadata.error) {
            // 更新标题
            document.getElementById('backtest-detail-title').textContent =
                `📊 ${metadata.name || 'Backtest'}`;
        }

        // 加载回测JSON数据并直接渲染（无需iframe）
        const container = document.getElementById('backtest-detail-container');
        container.innerHTML = '<div class="loader">Loading report...</div>';

        try {
            const jsonData = await this.fetchAPI(`backtests/${backtestId}/data`);
            if (jsonData && !jsonData.error) {
                // 确保backtest_report.js已加载
                if (!window.BacktestReportRenderer) {
                    // 动态加载backtest_report.js (添加时间戳防止缓存)
                    await this.loadScript(`/static/backtest_report.js?v=${Date.now()}`);
                }

                // 直接在容器中渲染报告
                const renderer = new BacktestReportRenderer(jsonData, 'backtest-detail-container');
                renderer.render();
            } else {
                container.innerHTML = '<div class="error">Failed to load backtest data</div>';
            }
        } catch (error) {
            console.error('[ERROR] Failed to render backtest report:', error);
            container.innerHTML = `<div class="error">Error: ${error.message}</div>`;
        }
    }

    /**
     * 动态加载JavaScript脚本
     */
    loadScript(src) {
        return new Promise((resolve, reject) => {
            // 检查是否已加载
            const existingScript = document.querySelector(`script[src="${src}"]`);
            if (existingScript) {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.src = src;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

}

// 启动监控
let monitorInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Trading Monitor 启动');
    monitorInstance = new TradingMonitor();

    // 添加刷新按钮事件监听
    const refreshBtn = document.getElementById('refresh-backtest-list-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            console.log('[INFO] 用户点击刷新回测列表按钮');

            // 添加旋转动画
            refreshBtn.classList.add('spinning');
            refreshBtn.disabled = true;

            try {
                // 重新加载回测历史（但不自动选择第一个）
                const data = await monitorInstance.fetchAPI('backtests?sort_by=created_at&limit=20');
                if (data && !data.error) {
                    console.log(`[INFO] 刷新成功，找到 ${data.backtests.length} 个回测`);
                    monitorInstance.renderBacktestList(data.backtests);

                    // 如果之前有选中的回测，保持选中状态
                    if (monitorInstance.selectedBacktestId) {
                        const selectedExists = data.backtests.some(
                            bt => bt.backtest_id === monitorInstance.selectedBacktestId
                        );
                        if (selectedExists) {
                            monitorInstance.viewBacktestDetail(monitorInstance.selectedBacktestId);
                        } else {
                            // 如果之前选中的回测不存在了，选择第一个
                            if (data.backtests.length > 0) {
                                monitorInstance.viewBacktestDetail(data.backtests[0].backtest_id);
                            }
                        }
                    } else if (data.backtests.length > 0) {
                        // 如果之前没有选中，选择第一个
                        monitorInstance.viewBacktestDetail(data.backtests[0].backtest_id);
                    }
                } else {
                    console.error('[ERROR] 刷新回测历史失败:', data);
                }
            } catch (error) {
                console.error('[ERROR] 刷新过程中出错:', error);
            } finally {
                // 移除旋转动画
                setTimeout(() => {
                    refreshBtn.classList.remove('spinning');
                    refreshBtn.disabled = false;
                }, 500); // 延迟500ms，让用户看到动画完成
            }
        });
    }
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
