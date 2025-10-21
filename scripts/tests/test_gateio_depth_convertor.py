"""
Unit tests for Gate.io Orderbook Depth Converter

Tests cover:
- OrderbookBuilder class functionality
- Snapshot generation and validation
- CSV format generation
- Integration with LEAN format
- Error cases (crossed spreads, invalid data)
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from converters.gateio_depth_convertor import (
    OrderbookBuilder,
    DEPTH_LEVELS,
    SNAPSHOT_INTERVAL_MS,
    parse_filename,
)


class TestOrderbookBuilder:
    """Test OrderbookBuilder class"""

    def test_initialization(self):
        """Test OrderbookBuilder initializes with empty state"""
        builder = OrderbookBuilder()

        assert isinstance(builder.bids, dict)
        assert isinstance(builder.asks, dict)
        assert len(builder.bids) == 0
        assert len(builder.asks) == 0
        assert builder.last_snapshot_time == 0

    def test_reset(self):
        """Test reset clears orderbook state"""
        builder = OrderbookBuilder()

        # Add some data
        builder.bids[100.0] = 10.0
        builder.asks[101.0] = 12.0
        builder.last_snapshot_time = 12345

        # Reset
        builder.reset()

        assert len(builder.bids) == 0
        assert len(builder.asks) == 0
        assert builder.last_snapshot_time == 0

    def test_apply_update_set_bid(self):
        """Test applying 'set' action to bid side"""
        builder = OrderbookBuilder()

        # Set initial bid
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)

        assert 100.0 in builder.bids
        assert builder.bids[100.0] == 10.0
        assert len(builder.asks) == 0

    def test_apply_update_set_ask(self):
        """Test applying 'set' action to ask side"""
        builder = OrderbookBuilder()

        # Set initial ask
        builder.apply_update(1693526400.0, side=1, action='set', price=101.0, amount=12.0)

        assert 101.0 in builder.asks
        assert builder.asks[101.0] == 12.0
        assert len(builder.bids) == 0

    def test_apply_update_set_zero_removes_level(self):
        """Test that 'set' with amount=0 removes the level"""
        builder = OrderbookBuilder()

        # Set initial level
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)
        assert 100.0 in builder.bids

        # Set to zero should remove
        builder.apply_update(1693526400.1, side=2, action='set', price=100.0, amount=0.0)
        assert 100.0 not in builder.bids

    def test_apply_update_make_adds_liquidity(self):
        """Test 'make' action adds liquidity"""
        builder = OrderbookBuilder()

        # Initial set
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)

        # Make adds to existing
        builder.apply_update(1693526400.1, side=2, action='make', price=100.0, amount=5.0)

        assert builder.bids[100.0] == 15.0

    def test_apply_update_make_new_level(self):
        """Test 'make' action creates new price level"""
        builder = OrderbookBuilder()

        # Make on new price level
        builder.apply_update(1693526400.0, side=2, action='make', price=100.0, amount=10.0)

        assert 100.0 in builder.bids
        assert builder.bids[100.0] == 10.0

    def test_apply_update_make_zero_removes_level(self):
        """Test 'make' resulting in zero or negative removes level"""
        builder = OrderbookBuilder()

        # Set initial
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)

        # Make with negative (shouldn't happen but handle it)
        builder.apply_update(1693526400.1, side=2, action='make', price=100.0, amount=-15.0)

        assert 100.0 not in builder.bids

    def test_apply_update_take_removes_liquidity(self):
        """Test 'take' action removes liquidity"""
        builder = OrderbookBuilder()

        # Initial set
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)

        # Take removes from existing
        builder.apply_update(1693526400.1, side=2, action='take', price=100.0, amount=3.0)

        assert builder.bids[100.0] == 7.0

    def test_apply_update_take_removes_level_when_empty(self):
        """Test 'take' removes level when quantity goes to zero or below"""
        builder = OrderbookBuilder()

        # Initial set
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)

        # Take all
        builder.apply_update(1693526400.1, side=2, action='take', price=100.0, amount=10.0)

        assert 100.0 not in builder.bids

    def test_apply_update_take_more_than_available(self):
        """Test 'take' removing more than available removes the level"""
        builder = OrderbookBuilder()

        # Initial set
        builder.apply_update(1693526400.0, side=2, action='set', price=100.0, amount=10.0)

        # Take more than available
        builder.apply_update(1693526400.1, side=2, action='take', price=100.0, amount=15.0)

        assert 100.0 not in builder.bids

    def test_apply_update_take_nonexistent_level(self):
        """Test 'take' on non-existent level doesn't crash"""
        builder = OrderbookBuilder()

        # Take from non-existent level
        builder.apply_update(1693526400.0, side=2, action='take', price=100.0, amount=5.0)

        # Should not add to bids
        assert 100.0 not in builder.bids

    def test_should_output_snapshot_initial(self):
        """Test first snapshot at interval threshold"""
        builder = OrderbookBuilder()

        # At timestamp 0, delta is 0 which is < 250, so should not output
        assert builder.should_output_snapshot(0) is False

        # At timestamp >= 250ms, should output first snapshot
        assert builder.should_output_snapshot(SNAPSHOT_INTERVAL_MS) is True
        assert builder.last_snapshot_time == SNAPSHOT_INTERVAL_MS

    def test_should_output_snapshot_interval(self):
        """Test snapshot output respects time interval"""
        builder = OrderbookBuilder()

        # First snapshot at 250ms
        assert builder.should_output_snapshot(SNAPSHOT_INTERVAL_MS) is True
        assert builder.last_snapshot_time == SNAPSHOT_INTERVAL_MS

        # Within interval - should not output
        assert builder.should_output_snapshot(SNAPSHOT_INTERVAL_MS + 100) is False
        assert builder.should_output_snapshot(SNAPSHOT_INTERVAL_MS * 2 - 1) is False

        # At next interval - should output
        assert builder.should_output_snapshot(SNAPSHOT_INTERVAL_MS * 2) is True
        assert builder.last_snapshot_time == SNAPSHOT_INTERVAL_MS * 2

        # Next interval
        assert builder.should_output_snapshot(SNAPSHOT_INTERVAL_MS * 3) is True


class TestGetSnapshot:
    """Test orderbook snapshot generation"""

    def test_get_snapshot_empty_orderbook(self):
        """Test snapshot of empty orderbook"""
        builder = OrderbookBuilder()

        bids, asks = builder.get_snapshot(levels=10)

        assert len(bids) == 0
        assert len(asks) == 0

    def test_get_snapshot_bids_sorted_descending(self):
        """Test bids are sorted in descending order (best first)"""
        builder = OrderbookBuilder()

        # Add bids in random order
        builder.bids = {100.05: 10.0, 100.03: 20.0, 100.04: 15.0, 100.01: 30.0}

        bids, _ = builder.get_snapshot(levels=10)

        # Verify descending order
        assert len(bids) == 4
        assert bids[0] == (100.05, 10.0)  # Highest price first
        assert bids[1] == (100.04, 15.0)
        assert bids[2] == (100.03, 20.0)
        assert bids[3] == (100.01, 30.0)  # Lowest price last

    def test_get_snapshot_asks_sorted_ascending(self):
        """Test asks are sorted in ascending order (best first)"""
        builder = OrderbookBuilder()

        # Add asks in random order
        builder.asks = {100.08: 22.0, 100.06: 12.0, 100.09: 28.0, 100.07: 18.0}

        _, asks = builder.get_snapshot(levels=10)

        # Verify ascending order
        assert len(asks) == 4
        assert asks[0] == (100.06, 12.0)  # Lowest price first
        assert asks[1] == (100.07, 18.0)
        assert asks[2] == (100.08, 22.0)
        assert asks[3] == (100.09, 28.0)  # Highest price last

    def test_get_snapshot_limits_levels(self):
        """Test snapshot limits to requested number of levels"""
        builder = OrderbookBuilder()

        # Add more than 10 levels
        for i in range(20):
            builder.bids[100.0 - i * 0.01] = 10.0
            builder.asks[101.0 + i * 0.01] = 12.0

        bids, asks = builder.get_snapshot(levels=10)

        assert len(bids) == 10  # Top 10 bids
        assert len(asks) == 10  # Top 10 asks

    def test_get_snapshot_less_than_requested_levels(self):
        """Test snapshot with fewer levels than requested"""
        builder = OrderbookBuilder()

        # Add only 3 levels
        builder.bids = {100.05: 10.0, 100.04: 15.0, 100.03: 20.0}
        builder.asks = {100.06: 12.0, 100.07: 18.0, 100.08: 22.0}

        bids, asks = builder.get_snapshot(levels=10)

        assert len(bids) == 3
        assert len(asks) == 3

    def test_get_snapshot_valid_spread(self):
        """Test snapshot has valid spread (best bid < best ask)"""
        builder = OrderbookBuilder()

        builder.bids = {100.05: 10.0, 100.04: 15.0}
        builder.asks = {100.06: 12.0, 100.07: 18.0}

        bids, asks = builder.get_snapshot(levels=10)

        # Verify best bid < best ask
        assert bids[0][0] < asks[0][0]  # 100.05 < 100.06

    def test_get_snapshot_detects_crossed_spread(self):
        """
        CRITICAL TEST: Detect crossed spread (bid >= ask)
        This is the bug causing the AAPLXUSD error
        """
        builder = OrderbookBuilder()

        # Create crossed spread scenario (like AAPLXUSD error)
        builder.bids = {252.75: 10.0}  # Bid is HIGHER
        builder.asks = {252.70: 12.0}  # Ask is LOWER - CROSSED!

        bids, asks = builder.get_snapshot(levels=10)

        # The snapshot is generated, but we need validation elsewhere
        # This test documents the issue - we get invalid data
        assert bids[0][0] > asks[0][0]  # This is INVALID - should be caught!


class TestFormatLeanRow:
    """Test LEAN CSV row formatting"""

    def test_format_lean_row_basic(self):
        """Test basic CSV row formatting"""
        builder = OrderbookBuilder()

        bids = [(100.05, 10.0), (100.04, 15.0)]
        asks = [(100.06, 12.0), (100.07, 18.0)]
        timestamp_ms = 18000677

        row = builder.format_lean_row(timestamp_ms, bids, asks)

        # Verify structure: timestamp + 10 bid pairs + 10 ask pairs = 41 fields
        assert len(row) == 1 + (DEPTH_LEVELS * 2) + (DEPTH_LEVELS * 2)
        assert row[0] == timestamp_ms

        # Verify bid data
        assert row[1] == 100.05
        assert row[2] == 10.0
        assert row[3] == 100.04
        assert row[4] == 15.0

        # Verify ask data (starts after all bids)
        ask_start_idx = 1 + (DEPTH_LEVELS * 2)
        assert row[ask_start_idx] == 100.06
        assert row[ask_start_idx + 1] == 12.0
        assert row[ask_start_idx + 2] == 100.07
        assert row[ask_start_idx + 3] == 18.0

    def test_format_lean_row_padding(self):
        """Test padding with zeros when levels < DEPTH_LEVELS"""
        builder = OrderbookBuilder()

        # Only 2 levels
        bids = [(100.05, 10.0), (100.04, 15.0)]
        asks = [(100.06, 12.0), (100.07, 18.0)]

        row = builder.format_lean_row(18000677, bids, asks)

        # Verify padding (should have 0,0 for missing levels)
        # Bid 3 should be padded
        assert row[5] == 0  # bid3_price
        assert row[6] == 0  # bid3_size

        # Ask 3 should be padded
        ask_start_idx = 1 + (DEPTH_LEVELS * 2)
        assert row[ask_start_idx + 4] == 0  # ask3_price
        assert row[ask_start_idx + 5] == 0  # ask3_size

    def test_format_lean_row_full_levels(self):
        """Test formatting with exactly DEPTH_LEVELS"""
        builder = OrderbookBuilder()

        # Create full 10 levels
        bids = [(100.0 + i * 0.01, 10.0 + i) for i in range(DEPTH_LEVELS)]
        asks = [(101.0 + i * 0.01, 12.0 + i) for i in range(DEPTH_LEVELS)]

        row = builder.format_lean_row(18000677, bids, asks)

        # Verify no padding needed
        # Check last bid level
        assert row[1 + (DEPTH_LEVELS - 1) * 2] == bids[-1][0]
        assert row[1 + (DEPTH_LEVELS - 1) * 2 + 1] == bids[-1][1]

        # Check last ask level
        ask_start_idx = 1 + (DEPTH_LEVELS * 2)
        assert row[ask_start_idx + (DEPTH_LEVELS - 1) * 2] == asks[-1][0]
        assert row[ask_start_idx + (DEPTH_LEVELS - 1) * 2 + 1] == asks[-1][1]

    def test_format_lean_row_empty_orderbook(self):
        """Test formatting with empty orderbook"""
        builder = OrderbookBuilder()

        bids = []
        asks = []

        row = builder.format_lean_row(18000677, bids, asks)

        # Should be all zeros except timestamp
        assert row[0] == 18000677
        assert all(x == 0 for x in row[1:])


class TestFilenameHandling:
    """Test filename parsing and formatting"""

    def test_parse_filename_valid(self):
        """Test parsing valid Gate.io filename"""
        filename = "AAPLX_USDT-2025090100.csv.gz"

        result = parse_filename(filename)

        assert result is not None
        assert result['symbol'] == 'AAPLX_USDT'
        assert result['date'] == '20250901'
        assert result['hour'] == '00'

    def test_parse_filename_different_symbol(self):
        """Test parsing different symbol"""
        filename = "TSLAX_USDT-2025091523.csv.gz"

        result = parse_filename(filename)

        assert result is not None
        assert result['symbol'] == 'TSLAX_USDT'
        assert result['date'] == '20250915'
        assert result['hour'] == '23'

    def test_parse_filename_invalid_format(self):
        """Test parsing invalid filename returns None"""
        filename = "invalid_filename.csv.gz"

        result = parse_filename(filename)

        assert result is None

    def test_parse_filename_missing_extension(self):
        """Test parsing filename without .csv.gz"""
        filename = "AAPLX_USDT-2025090100.csv"

        result = parse_filename(filename)

        assert result is None


class TestIntegration:
    """Integration tests for end-to-end conversion"""

    def test_process_sample_data_basic(self):
        """Test processing sample orderbook data and validation"""
        from converters.gateio_depth_convertor import OrderbookBuilder

        builder = OrderbookBuilder()

        # Simulate orderbook updates
        builder.apply_update(0, side=2, action='set', price=100.05, amount=10.0)
        builder.apply_update(0, side=2, action='set', price=100.04, amount=15.0)
        builder.apply_update(0, side=2, action='set', price=100.03, amount=20.0)
        builder.apply_update(0, side=1, action='set', price=100.06, amount=12.0)
        builder.apply_update(0, side=1, action='set', price=100.07, amount=18.0)
        builder.apply_update(0, side=1, action='set', price=100.08, amount=22.0)

        # Get snapshot
        bids, asks = builder.get_snapshot(levels=DEPTH_LEVELS)

        # Verify both sides have data
        assert len(bids) > 0
        assert len(asks) > 0

        # Verify valid spread (CRITICAL TEST)
        is_valid, error_msg = builder.validate_snapshot(bids, asks)
        assert is_valid is True, f"Snapshot validation failed: {error_msg}"

        # Verify snapshot can be formatted
        row_data = builder.format_lean_row(250, bids, asks)
        assert len(row_data) == 1 + (DEPTH_LEVELS * 2) * 2

        # Verify valid spread in output
        best_bid_price = row_data[1]
        best_ask_price = row_data[1 + DEPTH_LEVELS * 2]
        assert best_bid_price < best_ask_price, \
            f"Crossed spread in output: bid={best_bid_price}, ask={best_ask_price}"

    def test_crossed_spread_detection(self, sample_gateio_crossed_spread_data, base_date):
        """
        CRITICAL TEST: Detect the AAPLXUSD crossed spread bug
        This test should catch the error before it's written to file
        """
        from converters.gateio_depth_convertor import OrderbookBuilder

        builder = OrderbookBuilder()

        for row in sample_gateio_crossed_spread_data:
            timestamp, side, action, price, amount = row[:5]
            builder.apply_update(timestamp, side, action, price, amount)

        # Get snapshot
        bids, asks = builder.get_snapshot(levels=DEPTH_LEVELS)

        assert len(bids) > 0
        assert len(asks) > 0

        best_bid = bids[0][0]
        best_ask = asks[0][0]

        # This is the AAPLXUSD error case - bid (252.75) > ask (252.70)
        # The test documents the bug
        assert best_bid > best_ask, "Expected crossed spread for this test case"

        # In production code, we should REJECT this snapshot
        # See test_validation_rejects_crossed_spread below

    def test_unsorted_data_gets_sorted(self, sample_gateio_unsorted_data, base_date):
        """Test that unsorted data gets properly sorted in snapshot"""
        from converters.gateio_depth_convertor import OrderbookBuilder

        builder = OrderbookBuilder()

        for row in sample_gateio_unsorted_data:
            timestamp, side, action, price, amount = row[:5]
            builder.apply_update(timestamp, side, action, price, amount)

        bids, asks = builder.get_snapshot(levels=DEPTH_LEVELS)

        # Verify bids are sorted descending
        for i in range(len(bids) - 1):
            assert bids[i][0] > bids[i + 1][0], \
                f"Bids not sorted descending: {bids[i][0]} <= {bids[i + 1][0]}"

        # Verify asks are sorted ascending
        for i in range(len(asks) - 1):
            assert asks[i][0] < asks[i + 1][0], \
                f"Asks not sorted ascending: {asks[i][0]} >= {asks[i + 1][0]}"


class TestValidation:
    """Test validation logic that should be added to the converter"""

    def test_validation_accepts_valid_spread(self):
        """Test validation accepts valid spread"""
        bids = [(100.05, 10.0), (100.04, 15.0)]
        asks = [(100.06, 12.0), (100.07, 18.0)]

        # Validation logic (to be added to converter)
        is_valid = len(bids) > 0 and len(asks) > 0 and bids[0][0] < asks[0][0]

        assert is_valid is True

    def test_validation_rejects_crossed_spread(self):
        """
        CRITICAL TEST: Validation should reject crossed spread
        This is what we need to add to the converter
        """
        # AAPLXUSD error case
        bids = [(252.75, 10.0)]  # Bid higher
        asks = [(252.70, 12.0)]  # Ask lower - INVALID!

        # Validation logic (to be added to converter)
        is_valid = len(bids) > 0 and len(asks) > 0 and bids[0][0] < asks[0][0]

        assert is_valid is False, "Should reject crossed spread"

    def test_validation_rejects_equal_bid_ask(self):
        """Test validation rejects bid == ask"""
        bids = [(100.05, 10.0)]
        asks = [(100.05, 12.0)]  # Same price as bid - INVALID!

        # Validation logic
        is_valid = len(bids) > 0 and len(asks) > 0 and bids[0][0] < asks[0][0]

        assert is_valid is False, "Should reject equal bid and ask"

    def test_validation_rejects_empty_bids(self):
        """Test validation rejects empty bids"""
        bids = []
        asks = [(100.06, 12.0)]

        # Validation logic
        is_valid = len(bids) > 0 and len(asks) > 0 and bids[0][0] < asks[0][0]

        assert is_valid is False

    def test_validation_rejects_empty_asks(self):
        """Test validation rejects empty asks"""
        bids = [(100.05, 10.0)]
        asks = []

        # Validation logic
        is_valid = len(bids) > 0 and len(asks) > 0 and bids[0][0] < asks[0][0]

        assert is_valid is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
