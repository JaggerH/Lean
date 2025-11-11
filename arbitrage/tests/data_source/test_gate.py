"""
Unit tests for GateSymbolManager (New API)
"""
import unittest
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import AlgorithmImports (available via PythonTestRunner)
from AlgorithmImports import Market, Symbol, SecurityType

from data_source.gate import GateSymbolManager


class TestGateSymbolManager(unittest.TestCase):
    """Test GateSymbolManager class with new API"""

    def setUp(self):
        """Set up test fixtures"""
        # Initialize without auto_sync to avoid database operations in tests
        self.manager = GateSymbolManager(auto_sync=False)

    def test_initialization(self):
        """Test that manager initializes correctly"""
        self.assertIsNone(self.manager.spot_data)
        self.assertIsNone(self.manager.future_data)

    def test_fetch_spot_data(self):
        """Test fetching spot data from Gate.io API"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.fetch_spot_data()")
        print("="*80)

        spot_data = self.manager.fetch_spot_data()

        # Verify response structure
        self.assertIsInstance(spot_data, dict)
        self.assertIsNotNone(self.manager.spot_data)
        self.assertGreater(len(spot_data), 0)

        # Count tokenized stocks
        tokenized = {k: v for k, v in spot_data.items()
                    if 'xStock' in v.get('base_name', '') or 'Ondo Tokenized' in v.get('base_name', '')}

        print(f"\n✓ Fetched {len(spot_data)} total spot pairs")
        print(f"✓ Found {len(tokenized)} tokenized stock pairs")

        # Show breakdown
        xstock_count = sum(1 for v in tokenized.values() if 'xStock' in v.get('base_name', ''))
        ondo_count = sum(1 for v in tokenized.values() if 'Ondo Tokenized' in v.get('base_name', ''))

        print(f"\nBreakdown:")
        print(f"  - xStock: {xstock_count}")
        print(f"  - Ondo: {ondo_count}")

        print("="*80)

    def test_fetch_future_data(self):
        """Test fetching futures data from Gate.io API"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.fetch_future_data()")
        print("="*80)

        future_data = self.manager.fetch_future_data()

        # Verify response structure
        self.assertIsInstance(future_data, dict)
        self.assertIsNotNone(self.manager.future_data)
        self.assertGreater(len(future_data), 0)

        print(f"\n✓ Fetched {len(future_data)} futures contracts")
        print("="*80)

    def test_get_pairs_spot(self):
        """Test get_tokenized_stock_pairs(asset_type='spot')"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_tokenized_stock_pairs(asset_type='spot')")
        print("="*80)

        # Get spot pairs (懒加载：自动获取数据)
        spot_pairs = self.manager.get_tokenized_stock_pairs(asset_type='spot')

        # Verify structure
        self.assertIsInstance(spot_pairs, list)
        self.assertGreater(len(spot_pairs), 0)

        print(f"\n✓ Found {len(spot_pairs)} spot trading pairs")
        print("\nFirst 5 pairs:")
        for i, (crypto_symbol, equity_symbol) in enumerate(spot_pairs[:5]):
            print(f"  {i+1}. {str(crypto_symbol.Value):20s} <-> {str(equity_symbol.Value)}")

        print("="*80)

    def test_get_pairs_future(self):
        """Test get_tokenized_stock_pairs(asset_type='future')"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_tokenized_stock_pairs(asset_type='future')")
        print("="*80)

        # Get future pairs (懒加载：自动获取数据)
        future_pairs = self.manager.get_tokenized_stock_pairs(asset_type='future')

        # Verify structure
        self.assertIsInstance(future_pairs, list)
        self.assertGreater(len(future_pairs), 0)

        print(f"\n✓ Found {len(future_pairs)} future trading pairs")
        print("\nFirst 5 pairs:")
        for i, (crypto_symbol, equity_symbol) in enumerate(future_pairs[:5]):
            print(f"  {i+1}. {str(crypto_symbol.Value):20s} <-> {str(equity_symbol.Value)}")

        print("="*80)

    def test_get_pairs_all(self):
        """Test get_tokenized_stock_pairs(asset_type='all')"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_tokenized_stock_pairs(asset_type='all')")
        print("="*80)

        # Clear data to test fresh fetch
        manager = GateSymbolManager(auto_sync=False)

        # Get all pairs
        all_pairs = manager.get_tokenized_stock_pairs(asset_type='all')

        # Also get spot and future separately for comparison
        spot_pairs = manager.get_tokenized_stock_pairs(asset_type='spot')
        future_pairs = manager.get_tokenized_stock_pairs(asset_type='future')

        # Verify counts
        self.assertEqual(len(all_pairs), len(spot_pairs) + len(future_pairs),
                        "All pairs should equal spot + future")

        print(f"\n✓ Total pairs: {len(all_pairs)}")
        print(f"  - Spot: {len(spot_pairs)}")
        print(f"  - Future: {len(future_pairs)}")

        print("="*80)

    def test_lazy_loading(self):
        """Test lazy loading mechanism"""
        print("\n" + "="*80)
        print("Testing lazy loading mechanism")
        print("="*80)

        manager = GateSymbolManager(auto_sync=False)

        # Initially, data should be None
        self.assertIsNone(manager.spot_data)
        self.assertIsNone(manager.future_data)

        print("\n1. Initial state: data is None")

        # First call triggers fetch
        spot_pairs = manager.get_tokenized_stock_pairs(asset_type='spot')
        self.assertIsNotNone(manager.spot_data)
        self.assertIsNone(manager.future_data)  # Future data not fetched yet

        print("2. After get_tokenized_stock_pairs(asset_type='spot'): spot_data fetched, future_data still None")

        # Second call for future triggers future fetch
        future_pairs = manager.get_tokenized_stock_pairs(asset_type='future')
        self.assertIsNotNone(manager.spot_data)
        self.assertIsNotNone(manager.future_data)

        print("3. After get_tokenized_stock_pairs(asset_type='future'): both data fetched")
        print("\n✓ Lazy loading works correctly")
        print("="*80)

    def test_extract_stock_ticker(self):
        """Test stock ticker extraction logic"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager._extract_stock_ticker()")
        print("="*80)

        manager = GateSymbolManager(auto_sync=False)

        test_cases = [
            # (base, base_name, expected_ticker)
            ('AAPLX', 'Apple xStock', 'AAPL'),
            ('TSLAX', 'Tesla xStock', 'TSLA'),
            ('NVDAX', 'NVIDIA xStock', 'NVDA'),
            ('AAPLON', 'Apple Ondo Tokenized', 'AAPL'),
            ('TSLAON', 'Tesla Ondo Tokenized', 'TSLA'),
            ('NVDAON', 'NVIDIA Ondo Tokenized', 'NVDA'),
            ('MSFTON', 'Microsoft Ondo Tokenized', 'MSFT'),
            ('MAX', 'Mastercard xStock', 'MA'),
            ('SPYX', 'SP500 xStock', 'SPY'),
            ('QQQX', 'Nasdaq xStock', 'QQQ'),
            ('', '', ''),  # Empty case
            ('INVALID', 'Some Token', ''),  # Non-stock case
        ]

        print("\nTest cases:")
        for base, base_name, expected in test_cases:
            result = manager._extract_stock_ticker(base, base_name)
            status = '✓' if result == expected else '✗'
            print(f"  {status} {base:15s} | {base_name:35s} -> {result:6s} (expected: {expected})")
            self.assertEqual(result, expected, f"Failed for {base}")

        print("\n✓ All test cases passed")
        print("="*80)

    def test_provider_detection(self):
        """Test detection of xStock and Ondo Tokenized stocks"""
        print("\n" + "="*80)
        print("Testing provider detection")
        print("="*80)

        # Fetch spot data
        self.manager.fetch_spot_data()

        # Filter tokenized stocks
        xstocks = {k: v for k, v in self.manager.spot_data.items()
                  if 'xStock' in v.get('base_name', '')}
        ondo_stocks = {k: v for k, v in self.manager.spot_data.items()
                      if 'Ondo Tokenized' in v.get('base_name', '')}

        print(f"\nxStock pairs: {len(xstocks)}")
        print(f"Ondo pairs: {len(ondo_stocks)}")

        self.assertGreater(len(xstocks), 0, "Should find xStock pairs")
        self.assertGreater(len(ondo_stocks), 0, "Should find Ondo pairs")

        # Show examples
        print("\nExample xStocks:")
        for pair_id in list(xstocks.keys())[:3]:
            print(f"  {pair_id}: {xstocks[pair_id].get('base_name')}")

        print("\nExample Ondo stocks:")
        for pair_id in list(ondo_stocks.keys())[:3]:
            print(f"  {pair_id}: {ondo_stocks[pair_id].get('base_name')}")

        print("\n✓ Both providers detected")
        print("="*80)

    def test_is_tokenized_stock_spot(self):
        """Test is_tokenized_stock for spot assets"""
        print("\n" + "="*80)
        print("Testing is_tokenized_stock for spot")
        print("="*80)

        # Fetch spot data
        self.manager.fetch_spot_data()

        # Test cases
        test_cases = [
            # (pair_id, expected_result, description)
            ('AAPLX_USDT', True, 'Apple xStock should be tokenized'),
            ('TSLAON_USDT', True, 'Tesla Ondo should be tokenized'),
            ('BTC_USDT', False, 'Bitcoin should NOT be tokenized'),
            ('ETH_USDT', False, 'Ethereum should NOT be tokenized'),
        ]

        print("\nTest cases:")
        for pair_id, expected, description in test_cases:
            if pair_id in self.manager.spot_data:
                result = self.manager.is_tokenized_stock(
                    self.manager.spot_data[pair_id], 'spot'
                )
                status = '✓' if result == expected else '✗'
                print(f"  {status} {pair_id:20s} -> {result:5} (expected: {expected}) - {description}")
                self.assertEqual(result, expected, f"Failed for {pair_id}")
            else:
                print(f"  ⊘ {pair_id:20s} -> N/A (pair not found)")

        print("\n✓ Spot tokenized stock detection working correctly")
        print("="*80)

    def test_is_tokenized_stock_futures(self):
        """Test is_tokenized_stock for futures (the fixed logic)"""
        print("\n" + "="*80)
        print("Testing is_tokenized_stock for futures (FIXED LOGIC)")
        print("="*80)

        # Fetch both spot and futures data
        self.manager.fetch_spot_data()
        self.manager.fetch_future_data()

        # First, identify tokenized stocks from spot
        tokenized_bases = set()
        for pair_id, pair_info in self.manager.spot_data.items():
            if self.manager.is_tokenized_stock(pair_info, 'spot'):
                base = pair_info.get('base', '')
                if base:
                    tokenized_bases.add(base)

        print(f"\nFound {len(tokenized_bases)} tokenized stock bases in spot market")
        print(f"Examples: {list(tokenized_bases)[:5]}")

        # Test futures detection
        tokenized_futures = []
        non_tokenized_futures = []

        for contract_name, contract_info in self.manager.future_data.items():
            is_tokenized = self.manager.is_tokenized_stock(contract_info, 'future')
            base = contract_name.split('_')[0]

            if is_tokenized:
                tokenized_futures.append(contract_name)
                # Verify: must have corresponding spot tokenized stock
                self.assertIn(base, tokenized_bases,
                            f"{contract_name} identified as tokenized but no spot match")
            else:
                non_tokenized_futures.append(contract_name)

        print(f"\n✓ Found {len(tokenized_futures)} tokenized futures")
        print(f"✓ Found {len(non_tokenized_futures)} non-tokenized futures")

        # Show examples
        if tokenized_futures:
            print(f"\nExample tokenized futures:")
            for contract in tokenized_futures[:5]:
                print(f"  - {contract}")

        # Critical test: Verify no false positives
        # Any futures ending with X or ON but NOT in tokenized_bases should NOT be detected
        false_positive_candidates = []
        for contract_name in self.manager.future_data.keys():
            base = contract_name.split('_')[0]
            if (base.endswith('X') or base.endswith('ON')) and base not in tokenized_bases:
                false_positive_candidates.append(contract_name)
                # These should NOT be detected as tokenized
                result = self.manager.is_tokenized_stock(
                    self.manager.future_data[contract_name], 'future'
                )
                self.assertFalse(result,
                    f"{contract_name} should NOT be tokenized (no spot match)")

        if false_positive_candidates:
            print(f"\n✓ Correctly rejected {len(false_positive_candidates)} false positive candidates:")
            for contract in false_positive_candidates[:5]:
                print(f"  - {contract} (ends with X/ON but not a tokenized stock)")

        print("\n✓ Futures tokenized stock detection working correctly")
        print("✓ No false positives detected")
        print("="*80)

    def test_complete_workflow(self):
        """Test complete workflow: initialization -> fetch -> get pairs"""
        print("\n" + "="*80)
        print("Testing complete workflow")
        print("="*80)

        # Create fresh manager
        manager = GateSymbolManager(auto_sync=False)

        print("\n1. Getting spot pairs (auto-fetches data)...")
        spot_pairs = manager.get_tokenized_stock_pairs(asset_type='spot')
        self.assertGreater(len(spot_pairs), 0)
        print(f"   ✓ Got {len(spot_pairs)} spot pairs")

        print("\n2. Getting future pairs (auto-fetches data)...")
        future_pairs = manager.get_tokenized_stock_pairs(asset_type='future')
        self.assertGreater(len(future_pairs), 0)
        print(f"   ✓ Got {len(future_pairs)} future pairs")

        print("\n3. Getting all pairs (uses cached data)...")
        all_pairs = manager.get_tokenized_stock_pairs(asset_type='all')
        self.assertEqual(len(all_pairs), len(spot_pairs) + len(future_pairs))
        print(f"   ✓ Got {len(all_pairs)} total pairs")

        print("\n✓ Complete workflow successful")
        print("="*80)


class TestGateSpotFuturesLiquidity(unittest.TestCase):
    """Test spot-futures liquidity filtering functionality (期现套利流动性筛选)"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        # Register Gate market (ID: 42) for testing
        try:
            Market.Add("gate", 42)
        except:
            pass  # May already be registered

        cls.manager = GateSymbolManager(auto_sync=False)
        print("\n" + "=" * 80)
        print("Testing Spot-Futures Liquidity Filtering (期现套利流动性筛选)")
        print("=" * 80)

    def test_fetch_spot_tickers(self):
        """Test fetching spot tickers with volume data"""
        print("\n[1/5] Testing fetch_spot_tickers()...")

        tickers = self.manager.fetch_spot_tickers()

        # Assertions
        self.assertIsInstance(tickers, dict)
        self.assertGreater(len(tickers), 0, "Should fetch at least some tickers")

        # Check structure
        sample_ticker = next(iter(tickers.values()))
        self.assertIn('currency_pair', sample_ticker)
        self.assertIn('quote_volume', sample_ticker)

        print(f"✓ Fetched {len(tickers)} spot tickers with volume data")

    def test_fetch_futures_tickers(self):
        """Test fetching futures tickers with volume data"""
        print("\n[2/5] Testing fetch_futures_tickers()...")

        tickers = self.manager.fetch_futures_tickers()

        # Assertions
        self.assertIsInstance(tickers, dict)
        self.assertGreater(len(tickers), 0, "Should fetch at least some tickers")

        # Check structure
        sample_ticker = next(iter(tickers.values()))
        self.assertIn('contract', sample_ticker)
        self.assertIn('volume_24h_settle', sample_ticker)

        print(f"✓ Fetched {len(tickers)} futures tickers with volume data")

    def test_filter_by_volume(self):
        """Test volume filtering with different thresholds"""
        print("\n[3/5] Testing filter_by_volume()...")

        # Test with 300k threshold
        qualified_futures, qualified_spots = self.manager.filter_by_volume(
            min_volume_usdt=300000
        )

        # Assertions
        self.assertIsInstance(qualified_futures, set)
        self.assertIsInstance(qualified_spots, set)
        self.assertGreater(len(qualified_futures), 0)
        self.assertGreater(len(qualified_spots), 0)

        print(f"✓ Qualified futures: {len(qualified_futures)}, spots: {len(qualified_spots)}")

        # Test with higher threshold
        qualified_futures_1m, qualified_spots_1m = self.manager.filter_by_volume(
            min_volume_usdt=1000000
        )

        # Higher threshold should yield fewer or equal results
        self.assertLessEqual(len(qualified_futures_1m), len(qualified_futures))
        self.assertLessEqual(len(qualified_spots_1m), len(qualified_spots))

        print(f"✓ With 1M threshold: futures: {len(qualified_futures_1m)}, spots: {len(qualified_spots_1m)}")

    def test_match_spot_futures_pairs(self):
        """Test spot-futures pair matching"""
        print("\n[4/5] Testing get_crypto_basis_pairs()...")

        pairs = self.manager.get_crypto_basis_pairs(min_volume_usdt=300000)

        # Assertions
        self.assertIsInstance(pairs, list)
        self.assertGreater(len(pairs), 0, "Should have at least some matched pairs")

        # Check pair structure
        futures_symbol, spot_symbol = pairs[0]
        self.assertIsNotNone(futures_symbol)
        self.assertIsNotNone(spot_symbol)
        self.assertEqual(futures_symbol.Value, spot_symbol.Value,
                        "Futures and spot should have the same symbol name")

        print(f"✓ Matched {len(pairs)} spot-futures pairs")
        print(f"\nTop 5 pairs:")
        for i, (futures_sym, spot_sym) in enumerate(pairs[:5], 1):
            print(f"  {i}. {futures_sym.Value}")

        # Store for database test
        self.__class__.matched_pairs = pairs

    def test_pair_matching_statistics(self):
        """Test and display pair matching statistics"""
        print("\n[5/5] Pair matching statistics...")

        # Test different thresholds
        thresholds = [100000, 300000, 500000, 1000000]
        results = []

        # Get tickers once
        spot_tickers = self.manager.fetch_spot_tickers()
        futures_tickers = self.manager.fetch_futures_tickers()

        for threshold in thresholds:
            qualified_futures, qualified_spots = self.manager.filter_by_volume(
                min_volume_usdt=threshold,
                spot_tickers=spot_tickers,
                futures_tickers=futures_tickers
            )
            matched = qualified_futures.intersection(qualified_spots)
            results.append({
                'threshold': threshold,
                'futures': len(qualified_futures),
                'spots': len(qualified_spots),
                'matched': len(matched)
            })

        # Display results
        print(f"\n{'Threshold (USDT)':<20} {'Futures':<10} {'Spots':<10} {'Matched':<10}")
        print("-" * 50)
        for r in results:
            print(f"{r['threshold']:>18,}  {r['futures']:<10} {r['spots']:<10} {r['matched']:<10}")

        print(f"\nTotal futures: {len(futures_tickers)}")
        print(f"Total spots: {len(spot_tickers)}")
        print("✓ Statistics generated successfully")


class TestNewAPIDesign(unittest.TestCase):
    """Test the new API design with clearer method names"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        # Register Gate market for testing
        try:
            Market.Add("gate", 42)
        except:
            pass

        cls.manager = GateSymbolManager(auto_sync=False)
        print("\n" + "=" * 80)
        print("Testing New API Design (方法命名优化)")
        print("=" * 80)

    def test_get_tokenized_stock_pairs(self):
        """Test new get_tokenized_stock_pairs() method"""
        print("\n[1/3] Testing get_tokenized_stock_pairs()...")

        # Test with different asset types
        future_pairs = self.manager.get_tokenized_stock_pairs(asset_type='future')
        spot_pairs = self.manager.get_tokenized_stock_pairs(asset_type='spot')
        all_pairs = self.manager.get_tokenized_stock_pairs(asset_type='all')

        # Assertions
        self.assertIsInstance(future_pairs, list)
        self.assertIsInstance(spot_pairs, list)
        self.assertIsInstance(all_pairs, list)

        # All should equal future + spot
        self.assertEqual(len(all_pairs), len(future_pairs) + len(spot_pairs))

        # Check pair structure: (gate_crypto, usa_equity)
        if future_pairs:
            crypto_sym, equity_sym = future_pairs[0]
            self.assertEqual(crypto_sym.SecurityType, SecurityType.CryptoFuture)
            self.assertEqual(equity_sym.SecurityType, SecurityType.Equity)
            self.assertNotEqual(crypto_sym.ID.Market, equity_sym.ID.Market)  # Cross-market

        print(f"✓ Future pairs: {len(future_pairs)}")
        print(f"✓ Spot pairs: {len(spot_pairs)}")
        print(f"✓ All pairs: {len(all_pairs)}")
        print(f"✓ Verified cross-market structure (Gate ↔ USA)")

    def test_get_crypto_basis_pairs(self):
        """Test new get_crypto_basis_pairs() method"""
        print("\n[2/3] Testing get_crypto_basis_pairs()...")

        # Test with different thresholds
        pairs_300k = self.manager.get_crypto_basis_pairs(min_volume_usdt=300000)
        pairs_1m = self.manager.get_crypto_basis_pairs(min_volume_usdt=1000000)

        # Assertions
        self.assertIsInstance(pairs_300k, list)
        self.assertIsInstance(pairs_1m, list)
        self.assertGreater(len(pairs_300k), 0)

        # Higher threshold should yield fewer pairs
        self.assertLessEqual(len(pairs_1m), len(pairs_300k))

        # Check pair structure: (gate_futures, gate_spot)
        if pairs_300k:
            futures_sym, spot_sym = pairs_300k[0]
            self.assertEqual(futures_sym.SecurityType, SecurityType.CryptoFuture)
            self.assertEqual(spot_sym.SecurityType, SecurityType.Crypto)
            self.assertEqual(futures_sym.ID.Market, spot_sym.ID.Market)  # Same market
            self.assertEqual(futures_sym.Value, spot_sym.Value)  # Same asset

        print(f"✓ Pairs (300k threshold): {len(pairs_300k)}")
        print(f"✓ Pairs (1M threshold): {len(pairs_1m)}")
        print(f"✓ Verified intra-market structure (Gate futures ↔ Gate spot)")

    def test_volume_filtering_consistency(self):
        """Test volume filtering consistency across asset types (tokenized stocks)"""
        print("\n[3/3] Testing volume filtering consistency for tokenized stocks...")

        # Test with multiple thresholds
        thresholds = [300000, 500000, 1000000]

        print(f"\n{'Threshold':<15} {'Futures':<10} {'Spots':<10} {'All':<10} {'Match':<10}")
        print("-" * 55)

        for threshold in thresholds:
            # 1. Get futures with volume filtering
            future_pairs_filtered = self.manager.get_tokenized_stock_pairs(
                asset_type='future',
                min_volume_usdt=threshold
            )

            # 2. Get spots with volume filtering
            spot_pairs_filtered = self.manager.get_tokenized_stock_pairs(
                asset_type='spot',
                min_volume_usdt=threshold
            )

            # 3. Get all with volume filtering
            all_pairs_filtered = self.manager.get_tokenized_stock_pairs(
                asset_type='all',
                min_volume_usdt=threshold
            )

            # 4. Verify consistency: all = futures + spots
            expected_count = len(future_pairs_filtered) + len(spot_pairs_filtered)
            actual_count = len(all_pairs_filtered)

            match_status = "✓" if actual_count == expected_count else "✗"

            print(f"{threshold:>13,}  {len(future_pairs_filtered):<10} {len(spot_pairs_filtered):<10} {actual_count:<10} {match_status}")

            # Assert consistency
            self.assertEqual(
                actual_count,
                expected_count,
                f"For threshold {threshold}: all ({actual_count}) != futures ({len(future_pairs_filtered)}) + spots ({len(spot_pairs_filtered)})"
            )

        # Detailed test for 300k threshold
        print("\n" + "-" * 55)
        print("Detailed analysis for 300k USDT threshold:")
        print("-" * 55)

        # Get unfiltered counts for comparison
        future_pairs_all = self.manager.get_tokenized_stock_pairs(asset_type='future')
        spot_pairs_all = self.manager.get_tokenized_stock_pairs(asset_type='spot')
        all_pairs_all = self.manager.get_tokenized_stock_pairs(asset_type='all')

        # Get filtered counts
        future_pairs_300k = self.manager.get_tokenized_stock_pairs(asset_type='future', min_volume_usdt=300000)
        spot_pairs_300k = self.manager.get_tokenized_stock_pairs(asset_type='spot', min_volume_usdt=300000)
        all_pairs_300k = self.manager.get_tokenized_stock_pairs(asset_type='all', min_volume_usdt=300000)

        print(f"\nBefore filtering:")
        print(f"  Futures: {len(future_pairs_all)}")
        print(f"  Spots:   {len(spot_pairs_all)}")
        print(f"  All:     {len(all_pairs_all)}")

        print(f"\nAfter filtering (>= 300k USDT):")
        print(f"  Futures: {len(future_pairs_300k)} ({len(future_pairs_300k)/len(future_pairs_all)*100:.1f}% qualified)")
        print(f"  Spots:   {len(spot_pairs_300k)} ({len(spot_pairs_300k)/len(spot_pairs_all)*100:.1f}% qualified)")
        print(f"  All:     {len(all_pairs_300k)} ({len(all_pairs_300k)/len(all_pairs_all)*100:.1f}% qualified)")

        print(f"\nFiltered out:")
        print(f"  Futures: {len(future_pairs_all) - len(future_pairs_300k)} (low volume)")
        print(f"  Spots:   {len(spot_pairs_all) - len(spot_pairs_300k)} (low volume)")
        print(f"  All:     {len(all_pairs_all) - len(all_pairs_300k)} (low volume)")

        # Show sample filtered futures
        if len(future_pairs_300k) > 0:
            print(f"\nSample liquid futures (first 5):")
            for i, (crypto_sym, equity_sym) in enumerate(future_pairs_300k[:5], 1):
                print(f"  {i}. {crypto_sym.Value:15s} <-> {equity_sym.Value}")

        # Show sample filtered spots
        if len(spot_pairs_300k) > 0:
            print(f"\nSample liquid spots (first 5):")
            for i, (crypto_sym, equity_sym) in enumerate(spot_pairs_300k[:5], 1):
                print(f"  {i}. {crypto_sym.Value:15s} <-> {equity_sym.Value}")

        print("\n✓ Volume filtering consistency verified across all asset types")
        print("✓ All = Futures + Spots for all thresholds")

if __name__ == '__main__':
    unittest.main(verbosity=2)
