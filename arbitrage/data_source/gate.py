"""
Gate.io exchange data source implementation
Supports both xStock (Backed Finance) and Ondo Tokenized stocks
"""
from __future__ import annotations
import sys
import os

import requests
from typing import List, Tuple, Dict, Any
from AlgorithmImports import *

from .base_data_source import BaseDataSource


class GateSymbolManager(BaseDataSource):
    """
    Gate.io 交易所数据源

    支持：
        - 现货 (SecurityType.Crypto)
        - USDT 永续合约 (SecurityType.CryptoFuture)
        - xStock (Backed Finance) 和 Ondo Tokenized stocks

    使用方式：
        # 自动同步模式（最常用）
        manager = GateSymbolManager()
        pairs = manager.get_pairs(type='future')

        # 只查询不写库
        manager = GateSymbolManager(auto_sync=False)
        pairs = manager.get_pairs(type='spot')

        # 手动刷新
        result = manager.refresh()

    支持的 tokenized stock 提供商:
        1. xStock (Backed Finance) - 后缀 'X', base_name 包含 'xStock'
        2. Ondo Tokenized (Ondo Finance) - 后缀 'ON', base_name 包含 'Ondo Tokenized'
    """

    # Tokenized stock 提供商标识
    TOKENIZED_PROVIDERS = ['xStock', 'Ondo Tokenized']

    # API 端点
    SPOT_API = 'https://api.gateio.ws/api/v4/spot/currency_pairs'
    FUTURES_API = 'https://api.gateio.ws/api/v4/futures/usdt/contracts'

    # Ticker API 端点（24h 成交量数据）
    SPOT_TICKERS_API = 'https://api.gateio.ws/api/v4/spot/tickers'
    FUTURES_TICKERS_API = 'https://api.gateio.ws/api/v4/futures/usdt/tickers'

    def fetch_spot_data(self) -> Dict[str, Any]:
        """
        从 Gate.io API 获取现货交易对数据

        API: GET https://api.gateio.ws/api/v4/spot/currency_pairs

        Returns:
            Dict[str, Any]: {pair_id: pair_info, ...}
                格式: {
                    "AAPLX_USDT": {
                        "id": "AAPLX_USDT",
                        "base": "AAPLX",
                        "base_name": "Apple xStock",
                        "quote": "USDT",
                        "min_base_amount": "0.001",
                        "precision": 2,
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        try:
            response = requests.get(self.SPOT_API, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io spot pairs: {e}")

        all_pairs = response.json()

        if not isinstance(all_pairs, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(all_pairs)}")

        # 转换为字典格式（以 pair_id 为 key）
        self.spot_data = {pair.get('id'): pair for pair in all_pairs if pair.get('id')}

        print(f"[OK] Fetched {len(self.spot_data)} spot pairs from Gate.io")
        return self.spot_data

    def fetch_future_data(self) -> Dict[str, Any]:
        """
        从 Gate.io API 获取 USDT 永续合约数据

        API: GET https://api.gateio.ws/api/v4/futures/usdt/contracts

        Returns:
            Dict[str, Any]: {contract_name: contract_info, ...}
                格式: {
                    "BTC_USDT": {
                        "name": "BTC_USDT",
                        "type": "direct",
                        "quanto_multiplier": "0.0001",
                        "order_size_min": 1,
                        "order_price_round": "0.1",
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        try:
            response = requests.get(self.FUTURES_API, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io futures contracts: {e}")

        all_contracts = response.json()

        if not isinstance(all_contracts, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(all_contracts)}")

        # 转换为字典格式（以 contract name 为 key）
        self.future_data = {contract.get('name'): contract for contract in all_contracts if contract.get('name')}

        print(f"[OK] Fetched {len(self.future_data)} futures contracts from Gate.io")
        return self.future_data

    def is_tokenized_stock(self, symbol_info: Dict, asset_type: str) -> bool:
        """
        判断是否为 xStock 或 onStock tokenized asset

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            bool: True 表示是 tokenized stock

        现货判断逻辑:
            检查 base_name 是否包含 'xStock' 或 'Ondo Tokenized'

        期货判断逻辑:
            1. 确保 spot 数据已加载（懒加载）
            2. 从 spot 数据中提取所有 tokenized stock 的 base 货币集合（缓存）
            3. 检查期货合约的 base 是否在已验证的 tokenized stock 集合中

            这样可以避免误报（如 DYDX_USDT 被误识别为 tokenized stock）
        """
        if asset_type == 'spot':
            # 现货：检查 base_name
            base_name = symbol_info.get('base_name', '')
            return any(provider in base_name for provider in self.TOKENIZED_PROVIDERS)

        elif asset_type == 'future':
            # 期货：验证是否对应实际的 tokenized stock

            # 1. 确保 spot 数据已加载（懒加载）
            if self.spot_data is None:
                self.fetch_spot_data()

            # 2. 构建 tokenized stock 的 base 货币注册表（缓存）
            if not hasattr(self, '_tokenized_bases'):
                self._tokenized_bases = set()
                for pair_id, pair_info in self.spot_data.items():
                    # 递归调用 spot 逻辑检查是否为 tokenized stock
                    if self.is_tokenized_stock(pair_info, 'spot'):
                        base = pair_info.get('base', '')
                        if base:
                            self._tokenized_bases.add(base)

            # 3. 检查期货合约的 base 是否在已验证的集合中
            name = symbol_info.get('name', '')
            if not name:
                return False

            # 解析 base（例如: "AAPLX_USDT" -> "AAPLX"）
            base = name.split('_')[0]
            return base in self._tokenized_bases

        return False

    def parse_symbol(self, symbol_info: Dict, asset_type: str) -> Tuple[Symbol, Symbol]:
        """
        将交易所数据转换为 LEAN Symbol 交易对

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            Tuple[Symbol, Symbol]: (crypto_symbol, equity_symbol)

        现货示例:
            输入: {"id": "AAPLX_USDT", "base": "AAPLX", "quote": "USDT", "base_name": "Apple xStock"}
            输出: (Symbol("AAPLXUSDT", Crypto, gate), Symbol("AAPL", Equity, usa))

        期货示例:
            输入: {"name": "AAPLX_USDT", ...}
            输出: (Symbol("AAPLXUSDT", CryptoFuture, gate), Symbol("AAPL", Equity, usa))
        """
        if asset_type == 'spot':
            # 现货处理
            base = symbol_info.get('base', '')
            quote = symbol_info.get('quote', '')
            base_name = symbol_info.get('base_name', '')

            if not base or not quote:
                raise ValueError(f"Invalid spot data: missing base or quote")

            # 提取股票代码
            stock_ticker = self._extract_stock_ticker(base, base_name)

            if not stock_ticker:
                raise ValueError(f"Failed to extract stock ticker from base={base}, base_name={base_name}")

            # 创建 Symbol（LEAN 格式：无下划线）
            crypto_symbol = Symbol.Create(f"{base}{quote}", SecurityType.Crypto, "gate")
            equity_symbol = Symbol.Create(stock_ticker, SecurityType.Equity, Market.USA)

            return (crypto_symbol, equity_symbol)

        elif asset_type == 'future':
            # 期货处理
            name = symbol_info.get('name', '')

            if not name:
                raise ValueError(f"Invalid future data: missing name")

            # 解析合约名称（格式: "AAPLX_USDT"）
            parts = name.split('_')
            if len(parts) < 2:
                raise ValueError(f"Invalid futures contract name format: {name}")

            base = parts[0]
            quote = parts[1]

            # 提取股票代码
            stock_ticker = self._extract_stock_ticker(base, "")

            if not stock_ticker:
                raise ValueError(f"Failed to extract stock ticker from futures contract: {name}")

            # 创建 Symbol
            crypto_symbol = Symbol.Create(f"{base}{quote}", SecurityType.CryptoFuture, "gate")
            equity_symbol = Symbol.Create(stock_ticker, SecurityType.Equity, Market.USA)

            return (crypto_symbol, equity_symbol)

        else:
            raise ValueError(f"Unsupported asset_type: {asset_type}")

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
        """
        if asset_type == 'spot':
            return self._spot_to_csv(symbol_info)
        elif asset_type == 'future':
            return self._future_to_csv(symbol_info)
        else:
            raise ValueError(f"Unsupported asset_type: {asset_type}")

    def _spot_to_csv(self, pair_data: Dict) -> str:
        """
        现货交易对转 CSV

        示例:
            "gate,AAPLXUSDT,crypto,Apple xStock,USDT,1,0.01,0.001,AAPLX_USDT,3,,"
        """
        # 提取字段
        pair_id = pair_data.get('id', '')
        base = pair_data.get('base', '')
        base_name = pair_data.get('base_name', '')
        quote = pair_data.get('quote', '')
        min_base_amount = pair_data.get('min_base_amount', '0.001')
        min_quote_amount = pair_data.get('min_quote_amount', '3')
        precision = pair_data.get('precision', 2)

        # 映射到 CSV 字段
        market = 'gate'
        symbol = f"{base}{quote}".upper()
        security_type = 'crypto'
        description = base_name
        quote_currency = quote
        contract_multiplier = '1'
        minimum_price_variation = f"{10 ** -precision}"
        lot_size = min_base_amount
        market_ticker = pair_id
        minimum_order_size = min_quote_amount
        price_magnifier = ''
        strike_multiplier = ''

        # 构建 CSV 行
        return ','.join([
            market, symbol, security_type, description, quote_currency,
            contract_multiplier, minimum_price_variation, lot_size,
            market_ticker, minimum_order_size, price_magnifier, strike_multiplier
        ])

    def _future_to_csv(self, contract_data: Dict) -> str:
        """
        期货合约转 CSV

        示例:
            "gate,BTCUSDT,cryptofuture,BTC Perpetual,USDT,0.0001,0.1,1,BTC_USDT,,,"
        """
        # 提取字段
        name = contract_data.get('name', '')
        quanto_multiplier = contract_data.get('quanto_multiplier', '1')
        order_size_min = contract_data.get('order_size_min', 1)
        order_price_round = contract_data.get('order_price_round', '0.01')

        # 解析合约名称
        parts = name.split('_')
        if len(parts) >= 2:
            base = parts[0]
            quote = parts[1]
        else:
            base = name
            quote = 'USDT'

        # 映射到 CSV 字段
        market = 'gate'
        symbol = f"{base}{quote}".upper()
        security_type = 'cryptofuture'
        description = f"{base} Perpetual"
        quote_currency = quote
        contract_multiplier = quanto_multiplier
        minimum_price_variation = order_price_round
        lot_size = str(order_size_min)
        market_ticker = name
        minimum_order_size = ''
        price_magnifier = ''
        strike_multiplier = ''

        # 构建 CSV 行
        return ','.join([
            market, symbol, security_type, description, quote_currency,
            contract_multiplier, minimum_price_variation, lot_size,
            market_ticker, minimum_order_size, price_magnifier, strike_multiplier
        ])

    def _filter_pairs_by_volume(
        self,
        pairs: List[Tuple[Symbol, Symbol]],
        asset_type: str,
        min_volume_usdt: float
    ) -> List[Tuple[Symbol, Symbol]]:
        """
        根据24h成交量筛选tokenized stock交易对

        Args:
            pairs: 待筛选的交易对列表
            asset_type: 'spot', 'future', 或 'all'
            min_volume_usdt: 最小24h成交量(USDT)

        Returns:
            List[Tuple[Symbol, Symbol]]: 符合流动性要求的交易对列表

        流程:
            1. 获取ticker数据（spot和/或future）
            2. 使用 filter_by_volume() 获取合格的合约名称集合
            3. 筛选出符合流动性要求的交易对
        """
        if not pairs:
            return []

        print(f"[INFO] Filtering {len(pairs)} tokenized stock pairs by volume (>= {min_volume_usdt:,.0f} USDT)...")

        # 1. 获取ticker数据
        spot_tickers = None
        futures_tickers = None

        if asset_type in ('spot', 'all'):
            print(f"[INFO] Fetching spot tickers...")
            spot_tickers = self.fetch_spot_tickers()

        if asset_type in ('future', 'all'):
            print(f"[INFO] Fetching futures tickers...")
            futures_tickers = self.fetch_futures_tickers()

        # 2. 获取合格的合约名称集合
        qualified_futures, qualified_spots = self.filter_by_volume(
            min_volume_usdt=min_volume_usdt,
            spot_tickers=spot_tickers,
            futures_tickers=futures_tickers
        )

        # 3. 筛选交易对
        filtered_pairs = []
        skipped_pairs = []

        for crypto_symbol, equity_symbol in pairs:
            # 提取Gate API中的交易对名称（需要加下划线）
            # 例如：TSLAXUSDT -> TSLAX_USDT
            symbol_str = crypto_symbol.Value  # "TSLAXUSDT"
            gate_pair_name = self._symbol_to_gate_pair_name(symbol_str)

            if gate_pair_name is None:
                print(f"     [Warning] Failed to convert symbol to Gate pair name: {symbol_str}")
                continue

            # 根据SecurityType检查是否在合格集合中
            security_type = crypto_symbol.SecurityType
            is_qualified = False

            if security_type == SecurityType.Crypto and gate_pair_name in qualified_spots:
                is_qualified = True
            elif security_type == SecurityType.CryptoFuture and gate_pair_name in qualified_futures:
                is_qualified = True

            if is_qualified:
                filtered_pairs.append((crypto_symbol, equity_symbol))
            else:
                skipped_pairs.append((crypto_symbol, equity_symbol))

        # 4. 输出结果
        print(f"[OK] Volume filtering complete:")
        print(f"     Qualified: {len(filtered_pairs)} / {len(pairs)}")
        print(f"     Filtered out: {len(skipped_pairs)} (low volume)")

        if skipped_pairs and len(skipped_pairs) <= 10:
            print(f"     Low volume pairs: {[s.Value for s, _ in skipped_pairs]}")

        return filtered_pairs

    def _symbol_to_gate_pair_name(self, lean_symbol: str) -> str:
        """
        将LEAN Symbol字符串转换为Gate API中的交易对名称

        Args:
            lean_symbol: LEAN格式的symbol，如 "TSLAXUSDT", "BTCUSDT"

        Returns:
            Gate API格式的交易对名称，如 "TSLAX_USDT", "BTC_USDT"
            如果无法转换则返回None

        逻辑:
            假设所有交易对都是 {BASE}USDT 格式
            转换为 {BASE}_USDT
        """
        if not lean_symbol:
            return None

        # 检查是否以USDT结尾
        if lean_symbol.endswith('USDT'):
            base = lean_symbol[:-4]  # 去掉 "USDT"
            return f"{base}_USDT"

        return None

    def _extract_stock_ticker(self, base: str, base_name: str) -> str:
        """
        从 base currency 中提取股票代码

        Args:
            base: 基础货币，如 "AAPLX", "AAPLON"
            base_name: 完整名称，如 "Apple xStock", "Apple Ondo Tokenized"

        Returns:
            股票代码，如 "AAPL"，如果无法提取则返回空字符串

        逻辑:
            - xStock: 移除后缀 'X' (AAPLX -> AAPL)
            - Ondo: 移除后缀 'ON' (AAPLON -> AAPL)
            - 验证: 1-6 个大写字母
        """
        if not base:
            return ''

        # xStock: ends with 'X'
        if base.endswith('X') and (not base_name or 'xStock' in base_name):
            ticker = base[:-1]
            if ticker and ticker.isalpha() and ticker.isupper() and 1 <= len(ticker) <= 6:
                return ticker

        # Ondo Tokenized: ends with 'ON'
        elif base.endswith('ON') and (not base_name or 'Ondo Tokenized' in base_name):
            ticker = base[:-2]
            if ticker and ticker.isalpha() and ticker.isupper() and 1 <= len(ticker) <= 6:
                return ticker

        return ''

    # ========== 期现套利流动性筛选功能 ==========

    def fetch_spot_tickers(self) -> Dict[str, Dict]:
        """
        获取现货24h ticker数据（包含成交量）

        API: GET https://api.gateio.ws/api/v4/spot/tickers

        Returns:
            Dict[str, Dict]: {currency_pair: ticker_data, ...}
                格式: {
                    "BTC_USDT": {
                        "currency_pair": "BTC_USDT",
                        "quote_volume": "1155568980.102575",  # USDT成交量
                        "base_volume": "11305.507488",
                        "last": "101742.7",
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        try:
            response = requests.get(self.SPOT_TICKERS_API, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io spot tickers: {e}")

        tickers = response.json()

        if not isinstance(tickers, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(tickers)}")

        # 转换为字典格式（以 currency_pair 为 key）
        tickers_dict = {
            ticker.get('currency_pair'): ticker
            for ticker in tickers
            if ticker.get('currency_pair')
        }

        print(f"[OK] Fetched {len(tickers_dict)} spot tickers from Gate.io")
        return tickers_dict

    def fetch_futures_tickers(self) -> Dict[str, Dict]:
        """
        获取期货24h ticker数据（包含成交量）

        API: GET https://api.gateio.ws/api/v4/futures/usdt/tickers

        Returns:
            Dict[str, Dict]: {contract: ticker_data, ...}
                格式: {
                    "BTC_USDT": {
                        "contract": "BTC_USDT",
                        "volume_24h_settle": "14319897",  # USDT成交量
                        "volume_24h": "84976",
                        "last": "101742.7",
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        try:
            response = requests.get(self.FUTURES_TICKERS_API, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io futures tickers: {e}")

        tickers = response.json()

        if not isinstance(tickers, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(tickers)}")

        # 转换为字典格式（以 contract 为 key）
        tickers_dict = {
            ticker.get('contract'): ticker
            for ticker in tickers
            if ticker.get('contract')
        }

        print(f"[OK] Fetched {len(tickers_dict)} futures tickers from Gate.io")
        return tickers_dict

    def filter_by_volume(
        self,
        min_volume_usdt: float = 300000,
        spot_tickers: Dict[str, Dict] = None,
        futures_tickers: Dict[str, Dict] = None
    ) -> Tuple[set, set]:
        """
        根据24h成交量筛选期货和现货

        Args:
            min_volume_usdt: 最小24h成交量(USDT)，默认30万
            spot_tickers: 现货ticker数据（可选，如不提供则自动获取）
            futures_tickers: 期货ticker数据（可选，如不提供则自动获取）

        Returns:
            Tuple[set, set]: (qualified_futures, qualified_spots)
                - qualified_futures: Set[str] - 合格期货合约名称（如 {"BTC_USDT", "ETH_USDT"}）
                - qualified_spots: Set[str] - 合格现货交易对名称（如 {"BTC_USDT", "ETH_USDT"}）

        Example:
            >>> manager = GateSymbolManager()
            >>> futures_set, spots_set = manager.filter_by_volume(min_volume_usdt=500000)
            >>> print(f"Qualified futures: {len(futures_set)}, spots: {len(spots_set)}")
        """
        # 1. 获取 ticker 数据（如果未提供）
        if spot_tickers is None:
            spot_tickers = self.fetch_spot_tickers()

        if futures_tickers is None:
            futures_tickers = self.fetch_futures_tickers()

        # 2. 筛选现货（基于 quote_volume）
        qualified_spots = set()
        for pair_name, ticker in spot_tickers.items():
            try:
                quote_volume = float(ticker.get('quote_volume', 0))
                if quote_volume >= min_volume_usdt:
                    qualified_spots.add(pair_name)
            except (ValueError, TypeError):
                continue

        # 3. 筛选期货（基于 volume_24h_settle）
        qualified_futures = set()
        for contract_name, ticker in futures_tickers.items():
            try:
                volume_settle = float(ticker.get('volume_24h_settle', 0))
                if volume_settle >= min_volume_usdt:
                    qualified_futures.add(contract_name)
            except (ValueError, TypeError):
                continue

        print(f"[OK] Qualified by volume (>= {min_volume_usdt:,.0f} USDT):")
        print(f"     Futures: {len(qualified_futures)} / {len(futures_tickers)}")
        print(f"     Spots:   {len(qualified_spots)} / {len(spot_tickers)}")

        return (qualified_futures, qualified_spots)

    def get_crypto_basis_pairs(
        self,
        min_volume_usdt: float = 300000
    ) -> List[Tuple[Symbol, Symbol]]:
        """
        获取加密货币期现交易对（同市场套利：Gate futures ↔ Gate spot）

        Purpose:
            用于期现套利策略，匹配Gate.io同一基础资产的期货和现货
            支持基于24h成交量的流动性筛选

        流程：
        1. 获取期货和现货 ticker 数据
        2. 筛选成交量 >= min_volume_usdt 的标的
        3. Pair matching: 找到基础资产相同的期货和现货
           例如：BTC_USDT (futures) ↔ BTC_USDT (spot)
        4. 返回 (futures_symbol, spot_symbol) 列表

        Args:
            min_volume_usdt: 最小24h成交量(USDT)，默认30万

        Returns:
            List[Tuple[Symbol, Symbol]]: 交易对列表
                - 第一个Symbol: Gate.io crypto future
                - 第二个Symbol: Gate.io crypto spot (同一资产)

        Example:
            >>> manager = GateSymbolManager()
            >>> pairs = manager.get_crypto_basis_pairs(min_volume_usdt=500000)
            >>> # [(Symbol("BTCUSDT", CryptoFuture, gate), Symbol("BTCUSDT", Crypto, gate)), ...]

            >>> for futures_sym, spot_sym in pairs:
            >>>     print(f"Basis: {futures_sym.Value} futures ↔ {spot_sym.Value} spot")
        """
        # 1. 获取 ticker 数据
        print(f"[1/4] Fetching ticker data...")
        spot_tickers = self.fetch_spot_tickers()
        futures_tickers = self.fetch_futures_tickers()

        # 2. 流动性筛选
        print(f"[2/4] Filtering by volume...")
        qualified_futures, qualified_spots = self.filter_by_volume(
            min_volume_usdt=min_volume_usdt,
            spot_tickers=spot_tickers,
            futures_tickers=futures_tickers
        )

        # 3. Pair matching（找交集）
        print(f"[3/4] Matching spot-futures pairs...")
        matched_pairs = []

        # 找到期货和现货都存在且成交量合格的交易对
        common_pairs = qualified_futures.intersection(qualified_spots)

        for pair_name in common_pairs:
            try:
                # 创建 LEAN Symbol（去掉下划线）
                # 例如：BTC_USDT -> BTCUSDT
                lean_symbol_str = pair_name.replace('_', '').upper()

                # 创建期货和现货 Symbol
                # Note: Market.Gate is defined as "gate" (lowercase) in Market.cs
                # Use string directly as Python.NET doesn't expose Market.Gate attribute
                futures_symbol = Symbol.Create(lean_symbol_str, SecurityType.CryptoFuture, "gate")
                spot_symbol = Symbol.Create(lean_symbol_str, SecurityType.Crypto, "gate")

                matched_pairs.append((futures_symbol, spot_symbol))

            except Exception as e:
                print(f"     [Warning] Failed to create symbols for {pair_name}: {e}")
                continue

        # 4. 输出结果
        print(f"[4/4] Matching complete!")
        print(f"[OK] Matched {len(matched_pairs)} spot-futures pairs")
        print(f"     (Both futures and spot have >= {min_volume_usdt:,.0f} USDT 24h volume)")

        return matched_pairs

    def sync_to_database(
        self,
        pairs: List[Tuple[Symbol, Symbol]],
        database_path: str = None
    ):
        """
        将期现交易对写入 symbol CSV（避免重复）

        Args:
            pairs: 交易对列表，格式：[(futures_symbol, spot_symbol), ...]
            database_path: symbol-properties-database.csv 路径
                默认值：../../../Data/symbol-properties/symbol-properties-database.csv

        Example:
            >>> manager = GateSymbolManager()
            >>> pairs = manager.get_crypto_basis_pairs(min_volume_usdt=300000)
            >>> manager.sync_to_database(pairs)
            [OK] Synced 150 pairs to database (50 new, 100 existing)
        """
        import os
        from pathlib import Path

        # 1. 确定数据库路径
        if database_path is None:
            # 默认路径（相对于arbitrage目录）
            script_dir = os.path.dirname(os.path.abspath(__file__))
            database_path = os.path.join(script_dir, "../../../Data/symbol-properties/symbol-properties-database.csv")
            database_path = os.path.normpath(database_path)

        print(f"[1/3] Loading database: {database_path}")

        # 2. 读取现有数据库
        existing_entries = set()
        try:
            with open(database_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        existing_entries.add(line)
        except FileNotFoundError:
            print(f"     [Warning] Database file not found, will create new file")

        # 3. 获取合约元数据（用于生成CSV行）
        print(f"[2/3] Fetching contract metadata...")
        spot_data = self.fetch_spot_data()
        future_data = self.fetch_future_data()

        # 4. 生成CSV行并检查重复
        new_entries = []
        skipped_count = 0

        for futures_symbol, spot_symbol in pairs:
            # 提取交易对名称（例如：BTCUSDT -> BTC_USDT）
            symbol_str = futures_symbol.Value  # "BTCUSDT"
            gate_pair_name = self._symbol_to_gate_pair_name(symbol_str)

            if gate_pair_name is None:
                print(f"     [Warning] Skipping unsupported symbol format: {symbol_str}")
                continue

            # 4.1 处理期货合约
            if gate_pair_name in future_data:
                try:
                    csv_line = self.to_csv_row(future_data[gate_pair_name], 'future')
                    if csv_line not in existing_entries:
                        new_entries.append(csv_line)
                    else:
                        skipped_count += 1
                except Exception as e:
                    print(f"     [Warning] Failed to generate CSV for futures {gate_pair_name}: {e}")

            # 4.2 处理现货
            if gate_pair_name in spot_data:
                try:
                    csv_line = self.to_csv_row(spot_data[gate_pair_name], 'spot')
                    if csv_line not in existing_entries:
                        new_entries.append(csv_line)
                    else:
                        skipped_count += 1
                except Exception as e:
                    print(f"     [Warning] Failed to generate CSV for spot {gate_pair_name}: {e}")

        # 5. 写入数据库
        print(f"[3/3] Writing to database...")
        if new_entries:
            try:
                with open(database_path, 'a', encoding='utf-8') as f:
                    for entry in new_entries:
                        f.write(entry + '\n')

                print(f"[OK] Synced {len(pairs)} pairs to database:")
                print(f"     New entries: {len(new_entries)}")
                print(f"     Already existed: {skipped_count}")
            except Exception as e:
                print(f"[Error] Failed to write to database: {e}")
        else:
            print(f"[OK] All {len(pairs)} pairs already exist in database")
