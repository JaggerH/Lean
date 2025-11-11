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

    def get_tokenized_stock_pairs(self, asset_type: AssetType = 'all', min_volume_usdt: float = None) -> List[Tuple[Symbol, Symbol]]:
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
            min_volume_usdt: 最小24h成交量(USDT)，默认为None（不筛选）
                - None: 不进行流动性筛选，返回所有tokenized stocks
                - float: 只返回24h成交量 >= min_volume_usdt 的交易对

        Returns:
            List[Tuple[Symbol, Symbol]]: 交易对列表
                - 第一个Symbol: Gate.io crypto symbol (Crypto or CryptoFuture)
                - 第二个Symbol: USA equity symbol (Equity)

        Example:
            >>> manager = GateSymbolManager()
            >>> # 获取所有tokenized stock futures
            >>> pairs = manager.get_tokenized_stock_pairs(asset_type='future')
            >>>
            >>> # 获取流动性 >= 30万 USDT 的tokenized stock futures
            >>> liquid_pairs = manager.get_tokenized_stock_pairs(asset_type='future', min_volume_usdt=300000)
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

        # 流动性筛选（如果指定了 min_volume_usdt）
        if min_volume_usdt is not None:
            pairs = self._filter_pairs_by_volume(pairs, asset_type, min_volume_usdt)

        # 增量同步过滤后的交易对到 CSV（仅在 auto_sync=True 时）
        if pairs and self._auto_sync:
            sync_result = self._sync_filtered_pairs_to_database(pairs, asset_type)
            if sync_result.get('added', 0) > 0:
                print(f"[OK] Incremental sync: Added {sync_result['added']} filtered pairs to CSV")

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
                    if len(parts) >= 3:
                        market = parts[0]
                        symbol = parts[1]
                        type_ = parts[2]
                        # Store (market, symbol, type) tuple as unique key
                        existing_symbols.add((market, symbol, type_))

            # Filter new rows to avoid duplicates
            new_rows = []
            for row in csv_rows:
                parts = row.split(',')
                if len(parts) >= 3:
                    market = parts[0]
                    symbol = parts[1]
                    type_ = parts[2]
                    if (market, symbol, type_) not in existing_symbols:
                        new_rows.append(row)
                        existing_symbols.add((market, symbol, type_))  # Add to set to avoid duplicates within new_rows

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

    def _sync_filtered_pairs_to_database(self, pairs: List[Tuple[Symbol, Symbol]], asset_type: AssetType) -> Dict[str, int]:
        """
        增量同步过滤后的交易对到数据库

        用途：当使用 get_tokenized_stock_pairs 进行流动性筛选后，
              将筛选出的交易对增量写入 CSV（避免重复写入已存在的记录）

        Args:
            pairs: 交易对列表 [(crypto_symbol, equity_symbol), ...]
            asset_type: 'spot', 'future', 或 'all'

        Returns:
            Dict[str, int]: {'added': X, 'skipped': Y}
        """
        if not pairs:
            return {'added': 0, 'skipped': 0}

        # 根据 Symbol 的 SecurityType 将交易对分组
        spot_pairs = []
        future_pairs = []

        for crypto_symbol, equity_symbol in pairs:
            if crypto_symbol.SecurityType == SecurityType.Crypto:
                spot_pairs.append((crypto_symbol, equity_symbol))
            elif crypto_symbol.SecurityType == SecurityType.CryptoFuture:
                future_pairs.append((crypto_symbol, equity_symbol))

        # 将 pairs 转换回原始数据格式以便生成 CSV
        csv_rows = []

        # 处理现货
        if (asset_type in ('spot', 'all')) and spot_pairs and self.spot_data:
            for crypto_symbol, equity_symbol in spot_pairs:
                # 从 spot_data 中找到对应的原始数据
                ticker = crypto_symbol.Value.replace('USDT', '_USDT')
                if ticker in self.spot_data:
                    csv_rows.append(self.to_csv_row(self.spot_data[ticker], 'spot'))

        # 处理期货
        if (asset_type in ('future', 'all')) and future_pairs and self.future_data:
            for crypto_symbol, equity_symbol in future_pairs:
                # 从 future_data 中找到对应的原始数据
                ticker = crypto_symbol.Value.replace('USDT', '_USDT')
                if ticker in self.future_data:
                    csv_rows.append(self.to_csv_row(self.future_data[ticker], 'future'))

        # 调用增量保存方法
        if csv_rows:
            return self._save_to_database(csv_rows)

        return {'added': 0, 'skipped': 0}

    # ==================== 运行时注册方法 ====================

    def register_symbol_properties_runtime(self, algorithm, pairs: List[Tuple[Symbol, Symbol]]) -> int:
        """
        运行时动态注册 symbol properties 到 LEAN 内存数据库

        用途：
            - 支持长时间运行的策略动态添加新交易对
            - 无需重启算法即可订阅新发现的 symbols
            - 配合 CSV 写入形成双保险（CSV用于重启预加载，运行时API用于当前会话）

        Args:
            algorithm: QCAlgorithm 实例（用于访问 symbol_properties_database）
            pairs: 交易对列表 [(crypto_symbol, equity_symbol), ...]

        Returns:
            int: 成功注册的 symbol 数量

        示例:
            >>> manager = GateSymbolManager()
            >>> pairs = manager.get_tokenized_stock_pairs(asset_type='future', min_volume_usdt=300000)
            >>> # 运行时注册（立即生效）
            >>> manager.register_symbol_properties_runtime(self, pairs)
            >>> # 现在可以订阅这些 symbols
            >>> for crypto_symbol, equity_symbol in pairs:
            >>>     self.add_crypto_future(crypto_symbol)
        """
        if not pairs:
            return 0

        registered_count = 0

        for crypto_symbol, equity_symbol in pairs:
            try:
                # 从原始数据中获取 symbol info
                ticker = crypto_symbol.Value.replace('USDT', '_USDT')
                asset_type = 'spot' if crypto_symbol.SecurityType == SecurityType.Crypto else 'future'

                # 获取原始数据
                if asset_type == 'spot' and self.spot_data and ticker in self.spot_data:
                    symbol_info = self.spot_data[ticker]
                elif asset_type == 'future' and self.future_data and ticker in self.future_data:
                    symbol_info = self.future_data[ticker]
                else:
                    print(f"[WARN] Symbol info not found for {crypto_symbol.Value}, skipping runtime registration")
                    continue

                # 创建 SymbolProperties 对象
                symbol_properties = self._create_symbol_properties(symbol_info, asset_type, crypto_symbol)

                # 注册到 LEAN 的 symbol properties database
                algorithm.symbol_properties_database.set_entry(
                    crypto_symbol.ID.Market,      # e.g., "gate"
                    crypto_symbol.Value,           # e.g., "TSLAXUSDT"
                    crypto_symbol.SecurityType,    # SecurityType.Crypto or CryptoFuture
                    symbol_properties
                )

                # 创建并注册 market hours（24/7 for crypto）
                exchange_hours = self._create_exchange_hours()
                algorithm.market_hours_database.set_entry(
                    crypto_symbol.ID.Market,
                    crypto_symbol.Value,
                    crypto_symbol.SecurityType,
                    exchange_hours,
                    TimeZones.Utc  # Crypto exchanges typically use UTC
                )

                registered_count += 1

            except Exception as e:
                print(f"[ERROR] Failed to register {crypto_symbol.Value}: {e}")
                import traceback
                traceback.print_exc()

        if registered_count > 0:
            print(f"[OK] Runtime registered {registered_count} symbols to LEAN database")

        return registered_count

    def _create_symbol_properties(self, symbol_info: Dict, asset_type: str, symbol: Symbol) -> 'SymbolProperties':
        """
        从 symbol info 创建 SymbolProperties 对象

        Args:
            symbol_info: 交易对信息字典（从 spot_data 或 future_data 获取）
            asset_type: 'spot' 或 'future'
            symbol: LEAN Symbol 对象

        Returns:
            SymbolProperties: LEAN 的 SymbolProperties 对象
        """
        if asset_type == 'spot':
            # 现货参数
            description = symbol_info.get('base_name', '')
            quote_currency = symbol_info.get('quote', 'USDT')
            contract_multiplier = 1
            precision = symbol_info.get('precision', 2)
            minimum_price_variation = 10 ** -precision
            lot_size = float(symbol_info.get('min_base_amount', '0.001'))
            market_ticker = symbol_info.get('id', '')
            minimum_order_size = float(symbol_info.get('min_quote_amount', '3'))

        else:  # future
            # 期货参数
            name = symbol_info.get('name', '')
            parts = name.split('_')
            base = parts[0] if len(parts) >= 1 else ''
            description = f"{base} Perpetual"
            quote_currency = parts[1] if len(parts) >= 2 else 'USDT'
            contract_multiplier = float(symbol_info.get('quanto_multiplier', '1'))
            minimum_price_variation = float(symbol_info.get('order_price_round', '0.01'))
            lot_size = float(symbol_info.get('order_size_min', 1))
            market_ticker = name
            minimum_order_size = None  # futures 通常没有 minimum_order_size

        # 创建 SymbolProperties 对象
        return SymbolProperties(
            description,
            quote_currency,
            contract_multiplier,
            minimum_price_variation,
            lot_size,
            market_ticker,
            minimum_order_size
        )

    def _create_exchange_hours(self) -> 'SecurityExchangeHours':
        """
        创建 24/7 交易时间（加密货币市场）

        Returns:
            SecurityExchangeHours: 24/7 交易时间配置
        """
        # 使用 LEAN 内置的 AlwaysOpen 辅助方法创建 24/7 市场时间
        # 这是 LEAN 官方推荐的方式，适用于加密货币等全天候交易市场
        return SecurityExchangeHours.AlwaysOpen(TimeZones.Utc)

    # ==================== 抽象方法（子类必须实现） ====================

    @abstractmethod
    def _filter_pairs_by_volume(
        self,
        pairs: List[Tuple[Symbol, Symbol]],
        asset_type: AssetType,
        min_volume_usdt: float
    ) -> List[Tuple[Symbol, Symbol]]:
        """
        根据24h成交量筛选交易对

        Args:
            pairs: 待筛选的交易对列表
            asset_type: 'spot', 'future', 或 'all'
            min_volume_usdt: 最小24h成交量(USDT)

        Returns:
            List[Tuple[Symbol, Symbol]]: 符合流动性要求的交易对列表

        实现说明:
            子类应该实现此方法来获取ticker数据并进行流动性筛选。
            例如Gate.io应该：
            1. 调用 fetch_spot_tickers() 和/或 fetch_futures_tickers()
            2. 对每个交易对检查24h成交量
            3. 只保留成交量 >= min_volume_usdt 的交易对
        """
        pass

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
