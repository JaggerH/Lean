"""
Unit tests for KrakenSymbolManager
"""
import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data_source import KrakenSymbolManager


class TestKrakenSymbolManager(unittest.TestCase):
    """Test KrakenSymbolManager class"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = KrakenSymbolManager()

    def test_initialization(self):
        """Test that manager initializes correctly"""
        self.assertIsNone(self.manager.source)

    def test_get_tokenize_stocks(self):
        """Test fetching xStocks from Kraken API"""
        print("\n" + "="*80)
        print("Testing KrakenSymbolManager.get_tokenize_stocks()")
        print("="*80)

        # Call the function - should return dict directly or raise exception
        xstocks = self.manager.get_tokenize_stocks()

        # Verify response structure
        self.assertIsInstance(xstocks, dict, "Result should be a dictionary of pairs")
        self.assertIsNotNone(self.manager.source, "Source should be populated after API call")
        self.assertEqual(self.manager.source, xstocks, "Source should equal returned data")

        # Display results
        print(f"\n✓ API call successful")
        print(f"Found {len(xstocks)} xStocks pairs")
        print("-" * 80)

        if len(xstocks) > 0:
            print("\nxStocks symbols found:")
            for i, (pair_name, pair_info) in enumerate(xstocks.items()):
                if i >= 10:  # Show first 10
                    print(f"... and {len(xstocks) - 10} more")
                    break

                wsname = pair_info.get('wsname', '')
                base = pair_info.get('base', '')
                quote = pair_info.get('quote', '')
                aclass_base = pair_info.get('aclass_base', '')

                print(f"  {pair_name:20s} | WS: {wsname:20s} | "
                      f"{base}/{quote} | Class: {aclass_base}")

            # Verify they are actually tokenized assets
            first_pair = list(xstocks.values())[0]
            aclass_base = first_pair.get('aclass_base', '')
            self.assertEqual(aclass_base, 'tokenized_asset',
                           f"Expected aclass_base='tokenized_asset', got '{aclass_base}'")

            print(f"\n✓ Confirmed: All pairs have aclass_base='tokenized_asset'")

        else:
            print("\n✗ No xStocks found")
            print("\nPossible reasons:")
            print("  1. xStocks not available in your region")
            print("  2. Parameter 'aclass_base=tokenized_asset' may be incorrect")
            print("  3. xStocks may require authentication")

        print("="*80)

    def test_response_fields(self):
        """Test that response contains expected fields for each pair"""
        xstocks = self.manager.get_tokenize_stocks()

        if not xstocks:
            self.skipTest("No xStocks returned from API")

        # Check first pair has expected fields
        first_pair_name = list(xstocks.keys())[0]
        first_pair = xstocks[first_pair_name]

        expected_fields = ['base', 'quote', 'wsname', 'aclass_base']

        for field in expected_fields:
            self.assertIn(field, first_pair,
                        f"Pair should contain '{field}' field")

        print(f"\n✓ All expected fields present in xStocks data")

    def test_get_trade_pairs(self):
        """Test converting xStocks to trade pairs"""
        print("\n" + "="*80)
        print("Testing KrakenSymbolManager.get_trade_pairs()")
        print("="*80)

        # First fetch the data
        self.manager.get_tokenize_stocks()

        # Get trade pairs
        trade_pairs = self.manager.get_trade_pairs()

        # Verify structure
        self.assertIsInstance(trade_pairs, list)
        self.assertGreater(len(trade_pairs), 0, "Should return at least one trade pair")

        print(f"\n✓ Found {len(trade_pairs)} trade pairs")
        print("\nFirst 5 trade pairs:")

        for i, (crypto_symbol, equity_symbol) in enumerate(trade_pairs[:5]):
            print(f"  {i+1}. Crypto: {crypto_symbol} <-> Stock: {equity_symbol}")

            # Verify types - should be Symbol objects
            self.assertTrue(hasattr(crypto_symbol, 'Value'),
                          "crypto_symbol should be a LEAN Symbol object")
            self.assertTrue(hasattr(equity_symbol, 'Value'),
                          "equity_symbol should be a LEAN Symbol object")

        print("="*80)

    def test_get_trade_pairs_without_source(self):
        """Test that get_trade_pairs raises error when source is not populated"""
        manager = KrakenSymbolManager()
        with self.assertRaises(ValueError) as context:
            manager.get_trade_pairs()

        self.assertIn("Must call get_tokenize_stocks() first", str(context.exception))

    def test_get_records_to_database(self):
        """Test converting xStocks to database CSV format"""
        print("\n" + "="*80)
        print("Testing KrakenSymbolManager.get_records_to_database()")
        print("="*80)

        # First fetch the data
        self.manager.get_tokenize_stocks()

        # Get CSV records
        csv_records = self.manager.get_records_to_database()

        # Verify structure
        self.assertIsInstance(csv_records, list)
        self.assertGreater(len(csv_records), 0, "Should return at least one CSV record")

        print(f"\n✓ Generated {len(csv_records)} CSV records")
        print("\nFirst CSV record:")
        if csv_records:
            print(f"  {csv_records[0]}")

            # Verify CSV format (should have 12 fields)
            fields = csv_records[0].split(',')
            self.assertEqual(len(fields), 12,
                           f"CSV record should have 12 fields, got {len(fields)}")

            # Verify first field is 'kraken'
            self.assertEqual(fields[0], 'kraken',
                           f"First field should be 'kraken', got '{fields[0]}'")

            # Verify third field is 'crypto'
            self.assertEqual(fields[2], 'crypto',
                           f"Third field should be 'crypto', got '{fields[2]}'")

            print(f"✓ CSV format validated")

        print("="*80)

    def test_get_records_to_database_without_source(self):
        """Test that get_records_to_database raises error when source is not populated"""
        manager = KrakenSymbolManager()
        with self.assertRaises(ValueError) as context:
            manager.get_records_to_database()

        self.assertIn("Must call get_tokenize_stocks() first", str(context.exception))

    def test_full_workflow(self):
        """Test complete workflow: fetch -> parse -> generate CSV"""
        print("\n" + "="*80)
        print("Testing complete KrakenSymbolManager workflow")
        print("="*80)

        manager = KrakenSymbolManager()

        # Step 1: Fetch data
        print("\n1. Fetching tokenized stocks...")
        xstocks = manager.get_tokenize_stocks()
        self.assertGreater(len(xstocks), 0)
        print(f"   ✓ Fetched {len(xstocks)} xStocks")

        # Step 2: Get trade pairs
        print("\n2. Converting to trade pairs...")
        trade_pairs = manager.get_trade_pairs()
        self.assertGreater(len(trade_pairs), 0)
        print(f"   ✓ Generated {len(trade_pairs)} trade pairs")

        # Step 3: Generate CSV records
        print("\n3. Generating database records...")
        csv_records = manager.get_records_to_database()
        self.assertGreater(len(csv_records), 0)
        print(f"   ✓ Generated {len(csv_records)} CSV records")

        # Verify counts match
        self.assertEqual(len(xstocks), len(csv_records),
                       "Number of xStocks should match number of CSV records")

        print("\n✓ Complete workflow successful")
        print("="*80)


if __name__ == '__main__':
    unittest.main(verbosity=2)
