"""
Base data source abstraction for crypto exchange integration
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any, Literal
import sys
import os


from AlgorithmImports import *

# Type alias for asset type parameter
AssetType = Literal['spot', 'future', 'all']

class BaseDataSource(ABC):
    """
    交易所数据源抽象基类

    职责：
    1. 从交易所 API 获取 tokenized stock 信息（现货 + 期货）
    2. 转换为 LEAN Symbol 交易对
    3. 同步到 symbol-properties-database.csv

    使用方式：
        # 最常用：自动同步模式
        manager = GateSymbolManager()
        pairs = manager.get_pairs(type='future')

        # 只查询不写库
        manager = GateSymbolManager(auto_sync=False)
        pairs = manager.get_pairs(type='spot')

        # 手动刷新数据
        manager.refresh()
    """

    def __init__(self, auto_sync: bool = True):
        """
        初始化数据源

        Args:
            auto_sync: 是否自动同步到数据库（默认 True）
                      True: 自动调用 _fetch_and_sync()
                      False: 手动控制

        自动流程（auto_sync=True）:
            1. fetch_spot_data() + fetch_future_data()
            2. 生成 CSV 记录
            3. 写入数据库
        """
        self.spot_data = None      # 现货原始数据
        self.future_data = None    # 期货原始数据
        self._auto_sync = auto_sync
        self._sync_results = None  # 存储同步结果

        if auto_sync:
            try:
                print(f"[INFO] Starting auto-sync for {self.__class__.__name__}...")
                self._sync_results = self._fetch_and_sync()

                if self._sync_results:
                    spot_result = self._sync_results.get('spot', {})
                    future_result = self._sync_results.get('future', {})
                    print(f"[OK] Sync complete:")
                    if spot_result:
                        print(f"     Spot: Added {spot_result.get('added', 0)}, Skipped {spot_result.get('skipped', 0)}")
                    if future_result:
                        print(f"     Future: Added {future_result.get('added', 0)}, Skipped {future_result.get('skipped', 0)}")

            except Exception as e:
                print(f"[WARN] Auto-sync failed: {e}")
                print(f"   You can still use the data source, but database may not be updated")
                import traceback
                traceback.print_exc()

    # ==================== 公共 API ====================

    def get_tokenized_stock_pairs(self, asset_type: AssetType = 'all') -> List[Tuple[Symbol, Symbol]]:
        """
        获取tokenized stock交易对（跨市场套利：Gate ↔ USA）

        Purpose:
            用于股币套利策略，获取Gate.io的tokenized stocks（xStock/Ondo）
            与对应的美股配对

        Args:
            asset_type: 'spot', 'future', 或 'all'
                - 'spot': 只返回现货tokenized stocks配对
                - 'future': 只返回期货tokenized stocks配对
                - 'all': 返回所有tokenized stocks配对

        Returns:
            List[Tuple[Symbol, Symbol]]: 交易对列表
                - 第一个Symbol: Gate.io crypto symbol (Crypto or CryptoFuture)
                - 第二个Symbol: USA equity symbol (Equity)

        Example:
            >>> manager = GateSymbolManager()
            >>> pairs = manager.get_tokenized_stock_pairs(asset_type='future')
            >>> # [(Symbol('TSLAXUSDT', CryptoFuture, gate), Symbol('TSLA', Equity, usa)), ...]
        """
        pairs = []

        # 懒加载：数据不存在时自动获取
        if asset_type in ('spot', 'all'):
            if self.spot_data is None:
                print(f"[INFO] Fetching spot data...")
                self.fetch_spot_data()

            if self.spot_data:
                for key, info in self.spot_data.items():
                    if self.is_tokenized_stock(info, 'spot'):
                        pairs.append(self.parse_symbol(info, 'spot'))

        if asset_type in ('future', 'all'):
            if self.future_data is None:
                print(f"[INFO] Fetching future data...")
                self.fetch_future_data()

            if self.future_data:
                for key, info in self.future_data.items():
                    if self.is_tokenized_stock(info, 'future'):
                        pairs.append(self.parse_symbol(info, 'future'))

        return pairs


    def refresh(self) -> Dict[str, Dict[str, int]]:
        """
        刷新数据并重新同步到数据库

        用途: 手动触发数据更新（例如：定时任务）

        Returns:
            Dict: {
                'spot': {'added': X, 'skipped': Y},
                'future': {'added': X, 'skipped': Y}
            }

        示例:
            manager = GateSymbolManager(auto_sync=False)
            result = manager.refresh()
            print(f"刷新结果: {result}")
        """
        return self._fetch_and_sync()

    # ==================== 内部方法（对外隐藏） ====================

    def _fetch_and_sync(self) -> Dict[str, Dict[str, int]]:
        """
        内部方法：获取数据 + 同步数据库（一次性完成）

        Returns:
            Dict: 同步结果
        """
        # 获取数据
        self.fetch_spot_data()
        self.fetch_future_data()

        # 同步到数据库
        if self._auto_sync:
            return self._sync_all_to_database()

        return {}

    def _sync_all_to_database(self) -> Dict[str, Dict[str, int]]:
        """
        内部方法：同步所有数据（现货 + 期货）到数据库

        Returns:
            Dict: {'spot': {...}, 'future': {...}}
        """
        results = {}

        # 同步现货
        spot_csv = self._generate_csv(asset_type='spot')
        if spot_csv:
            results['spot'] = self._save_to_database(spot_csv)

        # 同步期货
        future_csv = self._generate_csv(asset_type='future')
        if future_csv:
            results['future'] = self._save_to_database(future_csv)

        return results

    def _generate_csv(self, asset_type: str) -> List[str]:
        """
        内部方法：生成 CSV 记录

        Args:
            asset_type: 'spot' 或 'future'

        Returns:
            List[str]: CSV 行列表
        """
        csv_rows = []

        if asset_type == 'spot' and self.spot_data:
            for key, info in self.spot_data.items():
                if self.is_tokenized_stock(info, 'spot'):
                    csv_rows.append(self.to_csv_row(info, 'spot'))

        elif asset_type == 'future' and self.future_data:
            for key, info in self.future_data.items():
                if self.is_tokenized_stock(info, 'future'):
                    csv_rows.append(self.to_csv_row(info, 'future'))

        return csv_rows

    def _save_to_database(self, csv_rows: List[str], base_path: str = None) -> Dict[str, int]:
        """
        内部方法：增量保存 CSV 到数据库

        Args:
            csv_rows: CSV 格式的记录列表
            base_path: Lean 项目根目录路径（默认自动检测）

        Returns:
            Dict[str, int]: {'added': X, 'skipped': Y}
        """
        if base_path is None:
            # Auto-detect: go up from arbitrage/data_source/ to Lean/
            current_dir = os.path.dirname(os.path.abspath(__file__))
            base_path = os.path.dirname(os.path.dirname(current_dir))

        csv_files = [
            os.path.join(base_path, 'Data', 'symbol-properties', 'symbol-properties-database.csv'),
            os.path.join(base_path, 'Launcher', 'bin', 'Debug', 'symbol-properties', 'symbol-properties-database.csv')
        ]

        results = {'added': 0, 'skipped': 0}

        for csv_file in csv_files:
            if not os.path.exists(csv_file):
                print(f"Warning: CSV file not found: {csv_file}")
                continue

            # Read existing entries
            existing_symbols = set()
            with open(csv_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split(',')
                    if len(parts) >= 2:
                        market = parts[0]
                        symbol = parts[1]
                        # Store (market, symbol) tuple
                        existing_symbols.add((market, symbol))

            # Filter new rows to avoid duplicates
            new_rows = []
            for row in csv_rows:
                parts = row.split(',')
                if len(parts) >= 2:
                    market = parts[0]
                    symbol = parts[1]
                    if (market, symbol) not in existing_symbols:
                        new_rows.append(row)
                        existing_symbols.add((market, symbol))  # Add to set to avoid duplicates within new_rows

            if new_rows:
                # Append new rows to file
                with open(csv_file, 'a', encoding='utf-8') as f:
                    for row in new_rows:
                        f.write(row + '\n')

                # Only count added rows once (from first file)
                if csv_file == csv_files[0]:
                    results['added'] = len(new_rows)
                    results['skipped'] = len(csv_rows) - len(new_rows)

                print(f"[OK] Added {len(new_rows)} symbols to {csv_file}")
            else:
                print(f"[INFO] No new symbols to add to {csv_file} (all already exist)")

        return results

    # ==================== 抽象方法（子类必须实现） ====================

    @abstractmethod
    def fetch_spot_data(self) -> Dict[str, Any]:
        """
        从交易所 API 获取现货交易对数据

        此方法应该：
        1. 调用交易所 API
        2. 获取 tokenized stock 现货数据
        3. 将原始数据存储在 self.spot_data 中

        Returns:
            Dict[str, Any]: 交易所返回的原始数据，存储在 self.spot_data

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        pass

    @abstractmethod
    def fetch_future_data(self) -> Dict[str, Any]:
        """
        从交易所 API 获取期货合约数据

        此方法应该：
        1. 调用交易所 API
        2. 获取 tokenized stock 期货合约数据
        3. 将原始数据存储在 self.future_data 中

        Returns:
            Dict[str, Any]: 交易所返回的原始数据，存储在 self.future_data

        Note:
            如果交易所不支持期货，返回空字典 {}
        """
        pass

    @abstractmethod
    def is_tokenized_stock(self, symbol_info: Dict, asset_type: str) -> bool:
        """
        判断是否为 xStock 或 onStock tokenized asset

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            bool: True 表示是 tokenized stock

        实现示例:
            # Gate 现货
            if asset_type == 'spot':
                base_name = symbol_info.get('base_name', '')
                return 'xStock' in base_name or 'Ondo Tokenized' in base_name

            # Gate 期货
            elif asset_type == 'future':
                name = symbol_info.get('name', '')
                base = name.split('_')[0]
                return base.endswith('X') or base.endswith('ON')
        """
        pass

    @abstractmethod
    def parse_symbol(self, symbol_info: Dict, asset_type: str) -> Tuple[Symbol, Symbol]:
        """
        将交易所数据转换为 LEAN Symbol 交易对

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            Tuple[Symbol, Symbol]: (crypto_symbol, equity_symbol)

        示例:
            现货: (Symbol.Create("AAPLXUSDT", SecurityType.Crypto, "gate"),
                  Symbol.Create("AAPL", SecurityType.Equity, "usa"))

            期货: (Symbol.Create("AAPLXUSDT", SecurityType.CryptoFuture, "gate"),
                  Symbol.Create("AAPL", SecurityType.Equity, "usa"))
        """
        pass

    @abstractmethod
    def to_csv_row(self, symbol_info: Dict, asset_type: str) -> str:
        """
        将交易对信息转换为 CSV 行

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            str: CSV 格式字符串（不含换行符）

        CSV 格式（12 个字段）:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier

        示例:
            现货: "gate,AAPLXUSDT,crypto,Apple xStock,USDT,1,0.01,0.001,AAPLX_USDT,3,,"
            期货: "gate,AAPLXUSDT,cryptofuture,AAPLX Perpetual,USDT,0.001,0.01,1,AAPLX_USDT,,,"
        """
        pass
