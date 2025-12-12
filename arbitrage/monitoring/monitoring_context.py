"""
Monitoring Context - 统一的监控组件管理器

提供监控组件的统一初始化和访问接口，解耦监控逻辑和业务逻辑。

更新内容 (2025-12-13):
- 移除了对已废弃的 strategy.execution_models 模块的依赖
- 定义本地 ExecutionStatus 枚举用于监控目的
- 保持向后兼容的监控接口

使用方式:
    # 在算法中创建监控上下文
    monitoring = MonitoringContext(self, mode='auto')

    # 使用监控组件
    spread_monitor = monitoring.get_spread_monitor()
    state_persistence = monitoring.get_state_persistence()
    order_tracker = monitoring.create_order_tracker()
"""

from typing import Optional
from enum import Enum
from .redis_writer import TradingRedis
from .spread_monitor import RedisSpreadMonitor
from .state_persistence import StatePersistence
from .order_tracker import OrderTracker


class ExecutionStatus(Enum):
    """
    执行状态枚举（本地定义，用于监控目的）

    Note: 这是为了兼容旧代码定义的本地枚举。
    在新的Framework中，执行状态由Framework管理。
    """
    New = "New"
    Submitted = "Submitted"
    PartiallyFilled = "PartiallyFilled"
    Filled = "Filled"
    Canceled = "Canceled"
    Invalid = "Invalid"
    Failed = "Failed"


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
        strategy_name: str = "GridStrategy",
        mode: str = 'auto',
        redis_config: Optional[dict] = None,
        fail_on_error: bool = False
    ):
        """
        初始化监控上下文（纯工具箱，不依赖 Strategy 引用）

        Args:
            algorithm: QCAlgorithm 实例
            strategy_name: 策略类名（用于 StatePersistence key 生成）
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
        self.strategy_name = strategy_name
        self.fail_on_error = fail_on_error

        # 检测运行模式
        self.is_live = self._detect_mode(mode)
        self.enabled = self.is_live  # Redis 组件是否启用（仅 Live 模式）

        # 核心组件
        self.redis_client: Optional[TradingRedis] = None
        self.spread_monitor: Optional[RedisSpreadMonitor] = None
        self.state_persistence: Optional[StatePersistence] = None
        self.order_tracker: Optional[OrderTracker] = None

        # ✅ 1. 初始化 Redis 组件（仅 Live 模式）
        if self.enabled:
            self._init_redis_components(redis_config or {})
        else:
            # ⚠️ Trick for testing: 在 Backtest 模式下也初始化 StatePersistence
            # 这样可以测试持久化功能（使用 LocalObjectStore，不需要 Redis）
            # 正常情况下，Backtest 模式不需要状态持久化
            self._init_backtest_state_persistence()

        # ✅ 2. 初始化 OrderTracker（所有模式）
        self._init_order_tracker()

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

    def _init_redis_components(self, redis_config: dict):
        """
        初始化 Redis 相关监控组件（仅 Live 模式）

        包括：SpreadMonitor, StatePersistence

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
                raw_redis = StatePersistence.init_redis_connection(self.algorithm)
                if raw_redis:
                    self.state_persistence = StatePersistence(
                        self.algorithm,
                        self.strategy_name,  # 使用传入的策略类名
                        raw_redis
                    )
                    self.algorithm.debug("[MonitoringContext] ✅ StatePersistence initialized")
                else:
                    self.algorithm.debug("[MonitoringContext] ⚠️ Raw Redis client unavailable")

                self.algorithm.debug("[MonitoringContext] ✅ Redis components initialized")

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

    def _init_backtest_state_persistence(self):
        """
        初始化 Backtest 模式下的 StatePersistence (使用 LocalObjectStore)

        这是一个 "trick" 用于在 Backtest 环境下测试持久化功能
        """
        try:
            self.algorithm.debug("[MonitoringContext] Initializing StatePersistence for Backtest mode...")

            # 在 Backtest 模式下，不需要 Redis，直接传 None
            # StatePersistence 会自动使用 LocalObjectStore
            self.state_persistence = StatePersistence(
                self.algorithm,
                self.strategy_name,
                redis_client=None  # Backtest 模式下使用 LocalObjectStore
            )

            self.algorithm.debug("[MonitoringContext] ✅ StatePersistence initialized (Backtest mode with LocalObjectStore)")

        except Exception as e:
            self.algorithm.debug(f"[MonitoringContext] ❌ Failed to init StatePersistence in Backtest mode: {e}")
            import traceback
            self.algorithm.debug(traceback.format_exc())

    def _init_order_tracker(self):
        """
        初始化 OrderTracker（所有模式都启用）

        行为差异：
        - Live 模式：realtime_mode=True，实时写入 Redis（前端看执行过程）
        - Backtest 模式：realtime_mode=False，数据保存内存，算法结束导出 JSON（前端看结果）
        """
        try:
            self.order_tracker = OrderTracker(
                self.algorithm,
                strategy=None,  # ✅ 不再传入 strategy
                debug=False,
                realtime_mode=self.is_live,  # Live 模式实时写入 Redis
                redis_client=self.redis_client if self.is_live else None  # Live 模式传入 Redis 客户端
            )

            mode_name = 'LIVE' if self.is_live else 'BACKTEST'
            realtime_status = 'realtime (Redis)' if self.is_live else 'memory only (JSON export on end)'
            self.algorithm.debug(
                f"[MonitoringContext] ✅ OrderTracker initialized "
                f"(mode={mode_name}, {realtime_status})"
            )

        except Exception as e:
            self.algorithm.error(f"[MonitoringContext] ❌ Failed to init OrderTracker: {e}")
            self.order_tracker = None

    # ========================================================================
    #                          事件处理器
    # ========================================================================

    def on_execution_event(self, target, grid_positions: dict, execution_targets: dict):
        """
        ✅ 执行事件处理器（由 GridStrategy.on_execution_event() 调用）

        功能:
        1. OrderTracker 追踪 ExecutionTarget 状态变化（所有模式）
        2. StatePersistence 持久化网格状态（仅 Live 模式）

        Args:
            target: ExecutionTarget 对象
            grid_positions: GridPositionManager.grid_positions（由 Strategy 主动传入）
            execution_targets: ExecutionManager.active_targets（由 Strategy 主动传入）

        Note:
            数据由 Strategy 主动推送，MonitoringContext 不访问 Strategy 内部状态
        """
        try:
            # ✅ 1. OrderTracker 追踪（所有模式都执行）
            if self.order_tracker:
                # 检查 target.status 属性（如果存在）
                if hasattr(target, 'status') and target.status == ExecutionStatus.New:
                    self.order_tracker.on_execution_target_registered(target)
                elif hasattr(target, 'status'):
                    self.order_tracker.on_execution_target_update(target)

            # ✅ 2. StatePersistence 持久化（仅 Live 模式）
            if self.enabled and self.state_persistence:
                self.state_persistence.persist(
                    grid_positions=grid_positions,
                    execution_targets=execution_targets
                )

        except Exception as ex:
            self.algorithm.error(f"[MonitoringContext] on_execution_event failed: {ex}")

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

        ⚠️ Deprecated: 此方法已弃用

        新架构中，状态持久化由 MonitoringContext 通过事件机制自动处理。
        Strategy 不再需要持有 state_persistence 引用。

        为了向后兼容保留此方法。

        Returns:
            StatePersistence 实例，如果监控未启用则返回 None

        Example (旧方式，已弃用):
            strategy = LongCryptoStrategy(
                algorithm=self,
                state_persistence=monitoring.get_state_persistence()
            )

        Example (新方式):
            strategy = GridStrategy(algorithm=self)
            monitoring.register_strategy(strategy)
        """
        if self.strategy is None:
            self.algorithm.debug(
                "[MonitoringContext] Warning: get_state_persistence() is deprecated. "
                "Use register_strategy() instead for event-driven architecture."
            )
        return self.state_persistence if self.is_enabled() else None

    def create_order_tracker(self, strategy, debug: bool = False) -> OrderTracker:
        """
        创建 OrderTracker（延迟创建，因为需要 strategy 实例）

        ⚠️ Deprecated: 此方法已弃用

        新架构中，OrderTracker 在 register_strategy() 时自动创建并注入。
        此方法保留仅用于向后兼容。

        Args:
            strategy: 策略实例
            debug: 是否开启调试模式

        Returns:
            OrderTracker 实例

        Example (旧方式，已弃用):
            order_tracker = monitoring.create_order_tracker(strategy)
            strategy.order_tracker = order_tracker

        Example (新方式):
            monitoring.register_strategy(strategy)
            # OrderTracker 自动创建并注入到 strategy.order_tracker
        """
        if self.order_tracker:
            self.algorithm.debug(
                "[MonitoringContext] Warning: create_order_tracker() is deprecated. "
                "OrderTracker is now auto-created in register_strategy()."
            )
            return self.order_tracker

        # 如果还没有创建（向后兼容路径）
        self.order_tracker = OrderTracker(
            self.algorithm,
            strategy,
            debug=debug,
            realtime_mode=self.is_enabled(),
            redis_client=self.redis_client if self.is_enabled() else None
        )

        mode_name = 'LIVE' if self.is_enabled() else 'BACKTEST'
        self.algorithm.debug(
            f"[MonitoringContext] Created OrderTracker (deprecated path) "
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
