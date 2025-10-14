"""
Base data source abstraction for crypto exchange integration
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any
import sys
import os


from AlgorithmImports import *

class BaseDataSource(ABC):
    """
    BaseDataSource是一个抽象接口，用于从虚拟货币交易所获取可交易对信息，
    并根据需要的功能实现对应转换

    这个抽象类定义了所有数据源必须实现的核心接口，用于：
    1. 从交易所API获取tokenized stock交易对
    2. 将交易所格式转换为LEAN符号格式
    3. 生成LEAN数据库所需的记录格式
    """

    def __init__(self, auto_sync: bool = True):
        """
        初始化数据源并可选地自动同步到数据库

        Args:
            auto_sync: 是否自动同步symbol到数据库(默认True)
        """
        self.source = None  # 用于记录从交易所获得的可交易对的raw data
        self.sync_results = None  # 存储同步结果

        # 自动执行同步流程
        if auto_sync:
            try:
                print(f"[INFO] Starting auto-sync for {self.__class__.__name__}...")

                # 1. 获取交易所数据
                self.get_tokenize_stocks()
                print(f"[OK] Fetched {len(self.source) if self.source else 0} tokenized stocks")

                # 2. 生成CSV记录
                csv_rows = self.get_records_to_database()
                print(f"[OK] Generated {len(csv_rows)} CSV records")

                # 3. 同步到数据库
                self.sync_results = self.sync_to_database(csv_rows)
                print(f"[OK] Sync complete: Added {self.sync_results['added']}, Skipped {self.sync_results['skipped']}")

            except Exception as e:
                print(f"[WARN] Auto-sync failed: {e}")
                print(f"   You can still use the data source, but database may not be updated")
                import traceback
                traceback.print_exc()

    @abstractmethod
    def get_tokenize_stocks(self):
        """
        访问交易所API获取用于套利的交易对基础信息

        此方法应该：
        1. 调用交易所API
        2. 获取tokenized stock交易对数据
        3. 将原始数据存储在self.source中

        Returns:
            Dict[str, Any]: 交易所返回的原始交易对数据

        Raises:
            requests.RequestException: 如果API请求失败
            ValueError: 如果交易所API返回错误
        """
        pass

    @abstractmethod
    def get_trade_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        将交易所获得的交易对信息转换成LEAN Crypto Symbol和Equity Symbol

        此方法应该：
        1. 从self.source中读取原始交易对数据
        2. 解析每个交易对，提取crypto symbol和对应的stock symbol
        3. 使用Symbol.Create()创建LEAN Symbol对象
        4. 返回(crypto_symbol, equity_symbol)元组列表

        Returns:
            List[Tuple[Symbol, Symbol]]: [(CryptoSymbol, EquitySymbol), ...]
            例如: [
                (Symbol.Create("AAPLUSD", SecurityType.Crypto, Market.Kraken),
                 Symbol.Create("AAPL", SecurityType.Equity, Market.USA)),
                (Symbol.Create("TSLAUSD", SecurityType.Crypto, Market.Kraken),
                 Symbol.Create("TSLA", SecurityType.Equity, Market.USA))
            ]

        Note:
            - 返回的是LEAN Symbol对象（不是Security对象，也不是字符串）
            - 使用 algorithm.add_security(symbol) 可以将Symbol转换为Security并订阅行情
            - crypto_symbol: SecurityType.Crypto + 对应交易所的market
            - equity_symbol: SecurityType.Equity + Market.USA
        """
        pass

    @abstractmethod
    def get_records_to_database(self) -> List[str]:
        """
        将可交易symbol转换成LEAN Database需要的格式

        此方法应该：
        1. 从self.source中读取原始交易对数据
        2. 将每个交易对转换为符合symbol-properties-database.csv格式的CSV行
        3. 返回CSV行字符串列表

        Returns:
            List[str]: CSV格式的记录列表

        CSV格式:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier

        Example:
            ["kraken,AAPLUSD,crypto,AAPLx/USD,USD,1,0.01,0.00000001,AAPLxUSD,0.5,,"]
        """
        pass

    def sync_to_database(self, csv_rows: List[str], base_path: str = None) -> Dict[str, int]:
        """
        增量同步symbol记录到LEAN的symbol-properties-database.csv

        此方法将:
        1. 读取现有数据库文件
        2. 检查重复的(market, symbol)对
        3. 只添加新记录,跳过已存在的
        4. 更新两个数据库文件

        Args:
            csv_rows: CSV格式的记录列表(来自get_records_to_database())
            base_path: Lean项目根目录路径(默认自动检测)

        Returns:
            Dict[str, int]: {'added': 添加数量, 'skipped': 跳过数量}

        Raises:
            FileNotFoundError: 如果数据库文件不存在
            IOError: 如果文件读写失败
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
