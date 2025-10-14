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

    def persist(self, positions: Dict[Tuple[Symbol, Symbol], Tuple[float, float]],
                order_to_pair: Dict[int, Dict]):
        """
        持久化状态到 Redis（主） + ObjectStore（备份）

        保存内容:
        - timestamp: 保存时间
        - positions: 交易对持仓
        - order_to_pair: 活跃订单映射（包含 filled_qty_snapshot）

        原子性: Redis 使用单个 SET 命令，天然原子性

        Args:
            positions: {(crypto_symbol, stock_symbol): (crypto_qty, stock_qty)}
            order_to_pair: {order_id: {"pair": (Symbol, Symbol), "filled_qty_snapshot": float}}
        """
        # 构建状态数据
        state_data = {
            "timestamp": str(self.algorithm.Time),
            "positions": self._serialize_positions(positions),
            "order_to_pair": self._serialize_order_to_pair(order_to_pair)
        }

        state_json = json.dumps(state_data, indent=2)

        # 1. 优先写入 Redis (使用冒号格式的key)
        redis_success = False
        if self.redis_client:
            try:
                redis_key = self._get_redis_key()
                self.redis_client.set(redis_key, state_json)
                redis_success = True
                self.algorithm.Debug(
                    f"💾 Persisted to Redis: {len(positions)} positions, "
                    f"{len(order_to_pair)} orders"
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

    def deserialize_positions(self, data: dict,
                             symbol_resolver) -> Dict[Tuple[Symbol, Symbol], Tuple[float, float]]:
        """
        反序列化 positions

        从: {"crypto_str|stock_str": [float, float]}
        到: {(Symbol, Symbol): (float, float)}

        Args:
            data: 序列化的持仓数据
            symbol_resolver: 函数，用于从字符串查找 Symbol 对象

        Returns:
            反序列化的持仓字典
        """
        positions = {}

        for key, (crypto_qty, stock_qty) in data.items():
            crypto_str, stock_str = key.split('|')

            crypto_symbol = symbol_resolver(crypto_str)
            stock_symbol = symbol_resolver(stock_str)

            if crypto_symbol and stock_symbol:
                positions[(crypto_symbol, stock_symbol)] = (float(crypto_qty), float(stock_qty))
            else:
                self.algorithm.Debug(
                    f"⚠️ Cannot restore position: {crypto_str} or {stock_str} not found"
                )

        return positions

    def deserialize_order_to_pair(self, data: dict,
                                  symbol_resolver) -> Dict[int, Dict]:
        """
        反序列化 order_to_pair

        从: {str: {"pair": [str, str], "filled_qty_snapshot": float}}
        到: {int: {"pair": (Symbol, Symbol), "filled_qty_snapshot": float}}

        Args:
            data: 序列化的订单映射数据
            symbol_resolver: 函数，用于从字符串查找 Symbol 对象

        Returns:
            反序列化的订单映射字典
        """
        order_to_pair = {}

        for order_id_str, info in data.items():
            order_id = int(order_id_str)
            crypto_str, stock_str = info["pair"]

            crypto_symbol = symbol_resolver(crypto_str)
            stock_symbol = symbol_resolver(stock_str)

            if crypto_symbol and stock_symbol:
                order_to_pair[order_id] = {
                    "pair": (crypto_symbol, stock_symbol),
                    "filled_qty_snapshot": float(info["filled_qty_snapshot"])
                }
            else:
                self.algorithm.Debug(f"⚠️ Cannot restore order {order_id}")

        return order_to_pair

    @staticmethod
    def _serialize_positions(positions: Dict[Tuple[Symbol, Symbol], Tuple[float, float]]) -> dict:
        """
        序列化 positions

        从: {(Symbol, Symbol): (float, float)}
        到: {"crypto_str|stock_str": [float, float]}

        Args:
            positions: 持仓字典

        Returns:
            序列化的持仓数据
        """
        return {
            f"{crypto.Value}|{stock.Value}": [float(crypto_qty), float(stock_qty)]
            for (crypto, stock), (crypto_qty, stock_qty) in positions.items()
        }

    @staticmethod
    def _serialize_order_to_pair(order_to_pair: Dict[int, Dict]) -> dict:
        """
        序列化 order_to_pair

        从: {int: {"pair": (Symbol, Symbol), "filled_qty_snapshot": float}}
        到: {str: {"pair": [str, str], "filled_qty_snapshot": float}}

        Args:
            order_to_pair: 订单映射字典

        Returns:
            序列化的订单映射数据
        """
        return {
            str(order_id): {
                "pair": [info["pair"][0].Value, info["pair"][1].Value],
                "filled_qty_snapshot": float(info["filled_qty_snapshot"])
            }
            for order_id, info in order_to_pair.items()
        }

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
