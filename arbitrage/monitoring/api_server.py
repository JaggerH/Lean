"""
FastAPI监控服务器
提供REST API和WebSocket实时推送
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import redis
import json
import asyncio
from typing import List
from config_utils import get_redis_port_from_compose

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


# === REST API端点 ===

@app.get("/")
async def root():
    """根路径 - 返回监控页面"""
    return FileResponse("static/index.html")


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

app.mount("/static", StaticFiles(directory="static"), name="static")


# === 启动事件 ===

@app.on_event("startup")
async def startup_event():
    """服务器启动时的初始化"""
    import os

    # 从环境变量获取端口（由uvicorn设置）或使用默认值
    port = os.environ.get('UVICORN_PORT', '8000')
    log_level = os.environ.get('MONITOR_LOG_LEVEL', 'INFO')

    print("\n" + "=" * 60)
    print("  Trading Monitor API Server")
    print("=" * 60)
    print("[OK] FastAPI服务器已启动")
    print(f"  监控页面: http://localhost:{port}")
    print(f"  API文档: http://localhost:{port}/docs")
    print(f"  日志级别: {log_level}")
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
        port=8000,
        reload=False,
        log_level="info"
    )
