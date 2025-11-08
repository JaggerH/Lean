"""
Unit tests for GateSymbolManager (New API)
"""
import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data_source import GateSymbolManager


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
        """Test get_pairs(type='spot')"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_pairs(type='spot')")
        print("="*80)

        # Get spot pairs (懒加载：自动获取数据)
        spot_pairs = self.manager.get_pairs(type='spot')

        # Verify structure
        self.assertIsInstance(spot_pairs, list)
        self.assertGreater(len(spot_pairs), 0)

        print(f"\n✓ Found {len(spot_pairs)} spot trading pairs")
        print("\nFirst 5 pairs:")
        for i, (crypto_symbol, equity_symbol) in enumerate(spot_pairs[:5]):
            print(f"  {i+1}. {str(crypto_symbol.Value):20s} <-> {str(equity_symbol.Value)}")

        print("="*80)

    def test_get_pairs_future(self):
        """Test get_pairs(type='future')"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_pairs(type='future')")
        print("="*80)

        # Get future pairs (懒加载：自动获取数据)
        future_pairs = self.manager.get_pairs(type='future')

        # Verify structure
        self.assertIsInstance(future_pairs, list)
        self.assertGreater(len(future_pairs), 0)

        print(f"\n✓ Found {len(future_pairs)} future trading pairs")
        print("\nFirst 5 pairs:")
        for i, (crypto_symbol, equity_symbol) in enumerate(future_pairs[:5]):
            print(f"  {i+1}. {str(crypto_symbol.Value):20s} <-> {str(equity_symbol.Value)}")

        print("="*80)

    def test_get_pairs_all(self):
        """Test get_pairs(type='all')"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_pairs(type='all')")
        print("="*80)

        # Clear data to test fresh fetch
        manager = GateSymbolManager(auto_sync=False)

        # Get all pairs
        all_pairs = manager.get_pairs(type='all')

        # Also get spot and future separately for comparison
        spot_pairs = manager.get_pairs(type='spot')
        future_pairs = manager.get_pairs(type='future')

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
        spot_pairs = manager.get_pairs(type='spot')
        self.assertIsNotNone(manager.spot_data)
        self.assertIsNone(manager.future_data)  # Future data not fetched yet

        print("2. After get_pairs(type='spot'): spot_data fetched, future_data still None")

        # Second call for future triggers future fetch
        future_pairs = manager.get_pairs(type='future')
        self.assertIsNotNone(manager.spot_data)
        self.assertIsNotNone(manager.future_data)

        print("3. After get_pairs(type='future'): both data fetched")
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

    def test_complete_workflow(self):
        """Test complete workflow: initialization -> fetch -> get pairs"""
        print("\n" + "="*80)
        print("Testing complete workflow")
        print("="*80)

        # Create fresh manager
        manager = GateSymbolManager(auto_sync=False)

        print("\n1. Getting spot pairs (auto-fetches data)...")
        spot_pairs = manager.get_pairs(type='spot')
        self.assertGreater(len(spot_pairs), 0)
        print(f"   ✓ Got {len(spot_pairs)} spot pairs")

        print("\n2. Getting future pairs (auto-fetches data)...")
        future_pairs = manager.get_pairs(type='future')
        self.assertGreater(len(future_pairs), 0)
        print(f"   ✓ Got {len(future_pairs)} future pairs")

        print("\n3. Getting all pairs (uses cached data)...")
        all_pairs = manager.get_pairs(type='all')
        self.assertEqual(len(all_pairs), len(spot_pairs) + len(future_pairs))
        print(f"   ✓ Got {len(all_pairs)} total pairs")

        print("\n✓ Complete workflow successful")
        print("="*80)


if __name__ == '__main__':
    unittest.main(verbosity=2)
