"""
Pytest configuration and shared fixtures for converter tests
"""

import gzip
import tempfile
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_gateio_orderbook_data():
    """
    Sample Gate.io orderbook data (incremental updates)

    Format: Timestamp, Side, Action, Price, Amount, Begin_Id, Merged
    Side: 1 = Ask (sell), 2 = Bid (buy)
    Action: 'set' (baseline), 'make' (add), 'take' (remove)

    Note: Timestamps are seconds since epoch. The test uses base_date = 2025-09-01 00:00:00 UTC
    which is epoch timestamp 1725148800. We start at 0.250 seconds after midnight to trigger snapshots.
    """
    base_epoch = 1725148800  # 2025-09-01 00:00:00 UTC
    return [
        # Initial snapshot (action='set') at 250ms
        (base_epoch + 0.250, 2, 'set', 100.05, 10.0, 1, False),  # Bid 100.05 @ 10.0
        (base_epoch + 0.250, 2, 'set', 100.04, 15.0, 2, False),  # Bid 100.04 @ 15.0
        (base_epoch + 0.250, 2, 'set', 100.03, 20.0, 3, False),  # Bid 100.03 @ 20.0
        (base_epoch + 0.250, 1, 'set', 100.06, 12.0, 4, False),  # Ask 100.06 @ 12.0
        (base_epoch + 0.250, 1, 'set', 100.07, 18.0, 5, False),  # Ask 100.07 @ 18.0
        (base_epoch + 0.250, 1, 'set', 100.08, 22.0, 6, False),  # Ask 100.08 @ 22.0

        # Incremental update - add liquidity (action='make') at 500ms
        (base_epoch + 0.500, 2, 'make', 100.02, 25.0, 7, False),  # Add Bid 100.02 @ 25.0
        (base_epoch + 0.500, 1, 'make', 100.09, 28.0, 8, False),  # Add Ask 100.09 @ 28.0

        # Incremental update - remove liquidity (action='take') at 800ms
        (base_epoch + 0.800, 2, 'take', 100.05, 5.0, 9, False),   # Take 5.0 from Bid 100.05
        (base_epoch + 0.800, 1, 'take', 100.06, 2.0, 10, False),  # Take 2.0 from Ask 100.06
    ]


@pytest.fixture
def sample_gateio_crossed_spread_data():
    """
    Sample data that creates a crossed spread (bid >= ask)
    This simulates the AAPLXUSD error case
    """
    return [
        # Snapshot with crossed spread
        (1693526400.123, 2, 'set', 252.75, 10.0, 1, False),  # Bid 252.75 (HIGHER)
        (1693526400.123, 1, 'set', 252.70, 12.0, 2, False),  # Ask 252.70 (LOWER) - CROSSED!
    ]


@pytest.fixture
def sample_gateio_unsorted_data():
    """
    Sample data with unsorted bids/asks to test sorting logic
    """
    return [
        # Bids in random order
        (1693526400.123, 2, 'set', 100.03, 20.0, 1, False),
        (1693526400.123, 2, 'set', 100.05, 10.0, 2, False),
        (1693526400.123, 2, 'set', 100.01, 30.0, 3, False),
        (1693526400.123, 2, 'set', 100.04, 15.0, 4, False),

        # Asks in random order
        (1693526400.123, 1, 'set', 100.08, 22.0, 5, False),
        (1693526400.123, 1, 'set', 100.06, 12.0, 6, False),
        (1693526400.123, 1, 'set', 100.09, 28.0, 7, False),
        (1693526400.123, 1, 'set', 100.07, 18.0, 8, False),
    ]


@pytest.fixture
def sample_gateio_csv_file(temp_dir, sample_gateio_orderbook_data):
    """
    Create a sample Gate.io CSV file for testing

    Args:
        temp_dir: Temporary directory fixture
        sample_gateio_orderbook_data: Sample orderbook data

    Returns:
        Path to the created CSV.gz file
    """
    # Create DataFrame
    df = pd.DataFrame(
        sample_gateio_orderbook_data,
        columns=['Timestamp', 'Side', 'Action', 'Price', 'Amount', 'Begin_Id', 'Merged']
    )

    # Create CSV file
    csv_file = temp_dir / 'AAPLX_USDT-2025090100.csv.gz'

    with gzip.open(csv_file, 'wt') as f:
        df.to_csv(f, index=False, header=False)

    return csv_file


@pytest.fixture
def expected_lean_format():
    """
    Expected LEAN format structure

    Format: milliseconds, bid1_price, bid1_size, ..., ask1_price, ask1_size, ...
    """
    return {
        'columns': [
            'milliseconds',
            'bid1_price', 'bid1_size',
            'bid2_price', 'bid2_size',
            'bid3_price', 'bid3_size',
            'bid4_price', 'bid4_size',
            'bid5_price', 'bid5_size',
            'bid6_price', 'bid6_size',
            'bid7_price', 'bid7_size',
            'bid8_price', 'bid8_size',
            'bid9_price', 'bid9_size',
            'bid10_price', 'bid10_size',
            'ask1_price', 'ask1_size',
            'ask2_price', 'ask2_size',
            'ask3_price', 'ask3_size',
            'ask4_price', 'ask4_size',
            'ask5_price', 'ask5_size',
            'ask6_price', 'ask6_size',
            'ask7_price', 'ask7_size',
            'ask8_price', 'ask8_size',
            'ask9_price', 'ask9_size',
            'ask10_price', 'ask10_size',
        ]
    }


@pytest.fixture
def base_date():
    """Base date for timestamp conversion (midnight UTC)"""
    return pd.Timestamp('2025-09-01', tz='UTC')
