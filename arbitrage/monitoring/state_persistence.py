"""
State Persistence - 策略状态持久化适配器

将策略状态（positions, order_to_pair）持久化到 Redis/ObjectStore 的适配器层。
从核心策略逻辑 (BaseStrategy) 中解耦持久化实现细节。
"""
from AlgorithmImports import *
from typing import Dict, Tuple, Optional
import json
import redis


class StatePersistence:
    """
    策略状态持久化管理器

    负责:
    - 持久化策略状态到 Redis（主） + ObjectStore（备份）
    - 从 Redis/ObjectStore 恢复状态
    - 序列化/反序列化 positions 和 order_to_pair

    使用方式:
        persistence = StatePersistence(algorithm, redis_client)
        persistence.persist(positions, order_to_pair)
        state_data = persistence.restore()
    """

    def __init__(self, algorithm: QCAlgorithm, strategy_name: str, redis_client=None):
        """
        初始化状态持久化管理器

        Args:
            algorithm: QCAlgorithm 实例
            strategy_name: 策略类名（用于生成唯一 key）
            redis_client: Redis 客户端实例（可选）
        """
        self.algorithm = algorithm
        self.strategy_name = strategy_name
        self.redis_client = redis_client

    def _get_redis_key(self) -> str:
        """
        获取 Redis 的 key (可以使用冒号)

        格式: strategy:state:{AlgorithmName}:{StrategyClassName}

        示例:
        - strategy:state:ArbitrageBot_Live:LongCryptoStrategy
        - strategy:state:0-0-Arbitrage:LongCryptoStrategy
        """
        algo_name = self.algorithm.Name or "default"
        return f"strategy:state:{algo_name}:{self.strategy_name}"

    def _get_objectstore_path(self) -> str:
        """
        获取 ObjectStore 的 path (使用斜杠，避免冒号)

        格式: trade_data/state/{StrategyClassName}/latest

        示例:
        - trade_data/state/LongCryptoStrategy/latest
        - trade_data/state/BothSideStrategy/latest
        """
        return f"trade_data/state/{self.strategy_name}/latest"

    def persist(self, grid_positions: Dict = None, execution_targets: Dict = None):
        """
        持久化网格状态到 Redis（主） + ObjectStore（备份）

        保存内容:
        - timestamp: 保存时间
        - grid_positions: 网格持仓（GridPositionManager.grid_positions）
        - execution_targets: 活跃执行目标（ExecutionManager.active_targets）

        原子性: Redis 使用单个 SET 命令，天然原子性

        Args:
            grid_positions: GridPositionManager.grid_positions
            execution_targets: ExecutionManager.active_targets

        Note:
            不再保存 positions 和 order_to_pair，因为：
            1. 券商账户可以恢复 positions（通过 BrokerageRecoverySetupHandler）
            2. ExecutionManager 已经追踪了活跃订单（通过 execution_targets）
        """
        # 构建状态数据
        state_data = {
            "timestamp": str(self.algorithm.Time),
            "grid_positions": self._serialize_grid_positions(grid_positions) if grid_positions else {},
            "execution_targets": self._serialize_execution_targets(execution_targets) if execution_targets else {}
        }

        state_json = json.dumps(state_data, indent=2)

        # 1. 优先写入 Redis (使用冒号格式的key)
        redis_success = False
        if self.redis_client:
            try:
                redis_key = self._get_redis_key()
                self.redis_client.set(redis_key, state_json)
                redis_success = True
                grid_pos_count = len(grid_positions) if grid_positions else 0
                exec_target_count = len(execution_targets) if execution_targets else 0
                self.algorithm.Debug(
                    f"💾 Persisted to Redis: {grid_pos_count} grid positions, "
                    f"{exec_target_count} execution targets"
                )
            except Exception as e:
                self.algorithm.Error(f"⚠️ Redis write failed: {e}")

        # 2. 降级到 ObjectStore（如果 Redis 失败或作为备份，使用斜杠格式的path）
        if not redis_success or True:  # 总是双写，确保备份
            try:
                objectstore_path = self._get_objectstore_path()
                self.algorithm.ObjectStore.Save(objectstore_path, state_json)
                if not redis_success:
                    self.algorithm.Debug("✓ Fallback to ObjectStore")
            except Exception as e:
                self.algorithm.Error(f"❌ ObjectStore write failed: {e}")

    def restore(self) -> Optional[Dict]:
        """
        从 Redis/ObjectStore 恢复状态

        对比两者的时间戳，返回最新的数据

        Returns:
            状态数据字典，包含:
            - timestamp: 保存时间
            - positions: 序列化的持仓数据
            - order_to_pair: 序列化的订单映射
            - source: 数据来源（"Redis" 或 "ObjectStore"）

            失败返回 None
        """
        redis_data = None
        objectstore_data = None

        # 1. 尝试从 Redis 加载 (使用冒号格式的key)
        if self.redis_client:
            try:
                redis_key = self._get_redis_key()
                redis_json = self.redis_client.get(redis_key)
                if redis_json:
                    redis_data = json.loads(redis_json.decode('utf-8'))
                    redis_data['source'] = 'Redis'
            except Exception as e:
                self.algorithm.Error(f"⚠️ Redis read failed: {e}")

        # 2. 尝试从 ObjectStore 加载 (使用斜杠格式的path)
        try:
            objectstore_path = self._get_objectstore_path()
            if self.algorithm.ObjectStore.ContainsKey(objectstore_path):
                objectstore_json = self.algorithm.ObjectStore.Read(objectstore_path)
                objectstore_data = json.loads(objectstore_json)
                objectstore_data['source'] = 'ObjectStore'
        except Exception as e:
            self.algorithm.Error(f"⚠️ ObjectStore read failed: {e}")

        # 3. 对比时间戳，返回最新的
        if redis_data and objectstore_data:
            redis_time = redis_data.get('timestamp', '')
            objectstore_time = objectstore_data.get('timestamp', '')
            if redis_time >= objectstore_time:
                self.algorithm.Debug("📂 Using Redis data (newer)")
                return redis_data
            else:
                self.algorithm.Debug("📂 Using ObjectStore data (newer)")
                return objectstore_data
        elif redis_data:
            return redis_data
        elif objectstore_data:
            return objectstore_data
        else:
            return None

    # ============================================================================
    #                      Grid State Serialization (GridStrategy)
    # ============================================================================
    #
    # 注意：
    # - _serialize_positions() 和 _serialize_order_to_pair() 已移除
    # - deserialize_positions() 和 deserialize_order_to_pair() 已移除
    # - 只保留 grid_positions 和 execution_targets 的序列化/反序列化
    #
    # 原因：
    # 1. 券商账户可以恢复 positions（通过 BrokerageRecoverySetupHandler）
    # 2. ExecutionManager 追踪活跃订单（通过 execution_targets）
    # 3. 只需要保存券商无法恢复的状态（网格配置相关）
    # ============================================================================

    @staticmethod
    def _serialize_grid_positions(grid_positions: Dict) -> dict:
        """
        序列化 GridPositionManager.grid_positions

        从: {GridLevel: GridPosition}
        到: {str(hash): {"level_data": {...}, "leg1_qty": float, "leg2_qty": float}}

        Args:
            grid_positions: GridPositionManager.grid_positions 字典

        Returns:
            序列化的网格持仓数据
        """
        result = {}

        for grid_level, grid_position in grid_positions.items():
            hash_key = str(hash(grid_level))

            # 序列化 GridLevel 数据（用于日志和验证）
            level_data = {
                "level_id": grid_level.level_id,
                "type": grid_level.type,
                "spread_pct": float(grid_level.spread_pct),
                "direction": grid_level.direction,
                "pair_symbol": [
                    grid_level.pair_symbol[0].value,
                    grid_level.pair_symbol[1].value
                ],
                "position_size_pct": float(grid_level.position_size_pct)
            }

            # 序列化 GridPosition 数据
            leg1_qty, leg2_qty = grid_position.quantity

            result[hash_key] = {
                "level_data": level_data,
                "leg1_qty": float(leg1_qty),
                "leg2_qty": float(leg2_qty)
            }

        return result

    def deserialize_grid_positions(self, data: dict, grid_level_manager) -> Dict:
        """
        反序列化 grid_positions

        从: {str(hash): {"level_data": {...}, "leg1_qty": float, "leg2_qty": float}}
        到: {GridLevel: GridPosition}

        使用严格 hash 匹配：只恢复 hash 完全匹配的 GridPosition

        Args:
            data: 序列化的网格持仓数据
            grid_level_manager: GridLevelManager 实例（用于通过 hash 查找 GridLevel）

        Returns:
            反序列化的网格持仓字典
        """
        grid_positions = {}
        restored_count = 0
        skipped_count = 0

        for hash_str, position_data in data.items():
            hash_value = int(hash_str)
            level_data = position_data["level_data"]

            # 严格 hash 匹配：通过 hash 查找当前配置的 GridLevel
            grid_level = grid_level_manager.find_level_by_hash(hash_value)

            if not grid_level:
                # Hash 不匹配，跳过恢复
                self.algorithm.debug(
                    f"⚠️ Skipped GridPosition: hash={hash_value} | "
                    f"level_id={level_data['level_id']} (no matching GridLevel in current config)"
                )
                skipped_count += 1
                continue

            # 验证 GridLevel 本质属性是否一致（额外检查，防止 hash 冲突）
            if (grid_level.type != level_data["type"] or
                abs(grid_level.spread_pct - level_data["spread_pct"]) > 1e-6 or
                grid_level.direction != level_data["direction"]):
                self.algorithm.debug(
                    f"⚠️ Skipped GridPosition: hash={hash_value} | "
                    f"level_id={level_data['level_id']} (GridLevel attributes mismatch)"
                )
                skipped_count += 1
                continue

            # 重建 GridPosition
            # 注意：GridPosition 需要通过 GridPositionManager.get_or_create_grid_position() 创建
            # 这里只返回数据，由 GridPositionManager 负责创建对象
            grid_positions[grid_level] = {
                "leg1_qty": float(position_data["leg1_qty"]),
                "leg2_qty": float(position_data["leg2_qty"])
            }

            restored_count += 1
            self.algorithm.debug(
                f"✅ Restored GridPosition: {grid_level.level_id} | "
                f"Qty: {position_data['leg1_qty']:.2f} / {position_data['leg2_qty']:.2f}"
            )

        if skipped_count > 0:
            self.algorithm.debug(
                f"⚠️ Skipped {skipped_count} GridPositions (config changed or hash mismatch)"
            )

        return grid_positions

    @staticmethod
    def _serialize_execution_targets(execution_targets: Dict) -> dict:
        """
        序列化 ExecutionManager.active_targets

        从: {hash(GridLevel): ExecutionTarget}
        到: {str(hash): ExecutionTarget.to_dict()}

        使用 ExecutionTarget.to_dict() 完整序列化，包含：
        - 基本字段（grid_id, target_qty, status, etc.）
        - order_groups 列表（包含 completed_tickets_json 和 active_broker_ids）

        Args:
            execution_targets: ExecutionManager.active_targets 字典

        Returns:
            序列化的执行目标数据
        """
        result = {}

        for hash_key, exec_target in execution_targets.items():
            # ✅ 使用 ExecutionTarget.to_dict() 完整序列化
            result[str(hash_key)] = exec_target.to_dict()

        return result

    def deserialize_execution_targets(self, data: dict, grid_level_manager) -> Dict:
        """
        反序列化 execution_targets

        从: {str(hash): {"grid_id": str, "target_qty": {...}, "status": str, ...}}
        到: {hash(GridLevel): ExecutionTarget_data}

        使用严格 hash 匹配：只恢复 hash 完全匹配的 ExecutionTarget

        Args:
            data: 序列化的执行目标数据
            grid_level_manager: GridLevelManager 实例（用于通过 hash 查找 GridLevel）

        Returns:
            反序列化的执行目标数据字典（返回原始数据，由 ExecutionManager 负责重建对象）
        """
        execution_targets_data = {}
        restored_count = 0
        skipped_count = 0

        for hash_str, target_data in data.items():
            hash_value = int(hash_str)

            # 严格 hash 匹配：通过 hash 查找当前配置的 GridLevel
            grid_level = grid_level_manager.find_level_by_hash(hash_value)

            if not grid_level:
                # Hash 不匹配，跳过恢复
                self.algorithm.debug(
                    f"⚠️ Skipped ExecutionTarget: hash={hash_value} | "
                    f"grid_id={target_data['grid_id']} (no matching GridLevel in current config)"
                )
                skipped_count += 1
                continue

            # 保存原始数据和匹配的 GridLevel
            execution_targets_data[hash_value] = {
                "grid_level": grid_level,
                "target_data": target_data
            }

            restored_count += 1
            self.algorithm.debug(
                f"✅ Restored ExecutionTarget: {target_data['grid_id']} | "
                f"Status: {target_data['status']}"
            )

        if skipped_count > 0:
            self.algorithm.debug(
                f"⚠️ Skipped {skipped_count} ExecutionTargets (config changed or hash mismatch)"
            )

        return execution_targets_data

    @staticmethod
    def init_redis_connection(algorithm: QCAlgorithm):
        """
        初始化 Redis 连接（静态工具方法）

        Args:
            algorithm: QCAlgorithm 实例

        Returns:
            Redis 客户端实例，失败返回 None
        """
        try:
            client = redis.StrictRedis(
                host='localhost',  # Docker 容器地址
                port=6379,
                db=0,
                decode_responses=False,  # 保留 bytes 格式
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # 测试连接
            client.ping()
            algorithm.Debug("✅ Redis connected successfully")
            return client
        except Exception as e:
            algorithm.Error(f"❌ Redis connection failed: {e}")
            return None
