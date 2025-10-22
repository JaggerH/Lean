"""
Monitoring Context - 统一的监控组件管理器

提供监控组件的统一初始化和访问接口，解耦监控逻辑和业务逻辑。

使用方式:
    # 在算法中创建监控上下文
    monitoring = MonitoringContext(self, mode='auto')

    # 初始化组件时注入监控
    spread_manager = SpreadManager(
        algorithm=self,
        monitor_adapter=monitoring.get_spread_monitor()
    )

    strategy = LongCryptoStrategy(
        algorithm=self,
        state_persistence=monitoring.get_state_persistence()
    )

    order_tracker = monitoring.create_order_tracker(strategy)
"""

from typing import Optional
from .redis_writer import TradingRedis
from .spread_monitor import RedisSpreadMonitor
from .state_persistence import StatePersistence
from .order_tracker import OrderTracker


class MonitoringContext:
    """
    监控上下文 - 统一管理所有监控组件

    职责:
    1. Redis 连接管理（单例）
    2. 监控组件生命周期管理
    3. Live/Backtest 模式自动检测
    4. 提供统一的监控接口

    优势:
    - 低耦合: 通过接口访问，不直接依赖具体实现
    - 易测试: 可以传入 mock 对象
    - 统一管理: 所有监控逻辑集中在一处
    """

    def __init__(
        self,
        algorithm,
        mode: str = 'auto',
        redis_config: Optional[dict] = None,
        fail_on_error: bool = False
    ):
        """
        初始化监控上下文

        Args:
            algorithm: QCAlgorithm 实例
            mode: 运行模式
                - 'live': 强制启用监控
                - 'backtest': 强制禁用监控
                - 'auto': 自动检测（默认）
            redis_config: Redis 配置字典（可选）
                - host: Redis 主机地址
                - port: Redis 端口
                - db: Redis 数据库编号
            fail_on_error: Redis 连接失败时是否抛出异常
                - True: Live 模式强制要求 Redis
                - False: 测试模式允许 Redis 失败
        """
        self.algorithm = algorithm
        self.fail_on_error = fail_on_error

        # 检测运行模式
        self.enabled = self._detect_mode(mode)

        # 核心组件（延迟初始化）
        self.redis_client: Optional[TradingRedis] = None
        self.spread_monitor: Optional[RedisSpreadMonitor] = None
        self.state_persistence: Optional[StatePersistence] = None
        self.order_tracker: Optional[OrderTracker] = None

        # 初始化监控组件
        if self.enabled:
            self._init_components(redis_config or {})

    def _detect_mode(self, mode: str) -> bool:
        """
        自动检测运行模式

        Args:
            mode: 'live' | 'backtest' | 'auto'

        Returns:
            bool: 是否启用监控
        """
        if mode == 'live':
            return True
        elif mode == 'backtest':
            return False
        else:  # 'auto'
            # 检测 Live 模式
            is_live = self.algorithm.live_mode

            # 备用检测方式（兼容某些环境）
            if is_live is None:
                is_live = hasattr(self.algorithm, 'Transactions') and \
                         hasattr(self.algorithm.Transactions, 'GetOpenOrders')

            mode_name = 'LIVE' if is_live else 'BACKTEST'
            self.algorithm.debug(f"[MonitoringContext] Detected mode: {mode_name}")

            return is_live

    def _init_components(self, redis_config: dict):
        """
        初始化所有监控组件

        Args:
            redis_config: Redis 配置字典
        """
        try:
            # === 1. 验证并初始化 Redis ===
            self.algorithm.debug("[MonitoringContext] Initializing Redis connection...")

            success, message = TradingRedis.verify_connection(
                host=redis_config.get('host', 'localhost'),
                port=redis_config.get('port', None),
                db=redis_config.get('db', 0),
                raise_on_failure=self.fail_on_error
            )

            if success:
                # 创建 TradingRedis 客户端
                self.redis_client = TradingRedis(
                    host=redis_config.get('host', 'localhost'),
                    port=redis_config.get('port', None),
                    db=redis_config.get('db', 0)
                )
                self.algorithm.debug(f"[MonitoringContext] {message}")

                # === 2. 初始化 RedisSpreadMonitor ===
                try:
                    self.spread_monitor = RedisSpreadMonitor(
                        self.algorithm,
                        self.redis_client
                    )
                    self.algorithm.debug("[MonitoringContext] ✅ RedisSpreadMonitor initialized")
                except Exception as e:
                    self.algorithm.debug(f"[MonitoringContext] ⚠️ Failed to init RedisSpreadMonitor: {e}")

                # === 3. 初始化 StatePersistence ===
                try:
                    raw_redis = StatePersistence.init_redis_connection(self.algorithm)
                    if raw_redis:
                        self.state_persistence = StatePersistence(
                            self.algorithm,
                            'Strategy',
                            raw_redis
                        )
                        self.algorithm.debug("[MonitoringContext] ✅ StatePersistence initialized")
                    else:
                        self.algorithm.debug("[MonitoringContext] ⚠️ Raw Redis client unavailable")
                except Exception as e:
                    self.algorithm.debug(f"[MonitoringContext] ⚠️ Failed to init StatePersistence: {e}")

                self.algorithm.debug("[MonitoringContext] ✅ All monitoring components initialized")

            else:
                # Redis 连接失败
                self.algorithm.debug(f"[MonitoringContext] ⚠️ Redis unavailable: {message}")
                self.algorithm.debug("[MonitoringContext] Monitoring will be disabled")
                self.enabled = False

        except Exception as e:
            self.algorithm.debug(f"[MonitoringContext] ❌ Initialization failed: {e}")

            if self.fail_on_error:
                raise RuntimeError(
                    f"Monitoring initialization failed: {e}\n"
                    f"Live mode requires Redis for data persistence.\n"
                    f"Please start Redis: docker compose up -d redis"
                )

            self.enabled = False

    # === Public API ===

    def is_enabled(self) -> bool:
        """
        监控是否启用

        Returns:
            bool: True 表示监控已启用且 Redis 连接正常
        """
        return self.enabled and self.redis_client is not None

    def get_spread_monitor(self) -> Optional[RedisSpreadMonitor]:
        """
        获取价差监控器（用于注入 SpreadManager）

        Returns:
            RedisSpreadMonitor 实例，如果监控未启用则返回 None

        Example:
            spread_manager = SpreadManager(
                algorithm=self,
                monitor_adapter=monitoring.get_spread_monitor()
            )
        """
        return self.spread_monitor if self.is_enabled() else None

    def get_state_persistence(self) -> Optional[StatePersistence]:
        """
        获取状态持久化器（用于注入 Strategy）

        Returns:
            StatePersistence 实例，如果监控未启用则返回 None

        Example:
            strategy = LongCryptoStrategy(
                algorithm=self,
                state_persistence=monitoring.get_state_persistence()
            )
        """
        return self.state_persistence if self.is_enabled() else None

    def create_order_tracker(self, strategy, debug: bool = False) -> OrderTracker:
        """
        创建 OrderTracker（延迟创建，因为需要 strategy 实例）

        Args:
            strategy: 策略实例
            debug: 是否开启调试模式

        Returns:
            OrderTracker 实例

        Note:
            OrderTracker 总是会被创建，但在 Backtest 模式下不会写入 Redis

        Example:
            order_tracker = monitoring.create_order_tracker(strategy, debug=True)
            strategy.order_tracker = order_tracker
        """
        self.order_tracker = OrderTracker(
            self.algorithm,
            strategy,
            debug=debug,
            realtime_mode=self.is_enabled(),
            redis_client=self.redis_client if self.is_enabled() else None
        )

        mode_name = 'LIVE' if self.is_enabled() else 'BACKTEST'
        self.algorithm.debug(
            f"[MonitoringContext] Created OrderTracker "
            f"(mode={mode_name}, debug={debug})"
        )

        return self.order_tracker

    def cleanup(self):
        """
        清理资源

        Note:
            Redis 连接会自动关闭，通常不需要手动调用此方法
        """
        if self.redis_client:
            # Redis 客户端会自动管理连接池
            pass

        self.algorithm.debug("[MonitoringContext] Cleanup completed")
