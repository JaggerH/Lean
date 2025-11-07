"""
Unit tests for GateSymbolManager
"""
import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data_source import GateSymbolManager


class TestGateSymbolManager(unittest.TestCase):
    """Test GateSymbolManager class"""

    def setUp(self):
        """Set up test fixtures"""
        # Initialize without auto_sync to avoid database operations in tests
        self.manager = GateSymbolManager(auto_sync=False)

    def test_initialization(self):
        """Test that manager initializes correctly"""
        self.assertIsNone(self.manager.source)

    def test_get_tokenize_stocks(self):
        """Test fetching tokenized stocks from Gate.io API"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_tokenize_stocks()")
        print("="*80)

        # Call the function
        tokenized_stocks = self.manager.get_tokenize_stocks()

        # Verify response structure
        self.assertIsInstance(tokenized_stocks, dict, "Result should be a dictionary")
        self.assertIsNotNone(self.manager.source, "Source should be populated after API call")
        self.assertEqual(self.manager.source, tokenized_stocks, "Source should equal returned data")

        # Display results
        print(f"\n✓ API call successful")
        print(f"Found {len(tokenized_stocks)} tokenized stock pairs")
        print("-" * 80)

        if len(tokenized_stocks) > 0:
            # Count by provider
            xstock_count = sum(1 for p in tokenized_stocks.values() if 'xStock' in p.get('base_name', ''))
            ondo_count = sum(1 for p in tokenized_stocks.values() if 'Ondo Tokenized' in p.get('base_name', ''))

            print(f"\nBreakdown by provider:")
            print(f"  xStock (Backed Finance): {xstock_count}")
            print(f"  Ondo Tokenized: {ondo_count}")
            print(f"  Total: {xstock_count + ondo_count}")

            # Show examples
            print("\nExample pairs (first 10):")
            for i, (pair_id, pair_info) in enumerate(list(tokenized_stocks.items())[:10]):
                base = pair_info.get('base', '')
                base_name = pair_info.get('base_name', '')
                quote = pair_info.get('quote', '')

                print(f"  {pair_id:25s} | {base:15s} | {base_name}")

            # Verify all are USDT pairs
            non_usdt = [p for p in tokenized_stocks.values() if p.get('quote') != 'USDT']
            if non_usdt:
                print(f"\n⚠️ Warning: Found {len(non_usdt)} non-USDT pairs")
            else:
                print(f"\n✓ All pairs are USDT pairs")

        else:
            print("\n✗ No tokenized stocks found")

        print("="*80)

    def test_get_trade_pairs(self):
        """Test converting tokenized stocks to trade pairs"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_trade_pairs()")
        print("="*80)

        # First fetch the data
        self.manager.get_tokenize_stocks()

        # Get trade pairs
        trade_pairs = self.manager.get_trade_pairs()

        # Verify structure
        self.assertIsInstance(trade_pairs, list)
        self.assertGreater(len(trade_pairs), 0, "Should return at least one trade pair")

        print(f"\n✓ Found {len(trade_pairs)} trade pairs")
        print("\nFirst 10 trade pairs:")

        for i, (crypto_symbol, equity_symbol) in enumerate(trade_pairs[:10]):
            print(f"  {i+1:2d}. Crypto: {str(crypto_symbol):30s} <-> Equity: {str(equity_symbol)}")

            # Verify types - should be Symbol objects
            self.assertTrue(hasattr(crypto_symbol, 'Value'),
                          "crypto_symbol should be a LEAN Symbol object")
            self.assertTrue(hasattr(equity_symbol, 'Value'),
                          "equity_symbol should be a LEAN Symbol object")

        print("="*80)

    def test_get_trade_pairs_without_source(self):
        """Test that get_trade_pairs raises error when source is not populated"""
        manager = GateSymbolManager(auto_sync=False)
        with self.assertRaises(ValueError) as context:
            manager.get_trade_pairs()

        self.assertIn("Must call get_tokenize_stocks() first", str(context.exception))

    def test_get_records_to_database(self):
        """Test converting tokenized stocks to database CSV format"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_records_to_database()")
        print("="*80)

        # First fetch the data
        self.manager.get_tokenize_stocks()

        # Get CSV records
        csv_records = self.manager.get_records_to_database()

        # Verify structure
        self.assertIsInstance(csv_records, list)
        self.assertGreater(len(csv_records), 0, "Should return at least one CSV record")

        print(f"\n✓ Generated {len(csv_records)} CSV records")
        print("\nFirst 3 CSV records:")
        for i, record in enumerate(csv_records[:3]):
            print(f"\n{i+1}. {record}")

            # Verify CSV format (should have 12 fields)
            fields = record.split(',')
            self.assertEqual(len(fields), 12,
                           f"CSV record should have 12 fields, got {len(fields)}")

            # Verify first field is 'gate'
            self.assertEqual(fields[0], 'gate',
                           f"First field should be 'gate', got '{fields[0]}'")

            # Verify third field is 'crypto'
            self.assertEqual(fields[2], 'crypto',
                           f"Third field should be 'crypto', got '{fields[2]}'")

        print(f"\n✓ CSV format validated")
        print("="*80)

    def test_get_records_to_database_without_source(self):
        """Test that get_records_to_database raises error when source is not populated"""
        manager = GateSymbolManager(auto_sync=False)
        with self.assertRaises(ValueError) as context:
            manager.get_records_to_database()

        self.assertIn("Must call get_tokenize_stocks() first", str(context.exception))

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
        """Test that both xStock and Ondo Tokenized stocks are detected"""
        print("\n" + "="*80)
        print("Testing Provider Detection")
        print("="*80)

        # Fetch tokenized stocks
        stocks = self.manager.get_tokenize_stocks()

        # Check we have both providers
        xstocks = {k: v for k, v in stocks.items() if 'xStock' in v.get('base_name', '')}
        ondo_stocks = {k: v for k, v in stocks.items() if 'Ondo Tokenized' in v.get('base_name', '')}

        print(f"\nxStock pairs found: {len(xstocks)}")
        print(f"Ondo Tokenized pairs found: {len(ondo_stocks)}")

        self.assertGreater(len(xstocks), 0, "Should find at least one xStock pair")
        self.assertGreater(len(ondo_stocks), 0, "Should find at least one Ondo Tokenized pair")

        # Verify examples
        print("\nExample xStocks:")
        for pair_id in list(xstocks.keys())[:3]:
            print(f"  {pair_id}: {xstocks[pair_id].get('base_name')}")

        print("\nExample Ondo Tokenized:")
        for pair_id in list(ondo_stocks.keys())[:3]:
            print(f"  {pair_id}: {ondo_stocks[pair_id].get('base_name')}")

        print("\n✓ Both providers detected successfully")
        print("="*80)

    def test_full_workflow(self):
        """Test complete workflow: fetch -> parse -> generate CSV"""
        print("\n" + "="*80)
        print("Testing complete GateSymbolManager workflow")
        print("="*80)

        manager = GateSymbolManager(auto_sync=False)

        # Step 1: Fetch data
        print("\n1. Fetching tokenized stocks...")
        stocks = manager.get_tokenize_stocks()
        self.assertGreater(len(stocks), 0)
        print(f"   ✓ Fetched {len(stocks)} tokenized stocks")

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
        self.assertEqual(len(stocks), len(csv_records),
                       "Number of stocks should match number of CSV records")

        print("\n✓ Complete workflow successful")
        print("="*80)

    # ========== Futures Contract Tests ==========

    def test_initialization_futures(self):
        """Test that futures_source initializes correctly"""
        manager = GateSymbolManager(auto_sync=False)
        self.assertIsNone(manager.futures_source)

    def test_get_futures_contracts(self):
        """Test fetching futures contracts from Gate.io API"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_futures_contracts()")
        print("="*80)

        # Call the function
        contracts = self.manager.get_futures_contracts(settle="usdt", filter_tokenized=False)

        # Verify response structure
        self.assertIsInstance(contracts, dict, "Result should be a dictionary")
        self.assertIsNotNone(self.manager.futures_source, "futures_source should be populated")
        self.assertEqual(self.manager.futures_source, contracts, "futures_source should equal returned data")

        # Display results
        print(f"\n✓ API call successful")
        print(f"Found {len(contracts)} futures contracts")
        print("-" * 80)

        if len(contracts) > 0:
            # Show examples
            print("\nExample contracts (first 5):")
            for i, (contract_name, contract_info) in enumerate(list(contracts.items())[:5]):
                quanto_mult = contract_info.get('quanto_multiplier', 'N/A')
                order_size_min = contract_info.get('order_size_min', 'N/A')
                price_round = contract_info.get('order_price_round', 'N/A')

                print(f"  {contract_name:20s} | Multiplier: {quanto_mult:10s} | Min Size: {order_size_min} | Price Round: {price_round}")

            # Verify required fields exist
            sample_contract = list(contracts.values())[0]
            required_fields = ['name', 'quanto_multiplier', 'order_size_min', 'order_price_round']
            for field in required_fields:
                self.assertIn(field, sample_contract, f"Contract should have '{field}' field")

            print(f"\n✓ All required fields present")
        else:
            print("\n✗ No contracts found")

        print("="*80)

    def test_get_futures_contracts_filter_tokenized(self):
        """Test fetching only tokenized stock futures"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_futures_contracts(filter_tokenized=True)")
        print("="*80)

        # Call with tokenized filter
        contracts = self.manager.get_futures_contracts(settle="usdt", filter_tokenized=True)

        print(f"\n✓ Found {len(contracts)} tokenized stock futures")

        if len(contracts) > 0:
            print("\nTokenized stock futures:")
            for contract_name in list(contracts.keys())[:10]:
                print(f"  {contract_name}")

            # Verify they have X_ or ON_ pattern
            for contract_name in contracts.keys():
                self.assertTrue('X_' in contract_name or 'ON_' in contract_name,
                              f"{contract_name} should contain 'X_' or 'ON_'")

            print(f"\n✓ All contracts match tokenized pattern")
        else:
            print("\n⚠️ No tokenized stock futures found (this may be normal if Gate.io doesn't offer them)")

        print("="*80)

    def test_get_single_futures_contract(self):
        """Test fetching a single futures contract"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_single_futures_contract()")
        print("="*80)

        # Test with BTC_USDT (should always exist)
        contract_name = "BTC_USDT"
        print(f"\nFetching contract: {contract_name}")

        contract_data = self.manager.get_single_futures_contract(contract_name, settle="usdt")

        # Verify response
        self.assertIsInstance(contract_data, dict, "Result should be a dictionary")
        self.assertIn('name', contract_data, "Contract should have 'name' field")
        self.assertEqual(contract_data['name'], contract_name, "Contract name should match")

        # Verify it's stored in futures_source
        self.assertIsNotNone(self.manager.futures_source)
        self.assertIn(contract_name, self.manager.futures_source)

        # Display contract details
        print(f"\n✓ Contract fetched successfully")
        print(f"\nContract details:")
        print(f"  Name: {contract_data.get('name')}")
        print(f"  Type: {contract_data.get('type')}")
        print(f"  Quanto Multiplier: {contract_data.get('quanto_multiplier')}")
        print(f"  Order Size Min: {contract_data.get('order_size_min')}")
        print(f"  Order Price Round: {contract_data.get('order_price_round')}")
        print(f"  Leverage Max: {contract_data.get('leverage_max')}")

        print("="*80)

    def test_get_single_futures_contract_invalid_settle(self):
        """Test that invalid settle parameter raises error"""
        manager = GateSymbolManager(auto_sync=False)
        with self.assertRaises(ValueError) as context:
            manager.get_single_futures_contract("BTC_USDT", settle="invalid")

        self.assertIn("Invalid settle parameter", str(context.exception))

    def test_get_futures_records_to_database(self):
        """Test converting futures contracts to database CSV format"""
        print("\n" + "="*80)
        print("Testing GateSymbolManager.get_futures_records_to_database()")
        print("="*80)

        # First fetch some contracts
        self.manager.get_futures_contracts(settle="usdt", filter_tokenized=False)

        # Limit to first 5 for testing
        if len(self.manager.futures_source) > 5:
            limited_source = dict(list(self.manager.futures_source.items())[:5])
            self.manager.futures_source = limited_source

        # Get CSV records
        csv_records = self.manager.get_futures_records_to_database()

        # Verify structure
        self.assertIsInstance(csv_records, list)
        self.assertGreater(len(csv_records), 0, "Should return at least one CSV record")

        print(f"\n✓ Generated {len(csv_records)} CSV records")
        print("\nFirst 3 CSV records:")
        for i, record in enumerate(csv_records[:3]):
            print(f"\n{i+1}. {record}")

            # Verify CSV format (should have 12 fields)
            fields = record.split(',')
            self.assertEqual(len(fields), 12,
                           f"CSV record should have 12 fields, got {len(fields)}")

            # Verify first field is 'gate'
            self.assertEqual(fields[0], 'gate',
                           f"First field should be 'gate', got '{fields[0]}'")

            # Verify third field is 'cryptofuture'
            self.assertEqual(fields[2], 'cryptofuture',
                           f"Third field should be 'cryptofuture', got '{fields[2]}'")

            # Verify contract_multiplier (field 5) is present
            self.assertTrue(len(fields[5]) > 0,
                          "contract_multiplier field should not be empty")

            # Verify lot_size (field 7) is present
            self.assertTrue(len(fields[7]) > 0,
                          "lot_size field should not be empty")

        print(f"\n✓ CSV format validated")
        print("="*80)

    def test_get_futures_records_without_source(self):
        """Test that get_futures_records_to_database raises error when futures_source is not populated"""
        manager = GateSymbolManager(auto_sync=False)
        with self.assertRaises(ValueError) as context:
            manager.get_futures_records_to_database()

        self.assertIn("Must call get_futures_contracts() or get_single_futures_contract() first",
                     str(context.exception))

    def test_futures_full_workflow(self):
        """Test complete futures workflow: fetch -> generate CSV"""
        print("\n" + "="*80)
        print("Testing complete futures workflow")
        print("="*80)

        manager = GateSymbolManager(auto_sync=False)

        # Step 1: Fetch contracts
        print("\n1. Fetching futures contracts...")
        contracts = manager.get_futures_contracts(settle="usdt", filter_tokenized=False)
        self.assertGreater(len(contracts), 0)
        print(f"   ✓ Fetched {len(contracts)} futures contracts")

        # Limit to first 10 for CSV generation
        if len(manager.futures_source) > 10:
            limited_source = dict(list(manager.futures_source.items())[:10])
            manager.futures_source = limited_source
            print(f"   ℹ Limited to {len(manager.futures_source)} contracts for testing")

        # Step 2: Generate CSV records
        print("\n2. Generating database records...")
        csv_records = manager.get_futures_records_to_database()
        self.assertGreater(len(csv_records), 0)
        print(f"   ✓ Generated {len(csv_records)} CSV records")

        # Verify counts match
        self.assertEqual(len(manager.futures_source), len(csv_records),
                       "Number of contracts should match number of CSV records")

        print("\n✓ Complete futures workflow successful")
        print("="*80)

    def test_futures_and_spot_workflow(self):
        """Test combined spot and futures workflow"""
        print("\n" + "="*80)
        print("Testing combined spot and futures workflow")
        print("="*80)

        manager = GateSymbolManager(auto_sync=False)

        # Step 1: Fetch spot tokenized stocks
        print("\n1. Fetching spot tokenized stocks...")
        spot_stocks = manager.get_tokenize_stocks()
        print(f"   ✓ Fetched {len(spot_stocks)} spot tokenized stocks")

        # Step 2: Fetch futures contracts
        print("\n2. Fetching futures contracts...")
        futures_contracts = manager.get_futures_contracts(settle="usdt", filter_tokenized=True)
        print(f"   ✓ Fetched {len(futures_contracts)} tokenized futures contracts")

        # Step 3: Generate CSV for both
        print("\n3. Generating CSV records...")
        spot_csv = manager.get_records_to_database()
        futures_csv = manager.get_futures_records_to_database()
        print(f"   ✓ Generated {len(spot_csv)} spot CSV records")
        print(f"   ✓ Generated {len(futures_csv)} futures CSV records")

        # Verify both sources are populated
        self.assertIsNotNone(manager.source)
        self.assertIsNotNone(manager.futures_source)

        print("\n✓ Combined workflow successful")
        print("="*80)


if __name__ == '__main__':
    unittest.main(verbosity=2)
