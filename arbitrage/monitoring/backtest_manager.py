"""
Backtest History Manager - 回测历史管理器

功能:
1. 管理回测结果的存储和索引
2. 提供回测历史查询接口
3. 自动发现和索引 Grid 回测报告

目录结构:
    backtest_history/
        index.json                          # 回测索引文件
        20251021_221430/                    # 回测时间戳目录
            grid_order_tracker_data.json    # GridOrderTracker 数据
            grid_order_tracker_data_grid.html  # HTML 报告
            metadata.json                    # 回测元数据
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class BacktestMetadata:
    """回测元数据"""
    backtest_id: str  # 唯一标识符（时间戳）
    name: str  # 回测名称
    description: str  # 描述
    created_at: str  # 创建时间 ISO8601
    start_date: str  # 回测开始日期
    end_date: str  # 回测结束日期
    algorithm: str  # 算法名称
    total_round_trips: int  # Round Trips 数量
    total_execution_targets: int  # ExecutionTarget 数量
    total_pnl: float  # 总盈亏
    has_html_report: bool  # 是否有 HTML 报告
    json_file: str  # JSON 文件路径（相对路径）
    html_file: Optional[str]  # HTML 文件路径（相对路径）


class BacktestManager:
    """
    回测历史管理器

    负责管理回测结果的存储、索引和查询
    """

    def __init__(self, history_dir: str = "backtest_history"):
        """
        初始化回测管理器

        Args:
            history_dir: 回测历史存储目录（相对于当前工作目录）
        """
        self.history_dir = Path(history_dir)
        self.index_file = self.history_dir / "index.json"

        # 确保目录存在
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # 加载或创建索引
        self.index = self._load_index()

    def _load_index(self) -> Dict[str, Any]:
        """加载回测索引"""
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARN] Failed to load index: {e}, creating new index")

        # 创建新索引
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "backtests": []
        }

    def _save_index(self):
        """保存回测索引"""
        self.index["last_updated"] = datetime.now().isoformat()

        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)

    def add_backtest(
        self,
        json_file: str,
        html_file: Optional[str] = None,
        name: Optional[str] = None,
        description: str = "",
        algorithm: str = "Unknown"
    ) -> str:
        """
        添加回测到历史记录

        Args:
            json_file: GridOrderTracker JSON 文件路径
            html_file: Grid HTML 报告文件路径（可选）
            name: 回测名称（可选，默认使用时间戳）
            description: 回测描述
            algorithm: 算法名称

        Returns:
            backtest_id: 回测唯一标识符
        """
        # 生成回测 ID（时间戳）
        backtest_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 创建回测目录
        backtest_dir = self.history_dir / backtest_id
        backtest_dir.mkdir(parents=True, exist_ok=True)

        # 读取 JSON 数据提取元数据
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        meta = data.get('meta', {})

        # 复制文件到回测目录
        import shutil

        dest_json = backtest_dir / "grid_order_tracker_data.json"
        shutil.copy2(json_file, dest_json)

        dest_html = None
        if html_file and Path(html_file).exists():
            dest_html = backtest_dir / "grid_order_tracker_data_grid.html"
            shutil.copy2(html_file, dest_html)

        # 创建元数据
        metadata = BacktestMetadata(
            backtest_id=backtest_id,
            name=name or f"Backtest {backtest_id}",
            description=description,
            created_at=datetime.now().isoformat(),
            start_date=meta.get('start_time', 'N/A'),
            end_date=meta.get('end_time', 'N/A'),
            algorithm=algorithm,
            total_round_trips=meta.get('total_round_trips', 0),
            total_execution_targets=meta.get('total_execution_targets', 0),
            total_pnl=self._calculate_total_pnl(data),
            has_html_report=dest_html is not None,
            json_file=str(dest_json.relative_to(self.history_dir)),
            html_file=str(dest_html.relative_to(self.history_dir)) if dest_html else None
        )

        # 保存元数据到回测目录
        metadata_file = backtest_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

        # 添加到索引
        self.index["backtests"].append(asdict(metadata))
        self._save_index()

        print(f"[OK] Backtest added to history: {backtest_id}")
        return backtest_id

    def _calculate_total_pnl(self, data: Dict) -> float:
        """从 JSON 数据计算总盈亏"""
        round_trips = data.get('round_trips', [])
        total_pnl = sum(
            rt.get('net_pnl', 0)
            for rt in round_trips
            if rt.get('net_pnl') is not None
        )
        return total_pnl

    def list_backtests(
        self,
        limit: Optional[int] = None,
        sort_by: str = "created_at",
        reverse: bool = True
    ) -> List[Dict]:
        """
        列出所有回测（通过遍历文件夹）

        Args:
            limit: 最大数量限制
            sort_by: 排序字段（created_at, total_pnl, total_round_trips）
            reverse: 是否倒序（默认 True，最新的在前）

        Returns:
            回测元数据列表
        """
        backtests = []

        # 遍历 backtest_history 目录下的所有子目录
        if not self.history_dir.exists():
            return backtests

        for backtest_dir in self.history_dir.iterdir():
            # 跳过非目录和 index.json 文件
            if not backtest_dir.is_dir():
                continue

            # 读取 metadata.json
            metadata_file = backtest_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    backtests.append(metadata)
            except Exception as e:
                print(f"[WARN] Failed to load metadata from {metadata_file}: {e}")
                continue

        # 排序
        if sort_by in ["created_at", "total_pnl", "total_round_trips"]:
            backtests = sorted(
                backtests,
                key=lambda x: x.get(sort_by, 0),
                reverse=reverse
            )

        # 限制数量
        if limit:
            backtests = backtests[:limit]

        return backtests

    def get_backtest(self, backtest_id: str) -> Optional[Dict]:
        """
        获取指定回测的详细信息（从文件夹读取）

        Args:
            backtest_id: 回测唯一标识符

        Returns:
            回测元数据，如果不存在返回 None
        """
        # 直接从文件夹读取 metadata.json
        backtest_dir = self.history_dir / backtest_id
        metadata_file = backtest_dir / "metadata.json"

        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load metadata from {metadata_file}: {e}")
            return None

    def get_backtest_data(self, backtest_id: str) -> Optional[Dict]:
        """
        获取回测的完整 JSON 数据

        Args:
            backtest_id: 回测唯一标识符

        Returns:
            GridOrderTracker JSON 数据，如果不存在返回 None
        """
        backtest = self.get_backtest(backtest_id)
        if not backtest:
            return None

        json_file = self.history_dir / backtest["json_file"]
        if not json_file.exists():
            return None

        with open(json_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_backtest_html_path(self, backtest_id: str) -> Optional[Path]:
        """
        获取回测 HTML 报告的文件路径

        Args:
            backtest_id: 回测唯一标识符

        Returns:
            HTML 文件路径，如果不存在返回 None
        """
        backtest = self.get_backtest(backtest_id)
        if not backtest or not backtest.get("html_file"):
            return None

        html_file = self.history_dir / backtest["html_file"]
        if not html_file.exists():
            return None

        return html_file

    def delete_backtest(self, backtest_id: str) -> bool:
        """
        删除指定回测

        Args:
            backtest_id: 回测唯一标识符

        Returns:
            是否删除成功
        """
        backtest = self.get_backtest(backtest_id)
        if not backtest:
            return False

        # 删除回测目录
        backtest_dir = self.history_dir / backtest_id
        if backtest_dir.exists():
            import shutil
            shutil.rmtree(backtest_dir)

        # 从索引中移除
        self.index["backtests"] = [
            bt for bt in self.index["backtests"]
            if bt.get("backtest_id") != backtest_id
        ]
        self._save_index()

        print(f"[OK] Backtest deleted: {backtest_id}")
        return True

    def scan_and_import(self, source_dir: str = "."):
        """
        扫描指定目录，自动发现并导入回测结果

        Args:
            source_dir: 源目录（默认当前目录）
        """
        source_path = Path(source_dir)

        # 查找所有 grid_order_tracker_data.json 文件
        json_files = list(source_path.glob("**/grid_order_tracker_data.json"))

        imported = 0
        for json_file in json_files:
            # 检查是否已在 history 目录中
            if self.history_dir in json_file.parents:
                continue

            # 查找对应的 HTML 文件
            html_file = json_file.with_name("grid_order_tracker_data_grid.html")
            html_file = html_file if html_file.exists() else None

            # 提取算法名称（从父目录）
            algorithm = json_file.parent.name

            # 导入
            try:
                self.add_backtest(
                    str(json_file),
                    str(html_file) if html_file else None,
                    algorithm=algorithm,
                    description=f"Auto-imported from {json_file.parent}"
                )
                imported += 1
            except Exception as e:
                print(f"[WARN] Failed to import {json_file}: {e}")

        print(f"[OK] Imported {imported} backtests")

    def get_statistics(self) -> Dict[str, Any]:
        """获取回测历史统计信息（从文件夹读取）"""
        backtests = self.list_backtests()

        total_pnl = sum(bt.get("total_pnl", 0) for bt in backtests)
        total_round_trips = sum(bt.get("total_round_trips", 0) for bt in backtests)

        return {
            "total_backtests": len(backtests),
            "total_pnl": total_pnl,
            "total_round_trips": total_round_trips,
            "avg_pnl_per_backtest": total_pnl / len(backtests) if backtests else 0
        }


# CLI 工具
if __name__ == "__main__":
    import sys

    # CLI 工具默认使用 monitoring/backtest_history 路径
    # 如果从 monitoring 目录运行，则使用 backtest_history
    # 如果从 arbitrage 目录运行，则使用 monitoring/backtest_history
    default_history_dir = Path(__file__).parent / "backtest_history"
    manager = BacktestManager(history_dir=str(default_history_dir))

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python backtest_manager.py list                 # 列出所有回测")
        print("  python backtest_manager.py scan [dir]           # 扫描并导入回测")
        print("  python backtest_manager.py add <json> [html]    # 添加回测")
        print("  python backtest_manager.py delete <id>          # 删除回测")
        print("  python backtest_manager.py stats                # 显示统计")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        backtests = manager.list_backtests()
        print(f"\nFound {len(backtests)} backtests:\n")
        for bt in backtests:
            print(f"ID: {bt['backtest_id']}")
            print(f"  Name: {bt['name']}")
            print(f"  Period: {bt['start_date']} to {bt['end_date']}")
            print(f"  Round Trips: {bt['total_round_trips']}")
            print(f"  PnL: ${bt['total_pnl']:.2f}")
            print(f"  HTML: {'Yes' if bt['has_html_report'] else 'No'}")
            print()

    elif command == "scan":
        source_dir = sys.argv[2] if len(sys.argv) > 2 else "."
        manager.scan_and_import(source_dir)

    elif command == "add":
        if len(sys.argv) < 3:
            print("Error: JSON file required")
            sys.exit(1)

        json_file = sys.argv[2]
        html_file = sys.argv[3] if len(sys.argv) > 3 else None

        backtest_id = manager.add_backtest(json_file, html_file)
        print(f"Backtest ID: {backtest_id}")

    elif command == "delete":
        if len(sys.argv) < 3:
            print("Error: Backtest ID required")
            sys.exit(1)

        backtest_id = sys.argv[2]
        success = manager.delete_backtest(backtest_id)
        if not success:
            print(f"Error: Backtest {backtest_id} not found")
            sys.exit(1)

    elif command == "stats":
        stats = manager.get_statistics()
        print("\nBacktest History Statistics:")
        print(f"  Total Backtests: {stats['total_backtests']}")
        print(f"  Total PnL: ${stats['total_pnl']:.2f}")
        print(f"  Total Round Trips: {stats['total_round_trips']}")
        print(f"  Avg PnL per Backtest: ${stats['avg_pnl_per_backtest']:.2f}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
