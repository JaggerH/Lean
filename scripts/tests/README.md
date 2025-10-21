# Gate.io Depth Converter Tests

Comprehensive unit tests for the Gate.io orderbook depth converter module.

## Overview

These tests validate the critical orderbook data processing pipeline that converts Gate.io incremental orderbook updates to LEAN format. The tests are designed to catch data quality issues (like crossed spreads) before they are written to output files.

## Test Coverage

### OrderbookBuilder Tests
- ✅ Initialization and reset functionality
- ✅ Applying updates: 'set', 'make', 'take' actions
- ✅ Bid vs ask side handling (side=1 for asks, side=2 for bids)
- ✅ Level removal when quantity goes to zero
- ✅ Snapshot timing (250ms interval)

### Snapshot Generation Tests
- ✅ Bid sorting (descending - highest price first)
- ✅ Ask sorting (ascending - lowest price first)
- ✅ Level limiting (top 10 levels)
- ✅ **CRITICAL: Crossed spread detection** (bid >= ask)
- ✅ Valid spread validation (bid < ask)

### CSV Format Tests
- ✅ LEAN CSV row structure (41 fields: 1 timestamp + 10 bid pairs + 10 ask pairs)
- ✅ Padding with zeros for missing levels
- ✅ Timestamp conversion (milliseconds since midnight)
- ✅ Empty orderbook handling

### Integration Tests
- ✅ End-to-end conversion with sample data
- ✅ Crossed spread error case (AAPLXUSD bug)
- ✅ Unsorted data handling
- ✅ Validation rejecting invalid snapshots

### Validation Logic Tests
- ✅ Accepting valid spreads
- ✅ **Rejecting crossed spreads (bid >= ask)**
- ✅ Rejecting equal bid and ask prices
- ✅ Rejecting empty bids or asks

## Running Tests

### Prerequisites

Ensure you have the test dependencies installed:

```bash
# Using conda environment
conda run -n lean pip install pytest pandas
```

### Run All Tests

```bash
# From the LEAN root directory
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py -v
```

### Run Specific Test Categories

```bash
# Run only OrderbookBuilder tests
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py::TestOrderbookBuilder -v

# Run only snapshot generation tests
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py::TestGetSnapshot -v

# Run only validation tests
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py::TestValidation -v

# Run only integration tests
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py::TestIntegration -v
```

### Run Specific Tests

```bash
# Run the crossed spread detection test
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py::TestIntegration::test_crossed_spread_detection -v

# Run validation rejection test
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py::TestValidation::test_validation_rejects_crossed_spread -v
```

### Run with Coverage

```bash
# Install pytest-cov if needed
conda run -n lean pip install pytest-cov

# Run with coverage report
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py --cov=scripts/converters/gateio_depth_convertor --cov-report=term-missing -v
```

### Run with Detailed Output

```bash
# Show print statements and detailed failure info
conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py -v -s --tb=long
```

## Test Fixtures

The tests use pytest fixtures defined in `conftest.py`:

- `temp_dir`: Temporary directory for test files
- `sample_gateio_orderbook_data`: Valid orderbook update sequence
- `sample_gateio_crossed_spread_data`: **Data that produces crossed spread (AAPLXUSD error case)**
- `sample_gateio_unsorted_data`: Unsorted bids/asks to test sorting
- `sample_gateio_csv_file`: Mock CSV.gz file for integration testing
- `expected_lean_format`: LEAN CSV format specification
- `base_date`: Base date for timestamp conversion

## Key Test Cases

### 1. Crossed Spread Detection (CRITICAL)

**Problem**: The AAPLXUSD error showed bid=252.75, ask=252.70 (bid > ask), which is invalid.

**Tests**:
- `test_get_snapshot_detects_crossed_spread`: Documents that crossed spreads can occur
- `test_crossed_spread_detection`: Integration test reproducing the AAPLXUSD error
- `test_validation_rejects_crossed_spread`: **Validates that the new validation logic rejects crossed spreads**

**Solution**: Added `validate_snapshot()` method that checks `bid[0] < ask[0]` before writing data.

### 2. Orderbook State Management

**Tests**:
- `test_apply_update_set_*`: Baseline snapshot setting
- `test_apply_update_make_*`: Adding liquidity
- `test_apply_update_take_*`: Removing liquidity

**Key Behavior**:
- Side=1 → Asks (sell orders)
- Side=2 → Bids (buy orders)
- Amount=0 → Remove price level

### 3. Sorting Validation

**Tests**:
- `test_get_snapshot_bids_sorted_descending`: Best bid (highest price) first
- `test_get_snapshot_asks_sorted_ascending`: Best ask (lowest price) first

**Why Important**: LEAN's OrderbookDepth.Reader() validates sort order and rejects incorrectly sorted data.

### 4. LEAN Format Compliance

**Tests**:
- `test_format_lean_row_basic`: 41-field structure
- `test_format_lean_row_padding`: Zero-padding for missing levels

**Format**: `timestamp,bid1_price,bid1_size,...,bid10_price,bid10_size,ask1_price,ask1_size,...,ask10_price,ask10_size`

## Debugging Failed Tests

### Common Issues

1. **Import Errors**
   ```bash
   # Make sure you're in the LEAN root directory
   cd /path/to/Lean
   conda run -n lean pytest scripts/tests/test_gateio_depth_convertor.py -v
   ```

2. **Module Not Found**
   ```bash
   # Ensure converters module is in path
   export PYTHONPATH="${PYTHONPATH}:$(pwd)/scripts"
   ```

3. **Crossed Spread Test Failing**
   - Expected behavior: Test should pass when validation correctly rejects crossed spreads
   - If failing: Check that `validate_snapshot()` is being called in `process_hourly_file()`

## Integration with LEAN

The converter output is validated by LEAN's `OrderbookDepth.Reader()` in:
- `Common/Data/Market/OrderbookDepth.cs:370-515`

The Reader validates:
- ✅ Bid-ask spread: `Bids[0].Price < Asks[0].Price` (line 475-480)
- ✅ Bid sorting: Descending (line 483-490)
- ✅ Ask sorting: Ascending (line 493-500)

Our tests mirror this validation logic to catch errors before data is written.

## Future Improvements

1. **Add Property-Based Testing**: Use `hypothesis` to generate random orderbook sequences
2. **Add Performance Tests**: Benchmark conversion speed (target: >1000 snapshots/sec)
3. **Add Corruption Recovery Tests**: Test handling of partially corrupted CSV files
4. **Add Multi-Symbol Tests**: Test concurrent conversion of multiple symbols

## Related Files

- **Converter**: `scripts/converters/gateio_depth_convertor.py`
- **C# Tests**: `Tests/Common/Data/Market/OrderbookDepthTests.cs`
- **C# Reader**: `Common/Data/Market/OrderbookDepth.cs`
- **LEAN Docs**: `arbitrage/OrderbookDepth_Implementation.md`

## Reporting Issues

If tests fail or you discover new edge cases:

1. Add a new test case documenting the issue
2. Fix the converter logic
3. Verify all tests pass
4. Document the fix in this README

## License

Copyright QuantConnect Corporation - Apache License 2.0
