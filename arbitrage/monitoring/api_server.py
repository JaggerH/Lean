"""
FastAPI监控服务器
提供REST API和WebSocket实时推送
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import redis
import json
import asyncio
from typing import List, Optional
from config_utils import get_redis_port_from_compose
from backtest_manager import BacktestManager

app = FastAPI(
    title="Trading Monitor API",
    description="实时交易监控API",
    version="1.0.0"
)

# CORS配置 (允许所有来源)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis客户端 - 自动从docker-compose.yml读取端口
redis_client = redis.Redis(
    host='localhost',
    port=get_redis_port_from_compose(),
    db=0,
    decode_responses=True
)

# WebSocket连接管理
active_connections: List[WebSocket] = []

# BacktestManager - 管理回测历史（使用绝对路径）
import os
from pathlib import Path

# 获取 monitoring 目录的父目录（arbitrage 目录）
ARBITRAGE_DIR = Path(__file__).parent.parent
# backtest_history 在 monitoring 目录下
BACKTEST_HISTORY_DIR = Path(__file__).parent / "backtest_history"

backtest_manager = BacktestManager(history_dir=str(BACKTEST_HISTORY_DIR))


# === REST API端点 ===

@app.get("/")
async def root():
    """根路径 - 返回监控页面"""
    # 使用绝对路径
    static_dir = Path(__file__).parent / "static"
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
async def health_check():
    """健康检查"""
    try:
        redis_client.ping()
        redis_status = "connected"
    except:
        redis_status = "disconnected"

    return {
        "status": "ok",
        "redis": redis_status,
        "active_connections": len(active_connections)
    }


@app.get("/api/snapshot")
async def get_snapshot():
    """获取最新的Portfolio快照"""
    try:
        data = redis_client.get("trading:snapshot")
        return json.loads(data) if data else {}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/spreads")
async def get_spreads():
    """获取所有交易对的价差数据"""
    try:
        raw = redis_client.hgetall("trading:spreads")
        spreads = {k: json.loads(v) for k, v in raw.items()}

        # 调试日志
        import os
        if os.environ.get('MONITOR_LOG_LEVEL') == 'DEBUG':
            print(f"[DEBUG] /api/spreads called: found {len(spreads)} pairs")
            if spreads:
                for pair_key, data in list(spreads.items())[:2]:  # 只显示前2个
                    print(f"  - {pair_key}: spread={data.get('spread_pct', 'N/A'):.4%}")

        return spreads
    except Exception as e:
        print(f"[ERROR] /api/spreads failed: {e}")
        return {"error": str(e)}


@app.get("/api/orders")
async def get_orders(limit: int = 50):
    """
    获取最近的订单列表

    Args:
        limit: 返回订单数量限制(默认50)
    """
    try:
        raw = redis_client.lrange("trading:orders", 0, limit - 1)
        return [json.loads(o) for o in raw]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/stats")
async def get_stats():
    """获取统计信息"""
    try:
        return redis_client.hgetall("trading:stats")
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/round_trips")
async def get_round_trips():
    """获取Round Trip数据"""
    try:
        data = redis_client.get("trading:round_trips")
        return json.loads(data) if data else {"active": [], "completed_count": 0}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/active_targets")
async def get_active_targets():
    """
    获取活跃的 ExecutionTarget 列表

    从 Redis 的 trading:active_targets (Hash) 中读取所有活跃的执行目标
    这些数据由 LEAN 实时写入（通过 OrderTracker.on_execution_target_registered/update）

    Returns:
        字典，key 为 grid_id，value 为 ExecutionTarget 数据
    """
    try:
        raw = redis_client.hgetall("trading:active_targets")
        active_targets = {k: json.loads(v) for k, v in raw.items()}
        return active_targets
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/grid_positions")
async def get_grid_positions():
    """
    获取 GridPosition 快照列表

    从 Redis 的 trading:grid_positions (Hash) 中读取所有网格持仓快照
    这些数据在 ExecutionTarget 终止状态时由 OrderTracker 写入

    Returns:
        字典，key 为 grid_id，value 为 GridPositionSnapshot 数据
    """
    try:
        raw = redis_client.hgetall("trading:grid_positions")
        grid_positions = {k: json.loads(v) for k, v in raw.items()}
        return grid_positions
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/positions")
async def get_positions():
    """
    获取按交易对配对的持仓数据

    使用 trading:pair_mappings 中的配对关系（在 SpreadManager.add_pair() 时写入）
    来正确配对两个账户的持仓数据。

    返回格式:
    [
        {
            "pair": "AAPLUSDx<->AAPL",
            "crypto": {
                "symbol": "AAPLUSDx",
                "market": "kraken",
                "account": "Kraken",
                "quantity": 10.0,
                "average_price": 248.50,
                "market_price": 249.80,
                "unrealized_pnl": 13.00
            },
            "stock": {
                "symbol": "AAPL",
                "market": "usa",
                "account": "IBKR",
                "quantity": -1000.0,
                "average_price": 248.00,
                "market_price": 249.30,
                "unrealized_pnl": -1300.00
            },
            "total_pnl": -1287.00,
            "open_time": "2025-10-13T08:00:00",
            "hold_duration_seconds": 8100
        }
    ]
    """
    try:
        # 1. 获取配对映射（在 LEAN subscribe 时写入）
        pair_mappings_raw = redis_client.hgetall("trading:pair_mappings")
        if not pair_mappings_raw:
            # 如果没有配对映射，返回空列表（说明 LEAN 还未启动或未订阅交易对）
            return []

        pair_mappings = {k: json.loads(v) for k, v in pair_mappings_raw.items()}

        # 2. 获取持仓快照
        snapshot_data = redis_client.get("trading:snapshot")
        if not snapshot_data:
            return []

        snapshot = json.loads(snapshot_data)
        accounts = snapshot.get('accounts', {})

        # 3. 根据配对映射构建持仓数据
        positions = []

        for pair_key, mapping in pair_mappings.items():
            crypto_info = mapping['crypto']
            stock_info = mapping['stock']

            # 根据配对映射中的账户信息查找持仓
            crypto_account_name = crypto_info['account']
            stock_account_name = stock_info['account']

            crypto_account = accounts.get(crypto_account_name, {})
            stock_account = accounts.get(stock_account_name, {})

            crypto_symbol = crypto_info['symbol']
            stock_symbol = stock_info['symbol']

            crypto_holding = crypto_account.get('holdings', {}).get(crypto_symbol)
            stock_holding = stock_account.get('holdings', {}).get(stock_symbol)

            # 如果任一端没有持仓，跳过（可能还未开仓）
            if not crypto_holding or not stock_holding:
                continue

            # 计算持仓时长
            hold_duration_seconds = 0
            open_time = crypto_holding.get('open_time', '')  # 使用 crypto 端的 open_time
            if open_time:
                try:
                    from datetime import datetime
                    open_dt = datetime.fromisoformat(open_time)
                    now = datetime.now()
                    hold_duration_seconds = int((now - open_dt).total_seconds())
                except:
                    pass

            # 构建配对持仓数据
            crypto_pnl = float(crypto_holding.get('unrealized_pnl', 0))
            stock_pnl = float(stock_holding.get('unrealized_pnl', 0))

            position = {
                'pair': pair_key,
                'crypto': {
                    'symbol': crypto_symbol,
                    'market': crypto_info['market'],
                    'account': crypto_account_name,
                    'quantity': float(crypto_holding.get('quantity', 0)),
                    'average_price': float(crypto_holding.get('average_price', 0)),
                    'market_price': float(crypto_holding.get('market_price', 0)),
                    'unrealized_pnl': crypto_pnl,
                },
                'stock': {
                    'symbol': stock_symbol,
                    'market': stock_info['market'],
                    'account': stock_account_name,
                    'quantity': float(stock_holding.get('quantity', 0)),
                    'average_price': float(stock_holding.get('average_price', 0)),
                    'market_price': float(stock_holding.get('market_price', 0)),
                    'unrealized_pnl': stock_pnl,
                },
                'total_pnl': crypto_pnl + stock_pnl,
                'open_time': open_time,
                'hold_duration_seconds': hold_duration_seconds,
            }

            positions.append(position)

        return positions

    except Exception as e:
        print(f"[ERROR] /api/positions failed: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# === Backtest History API ===

@app.get("/api/backtests")
async def list_backtests(limit: Optional[int] = None, sort_by: str = "created_at"):
    """
    获取回测历史列表

    Args:
        limit: 最大返回数量
        sort_by: 排序字段 (created_at, total_pnl, total_round_trips)

    Returns:
        回测列表
    """
    try:
        backtests = backtest_manager.list_backtests(limit=limit, sort_by=sort_by)
        return {
            "backtests": backtests,
            "total": len(backtests)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtests/{backtest_id}")
async def get_backtest(backtest_id: str):
    """
    获取指定回测的元数据

    Args:
        backtest_id: 回测唯一标识符

    Returns:
        回测元数据
    """
    try:
        backtest = backtest_manager.get_backtest(backtest_id)
        if not backtest:
            raise HTTPException(status_code=404, detail="Backtest not found")
        return backtest
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtests/{backtest_id}/data")
async def get_backtest_data(backtest_id: str):
    """
    获取指定回测的完整 JSON 数据

    Args:
        backtest_id: 回测唯一标识符

    Returns:
        GridOrderTracker JSON 数据
    """
    try:
        data = backtest_manager.get_backtest_data(backtest_id)
        if not data:
            raise HTTPException(status_code=404, detail="Backtest data not found")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtests/{backtest_id}/report")
async def get_backtest_report(backtest_id: str):
    """
    获取指定回测的 HTML 报告（动态渲染版本）

    Args:
        backtest_id: 回测唯一标识符

    Returns:
        报告查看器HTML页面（会从JSON动态渲染）
    """
    try:
        # 验证backtest是否存在
        backtest = backtest_manager.get_backtest(backtest_id)
        if not backtest:
            raise HTTPException(status_code=404, detail="Backtest not found")

        # 返回报告查看器页面,它会通过 ?id=backtest_id 加载JSON并渲染
        from fastapi.responses import HTMLResponse
        from pathlib import Path

        # 读取report_viewer.html并注入backtest_id
        report_viewer_path = Path(__file__).parent / "static" / "report_viewer.html"
        with open(report_viewer_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # 返回HTML,浏览器会自动从URL参数获取id
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/backtests/{backtest_id}")
async def delete_backtest(backtest_id: str):
    """
    删除指定回测

    Args:
        backtest_id: 回测唯一标识符

    Returns:
        删除结果
    """
    try:
        success = backtest_manager.delete_backtest(backtest_id)
        if not success:
            raise HTTPException(status_code=404, detail="Backtest not found")
        return {"success": True, "message": f"Backtest {backtest_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtests/stats/summary")
async def get_backtest_stats():
    """
    获取回测历史统计信息

    Returns:
        统计数据
    """
    try:
        stats = backtest_manager.get_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === WebSocket实时推送 ===

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket端点 - 订阅Redis事件并推送到客户端

    客户端将收到以下类型的事件:
    - snapshot_update: Portfolio快照更新
    - spread_update: 价差更新
    - order_update: 订单更新
    - spreads_batch_update: 批量价差更新
    """
    await websocket.accept()
    active_connections.append(websocket)

    # 创建Redis Pub/Sub订阅（在executor中运行）
    pubsub = redis_client.pubsub()
    pubsub.subscribe("trading:events")

    try:
        print(f"[OK] WebSocket客户端已连接 (总连接数: {len(active_connections)})")

        # 使用asyncio在后台监听Redis事件
        loop = asyncio.get_event_loop()

        while True:
            # 使用run_in_executor在后台线程中执行阻塞的get_message()
            message = await loop.run_in_executor(
                None,  # 使用默认线程池
                pubsub.get_message,
                0.1  # 100ms 超时，避免永久阻塞
            )

            if message and message['type'] == 'message':
                # 转发事件到客户端
                try:
                    await websocket.send_text(message['data'])
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    print(f"[WARN] WebSocket发送失败: {e}")
                    break

            # 短暂休眠，避免CPU占用过高
            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        print("[INFO] WebSocket客户端断开连接")
    except Exception as e:
        print(f"[ERROR] WebSocket错误: {e}")
    finally:
        # 清理
        pubsub.unsubscribe()
        pubsub.close()
        if websocket in active_connections:
            active_connections.remove(websocket)

        print(f"  当前连接数: {len(active_connections)}")


# === 静态文件服务 ===

# 使用绝对路径挂载静态文件目录
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# === 启动事件 ===

@app.on_event("startup")
async def startup_event():
    """服务器启动时的初始化"""
    import os

    # 从环境变量获取端口（由uvicorn设置）或使用默认值
    port = os.environ.get('UVICORN_PORT', '8001')
    log_level = os.environ.get('MONITOR_LOG_LEVEL', 'INFO')

    print("\n" + "=" * 60)
    print("  Trading Monitor API Server")
    print("=" * 60)
    print("[OK] FastAPI服务器已启动")
    print(f"  监控页面: http://localhost:{port}")
    print(f"  API文档: http://localhost:{port}/docs")
    print(f"  日志级别: {log_level}")

    # 显示路径信息（调试用）
    if log_level == 'DEBUG':
        print(f"\n[DEBUG] 路径配置:")
        print(f"  - 当前工作目录: {os.getcwd()}")
        print(f"  - api_server.py: {Path(__file__).absolute()}")
        print(f"  - static 目录: {STATIC_DIR.absolute()}")
        print(f"  - backtest_history: {BACKTEST_HISTORY_DIR.absolute()}")

    print("=" * 60 + "\n")

    # 测试Redis连接
    try:
        redis_client.ping()
        redis_port = redis_client.connection_pool.connection_kwargs.get('port', 'unknown')
        print(f"[OK] Redis连接正常 (端口: {redis_port})")

        # 调试模式：检查Redis中的现有数据
        if log_level == 'DEBUG':
            print("\n[DEBUG] Redis数据检查:")
            try:
                # 检查spreads
                spreads_count = redis_client.hlen("trading:spreads")
                print(f"  - trading:spreads: {spreads_count} pairs")

                # 检查orders
                orders_count = redis_client.llen("trading:orders")
                print(f"  - trading:orders: {orders_count} orders")

                # 检查snapshot
                snapshot = redis_client.get("trading:snapshot")
                print(f"  - trading:snapshot: {'存在' if snapshot else '不存在'}")

                print("")
            except Exception as debug_error:
                print(f"  [WARN] 数据检查失败: {debug_error}\n")

    except Exception as e:
        print(f"[WARN] Redis连接失败: {e}")
        print("   请确保Redis已启动")


@app.on_event("shutdown")
async def shutdown_event():
    """服务器关闭时的清理"""
    print("\n[INFO] Trading Monitor API Server已停止\n")


# === 主程序入口 ===

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )
