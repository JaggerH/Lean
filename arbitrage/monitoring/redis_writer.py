"""
Redis写入工具 - 简洁版
用于将交易数据实时写入Redis
"""
import redis
import json
import time
from typing import Dict, Any, Optional
from .config_utils import get_redis_port_from_compose


class TradingRedis:
    """
    交易数据的Redis写入器

    提供简单的接口将交易数据写入Redis,并通过Pub/Sub通知订阅者
    """

    @staticmethod
    def verify_connection(host='localhost', port=None, db=0, raise_on_failure=True):
        """
        验证Redis连接可用性 (静态方法，可在初始化前调用)

        Args:
            host: Redis主机地址
            port: Redis端口 (None=自动从docker-compose.yml读取)
            db: Redis数据库编号
            raise_on_failure: 连接失败时是否抛出异常

        Returns:
            (bool, str): (是否连接成功, 详细信息/错误信息)

        Raises:
            RuntimeError: 当 raise_on_failure=True 且连接失败时
        """
        from .config_utils import get_redis_port_from_compose

        # 如果未指定端口，从docker-compose.yml读取
        if port is None:
            port = get_redis_port_from_compose()

        try:
            # 尝试连接
            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=2
            )

            # PING测试
            response = client.ping()
            if not response:
                raise ConnectionError("Redis PING失败")

            # 写入测试
            test_key = "health_check:test"
            test_value = "ok"
            client.set(test_key, test_value, ex=10)  # 10秒过期

            # 读取测试
            read_value = client.get(test_key)
            if read_value != test_value:
                raise ConnectionError("Redis读写测试失败")

            # 清理测试数据
            client.delete(test_key)

            # 检查Pub/Sub (可选)
            pubsub = client.pubsub()
            pubsub.subscribe("health_check:test")
            pubsub.unsubscribe()
            pubsub.close()

            success_msg = f"[OK] Redis连接成功 (端口: {port})"
            return (True, success_msg)

        except redis.exceptions.ConnectionError as e:
            error_msg = (
                f"[ERROR] Redis连接失败 (端口: {port})\n"
                f"   错误: {e}\n"
                f"   请检查:\n"
                f"   1. Redis服务是否启动: docker compose up -d redis\n"
                f"   2. 端口配置是否正确: arbitrage/docker-compose.yml\n"
                f"   3. 防火墙/网络是否正常"
            )
            if raise_on_failure:
                raise RuntimeError(error_msg)
            return (False, error_msg)

        except redis.exceptions.TimeoutError as e:
            error_msg = (
                f"[ERROR] Redis连接超时 (端口: {port})\n"
                f"   错误: {e}\n"
                f"   Redis服务可能未响应"
            )
            if raise_on_failure:
                raise RuntimeError(error_msg)
            return (False, error_msg)

        except Exception as e:
            error_msg = (
                f"[ERROR] Redis初始化失败\n"
                f"   错误类型: {type(e).__name__}\n"
                f"   错误信息: {e}"
            )
            if raise_on_failure:
                raise RuntimeError(error_msg)
            return (False, error_msg)

    def __init__(self, host='localhost', port=None, db=0):
        """
        初始化Redis客户端

        Args:
            host: Redis主机地址
            port: Redis端口 (None=自动从docker-compose.yml读取)
            db: Redis数据库编号
        """
        # 保存连接参数用于重连
        self.host = host
        self.port = port if port else get_redis_port_from_compose()
        self.db = db

        # 重连状态管理
        self._last_reconnect_attempt = 0  # 上次重连尝试时间戳
        self._reconnect_interval = 10  # 当前重连间隔(秒)
        self._max_reconnect_interval = 300  # 最大重连间隔(5分钟)
        self._reconnect_backoff_multiplier = 2  # 退避倍数

        # 初始化连接
        self.connected = False
        self.client = None
        self._connect()

    def _connect(self) -> bool:
        """
        建立Redis连接 (可复用于初始连接和重连)

        Returns:
            bool: 是否连接成功
        """
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2  # 添加操作超时
            )

            # 测试连接
            self.client.ping()
            self.connected = True

            # 重置重连间隔
            self._reconnect_interval = 10

            print(f"[OK] Redis连接成功 (端口: {self.port})")
            return True

        except Exception as e:
            self.connected = False
            self.client = None
            print(f"[WARN] Redis连接失败: {e}")
            print("   监控功能将不可用,但不影响交易")
            return False

    def _try_reconnect(self) -> bool:
        """
        尝试重连Redis (带指数退避和限流)

        Returns:
            bool: 是否重连成功
        """
        current_time = time.time()

        # 限流检查: 距离上次尝试需要超过重连间隔
        if current_time - self._last_reconnect_attempt < self._reconnect_interval:
            return False  # 未到重连时间，跳过

        # 更新重连尝试时间
        self._last_reconnect_attempt = current_time

        print(f"[INFO] 尝试重连Redis... (间隔: {self._reconnect_interval}秒)")

        # 尝试重连
        if self._connect():
            print("[OK] Redis重连成功!")
            return True

        # 重连失败，增加重连间隔 (指数退避)
        self._reconnect_interval = min(
            self._reconnect_interval * self._reconnect_backoff_multiplier,
            self._max_reconnect_interval
        )

        print(f"[WARN] Redis重连失败，下次尝试间隔: {self._reconnect_interval}秒")
        return False

    def _safe_execute(self, func, *args, **kwargs):
        """
        安全执行Redis操作，失败时尝试重连

        Args:
            func: Redis操作函数
            *args, **kwargs: 函数参数

        Returns:
            操作结果或None
        """
        # 如果未连接且无法重连，直接返回
        if not self.is_connected():
            return None

        try:
            return func(*args, **kwargs)

        except redis.exceptions.ConnectionError as e:
            # 连接错误：标记断开并尝试重连
            print(f"[WARN] Redis连接错误: {e}")
            self.connected = False

            # 尝试重连并重试操作
            if self._try_reconnect():
                try:
                    return func(*args, **kwargs)
                except Exception as retry_error:
                    print(f"[WARN] 重连后操作仍失败: {retry_error}")
                    return None
            return None

        except redis.exceptions.TimeoutError as e:
            # 超时错误：可能是临时负载问题，不立即断开
            print(f"[WARN] Redis操作超时: {e}")
            return None

        except Exception as e:
            # 其他错误：记录但不触发重连
            print(f"[WARN] Redis操作失败: {e}")
            return None

    # === 快照数据 ===

    def set_snapshot(self, data: Dict):
        """
        更新Portfolio快照

        Args:
            data: 快照数据字典,包含timestamp、accounts、pnl等
        """
        self._safe_execute(
            lambda: self.client.set("trading:snapshot", json.dumps(data))
        )
        self._notify("snapshot_update")

    # === 价差数据 ===

    def set_spread(self, pair: str, data: Dict):
        """
        更新单个交易对的价差数据

        Args:
            pair: 交易对标识 (如 "BTCUSD<->BTC")
            data: 价差数据字典,包含spread_pct、crypto_bid等
        """
        # 首次写入日志标记
        if not hasattr(self, '_spread_write_logged'):
            self._spread_write_logged = set()

        result = self._safe_execute(
            lambda: self.client.hset("trading:spreads", pair, json.dumps(data))
        )

        # 调试日志：每个交易对只记录首次成功写入
        if result is not None and pair not in self._spread_write_logged:
            self._spread_write_logged.add(pair)
            print(f"[OK] Redis: 首次写入价差数据 [{pair}] | spread={data.get('spread_pct', 0):.4%}")

        self._notify("spread_update", pair)

    def set_all_spreads(self, spreads: Dict[str, Dict]):
        """
        批量更新所有交易对的价差数据

        Args:
            spreads: {pair: spread_data, ...}
        """
        if not spreads:
            return

        # 转换为JSON字符串
        spreads_json = {k: json.dumps(v) for k, v in spreads.items()}

        self._safe_execute(
            lambda: self.client.hset("trading:spreads", mapping=spreads_json)
        )
        self._notify("spreads_batch_update")

    # === 订单数据 ===

    def add_order(self, order: Dict):
        """
        添加订单到订单列表 (保留最近100个)

        Args:
            order: 订单数据字典
        """
        def _add():
            self.client.lpush("trading:orders", json.dumps(order))
            self.client.ltrim("trading:orders", 0, 99)  # 只保留最近100个

        self._safe_execute(_add)
        self._notify("order_update")

    # === 统计数据 ===

    def set_stat(self, key: str, value: Any):
        """
        更新单个统计指标

        Args:
            key: 统计指标名称
            value: 统计值
        """
        self._safe_execute(
            lambda: self.client.hset("trading:stats", key, str(value))
        )

    def set_stats(self, **kwargs):
        """
        批量更新统计指标

        Args:
            **kwargs: 统计指标键值对
        """
        if not kwargs:
            return

        # 转换为字符串
        stats = {k: str(v) for k, v in kwargs.items()}

        self._safe_execute(
            lambda: self.client.hset("trading:stats", mapping=stats)
        )

    # === Round Trip数据 ===

    def set_round_trips(self, active: list, completed_count: int):
        """
        更新Round Trip数据

        Args:
            active: 活跃的round trips列表
            completed_count: 已完成的round trips数量
        """
        data = {
            "active": active,
            "completed_count": completed_count
        }

        self._safe_execute(
            lambda: self.client.set("trading:round_trips", json.dumps(data))
        )

    # === Pub/Sub事件通知 ===

    def _notify(self, event_type: str, data: Any = None):
        """
        发布事件通知到订阅者

        Args:
            event_type: 事件类型
            data: 事件数据(可选)
        """
        event = {
            "type": event_type,
            "data": data
        }

        self._safe_execute(
            lambda: self.client.publish("trading:events", json.dumps(event))
        )

    # === 健康检查 ===

    def is_connected(self) -> bool:
        """
        检查Redis连接状态，断开时自动尝试重连

        Returns:
            bool: 当前是否连接
        """
        # 如果已断开，尝试重连
        if not self.connected:
            return self._try_reconnect()

        # 如果标记为已连接，验证连接有效性
        try:
            self.client.ping()
            return True
        except Exception as e:
            # PING失败，标记为断开
            self.connected = False
            print(f"[WARN] Redis连接已断开: {e}")

            # 立即尝试一次重连
            return self._try_reconnect()
