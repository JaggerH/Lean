"""
清空 Redis 中的交易数据

提供安全的交互式清空功能，支持选择性清空特定数据类型。

使用方式:
    # 交互式清空所有数据（会提示确认）
    conda run -n lean python arbitrage/clear_redis.py --all

    # 强制清空所有数据（不提示确认）
    conda run -n lean python arbitrage/clear_redis.py --all --force

    # 选择性清空
    conda run -n lean python arbitrage/clear_redis.py --spreads
    conda run -n lean python arbitrage/clear_redis.py --orders --snapshot
    conda run -n lean python arbitrage/clear_redis.py --pairs
    conda run -n lean python arbitrage/clear_redis.py --active-targets
    conda run -n lean python arbitrage/clear_redis.py --grid-positions
"""
import sys
import argparse
import redis
import json
from pathlib import Path

# 添加监控模块到路径
sys.path.insert(0, str(Path(__file__).parent))

from monitoring.redis_writer import TradingRedis
from monitoring.config_utils import get_redis_port_from_compose


# Redis 数据结构定义
REDIS_KEYS = {
    'pairs': {
        'key': 'trading:pair_mappings',
        'type': 'hash',
        'description': '交易对配对映射'
    },
    'spreads': {
        'key': 'trading:spreads',
        'type': 'hash',
        'description': '价差数据'
    },
    'snapshot': {
        'key': 'trading:snapshot',
        'type': 'string',
        'description': '投资组合快照'
    },
    'orders': {
        'key': 'trading:orders',
        'type': 'list',
        'description': '订单历史'
    },
    'stats': {
        'key': 'trading:stats',
        'type': 'hash',
        'description': '统计数据'
    },
    'round_trips': {
        'key': 'trading:round_trips',
        'type': 'string',
        'description': 'Round Trip 数据'
    },
    'active_targets': {
        'key': 'trading:active_targets',
        'type': 'hash',
        'description': '活跃订单执行'
    },
    'grid_positions': {
        'key': 'trading:grid_positions',
        'type': 'hash',
        'description': '网格持仓追踪'
    }
}


def get_data_stats(client):
    """
    获取 Redis 中各数据类型的统计信息

    Args:
        client: Redis 客户端

    Returns:
        dict: {key_name: count}
    """
    stats = {}

    for name, config in REDIS_KEYS.items():
        key = config['key']
        key_type = config['type']

        try:
            if key_type == 'hash':
                count = client.hlen(key)
            elif key_type == 'list':
                count = client.llen(key)
            elif key_type == 'string':
                count = 1 if client.exists(key) else 0
            else:
                count = 0

            stats[name] = count
        except Exception as e:
            print(f"[WARN] 无法获取 {key} 的统计信息: {e}")
            stats[name] = 0

    return stats


def print_stats(stats, title="当前数据统计"):
    """打印数据统计"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

    for name, count in stats.items():
        config = REDIS_KEYS[name]
        description = config['description']
        key = config['key']

        if count > 0:
            print(f"✓ {description:20} ({key:30}): {count:6} 条")
        else:
            print(f"  {description:20} ({key:30}): {count:6} 条")

    print("=" * 60)


def clear_data(client, keys_to_clear, force=False):
    """
    清空指定的 Redis 数据

    Args:
        client: Redis 客户端
        keys_to_clear: 要清空的 key 名称列表（如 ['pairs', 'spreads']）
        force: 是否跳过确认

    Returns:
        bool: 是否成功清空
    """
    # 获取清空前的统计
    stats_before = get_data_stats(client)
    print_stats(stats_before, "清空前数据统计")

    # 检查是否有数据可清空
    total_items = sum(stats_before[k] for k in keys_to_clear)
    if total_items == 0:
        print("\n[INFO] 没有数据需要清空")
        return True

    # 显示将要清空的数据
    print("\n" + "=" * 60)
    print("  将要清空以下数据:")
    print("=" * 60)
    for key_name in keys_to_clear:
        config = REDIS_KEYS[key_name]
        count = stats_before[key_name]
        if count > 0:
            print(f"  {config['description']:20} ({config['key']:30}): {count:6} 条")
    print("=" * 60)

    # 确认提示（除非使用 --force）
    if not force:
        print("\n⚠️  警告: 此操作将永久删除上述数据，无法恢复！")
        response = input("是否继续？(输入 'yes' 确认): ").strip().lower()
        if response != 'yes':
            print("\n[INFO] 操作已取消")
            return False

    # 执行清空
    print("\n开始清空数据...")
    cleared_count = 0

    for key_name in keys_to_clear:
        config = REDIS_KEYS[key_name]
        key = config['key']

        try:
            result = client.delete(key)
            if result > 0 or stats_before[key_name] > 0:
                print(f"✓ 已清空 {config['description']} ({key})")
                cleared_count += 1
        except Exception as e:
            print(f"❌ 清空 {key} 失败: {e}")

    # 获取清空后的统计
    stats_after = get_data_stats(client)
    print_stats(stats_after, "清空后数据统计")

    # 验证清空结果
    remaining_items = sum(stats_after[k] for k in keys_to_clear)
    if remaining_items == 0:
        print(f"\n✅ 成功清空 {cleared_count} 个数据类型")
        return True
    else:
        print(f"\n⚠️  部分数据未清空成功，剩余 {remaining_items} 条")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='清空 Redis 中的交易数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 清空所有数据（交互式确认）
  python clear_redis.py --all

  # 强制清空所有数据（跳过确认）
  python clear_redis.py --all --force

  # 选择性清空
  python clear_redis.py --spreads --orders
  python clear_redis.py --pairs
  python clear_redis.py --snapshot --stats
  python clear_redis.py --active-targets
  python clear_redis.py --grid-positions
        """
    )

    # 数据类型选项
    parser.add_argument('--all', action='store_true',
                        help='清空所有数据')
    parser.add_argument('--pairs', action='store_true',
                        help='清空交易对配对映射')
    parser.add_argument('--spreads', action='store_true',
                        help='清空价差数据')
    parser.add_argument('--snapshot', action='store_true',
                        help='清空投资组合快照')
    parser.add_argument('--orders', action='store_true',
                        help='清空订单历史')
    parser.add_argument('--stats', action='store_true',
                        help='清空统计数据')
    parser.add_argument('--round-trips', action='store_true',
                        help='清空 Round Trip 数据')
    parser.add_argument('--active-targets', action='store_true',
                        help='清空活跃订单执行')
    parser.add_argument('--grid-positions', action='store_true',
                        help='清空网格持仓追踪')

    # 控制选项
    parser.add_argument('--force', action='store_true',
                        help='跳过确认，直接清空')

    args = parser.parse_args()

    # 检查参数
    has_selection = any([
        args.all, args.pairs, args.spreads, args.snapshot,
        args.orders, args.stats, args.round_trips,
        args.active_targets, args.grid_positions
    ])

    if not has_selection:
        parser.print_help()
        print("\n[ERROR] 请至少指定一种数据类型或使用 --all")
        sys.exit(1)

    # 确定要清空的 keys
    if args.all:
        keys_to_clear = list(REDIS_KEYS.keys())
    else:
        keys_to_clear = []
        if args.pairs:
            keys_to_clear.append('pairs')
        if args.spreads:
            keys_to_clear.append('spreads')
        if args.snapshot:
            keys_to_clear.append('snapshot')
        if args.orders:
            keys_to_clear.append('orders')
        if args.stats:
            keys_to_clear.append('stats')
        if args.round_trips:
            keys_to_clear.append('round_trips')
        if args.active_targets:
            keys_to_clear.append('active_targets')
        if args.grid_positions:
            keys_to_clear.append('grid_positions')

    # 连接验证
    print("\n" + "=" * 60)
    print("  Redis 数据清空工具")
    print("=" * 60)

    print("\n检查 Redis 连接...")
    success, message = TradingRedis.verify_connection(raise_on_failure=False)

    if not success:
        print(f"\n❌ {message}")
        print("\n请先启动 Redis:")
        print("  cd arbitrage")
        print("  docker compose up -d redis")
        sys.exit(1)

    print(f"✅ {message}")

    # 创建 Redis 客户端
    port = get_redis_port_from_compose()
    client = redis.Redis(
        host='localhost',
        port=port,
        db=0,
        decode_responses=True
    )

    # 执行清空
    success = clear_data(client, keys_to_clear, force=args.force)

    # 退出
    print("\n" + "=" * 60)
    if success:
        print("  清空完成！")
    else:
        print("  清空未完全成功")
    print("=" * 60 + "\n")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
