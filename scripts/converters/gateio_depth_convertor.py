"""
Gate.io Orderbook Depth Converter for LEAN
Converts Gate.io incremental orderbook data to LEAN format (Kraken-style)
"""

import argparse
import gzip
import logging
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Symbol mapping: Gate.io → Gate LEAN format
SYMBOL_MAP = {
    'AAPLX_USDT': 'AAPLXUSDT',  # Fixed: Added 'T' suffix for correct LEAN symbol
    'TSLAX_USDT': 'TSLAXUSDT',  # Fixed: Added 'T' suffix for correct LEAN symbol
    'BTC_USDT': 'BTCUSDT',      # Bitcoin
    'ETH_USDT': 'ETHUSDT',      # Ethereum
    'BNB_USDT': 'BNBUSDT',      # Binance Coin
}

# Configuration
DEPTH_LEVELS = 10  # Output 10 levels of depth
SNAPSHOT_INTERVAL_MS = 250  # Output snapshot every 250ms
ALLOW_CROSSED_SPREAD = False  # If True, allow snapshots with crossed spreads (bid >= ask)
                              # Set to True if you want to keep all data despite market anomalies


class OrderbookBuilder:
    """
    Rebuilds orderbook from Gate.io incremental updates

    Gate.io provides:
    1. Initial snapshot (action='set')
    2. Incremental updates (action='make'/'take')

    We need to maintain full orderbook state and output snapshots.
    """

    def __init__(self):
        self.bids = {}  # {price: amount}
        self.asks = {}  # {price: amount}
        self.last_snapshot_time = 0

    def reset(self):
        """Reset orderbook state"""
        self.bids.clear()
        self.asks.clear()
        self.last_snapshot_time = 0

    def apply_update(self, timestamp, side, action, price, amount):
        """
        Apply a single orderbook update

        Args:
            timestamp: Unix timestamp (seconds with 1 decimal)
            side: 1 (ask/sell) or 2 (bid/buy)
            action: 'set', 'make', or 'take'
            price: Price level
            amount: Amount at this price level
        """
        # Determine which side to update
        book = self.asks if side == 1 else self.bids

        # Tolerance for floating point comparison (1e-10 for crypto amounts)
        EPSILON = 1e-10

        if action == 'set':
            # Set baseline: replace current amount
            if amount > EPSILON:
                book[price] = amount
            else:
                book.pop(price, None)

        elif action == 'make':
            # Add to existing amount
            book[price] = book.get(price, 0) + amount
            if book[price] <= EPSILON:
                book.pop(price, None)

        elif action == 'take':
            # Subtract from existing amount
            current = book.get(price, 0)
            new_amount = current - amount
            if new_amount > EPSILON:
                book[price] = new_amount
            else:
                book.pop(price, None)

    def should_output_snapshot(self, timestamp_ms):
        """
        Check if we should output a snapshot based on time interval

        Args:
            timestamp_ms: Current timestamp in milliseconds

        Returns:
            bool: True if should output snapshot
        """
        if timestamp_ms - self.last_snapshot_time >= SNAPSHOT_INTERVAL_MS:
            self.last_snapshot_time = timestamp_ms
            return True
        return False

    def get_snapshot(self, levels=10):
        """
        Get current orderbook snapshot with top N levels

        Args:
            levels: Number of levels to output (default 10)

        Returns:
            tuple: (bids_list, asks_list)
                bids_list: [(price, size), ...] sorted descending (best first)
                asks_list: [(price, size), ...] sorted ascending (best first)
        """
        # Sort and get top N levels
        # Bids: descending order (highest price first)
        bids_sorted = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:levels]

        # Asks: ascending order (lowest price first)
        asks_sorted = sorted(self.asks.items(), key=lambda x: x[0])[:levels]

        return bids_sorted, asks_sorted

    def validate_snapshot(self, bids, asks):
        """
        Validate orderbook snapshot for common errors

        Args:
            bids: List of (price, size) tuples
            asks: List of (price, size) tuples

        Returns:
            tuple: (is_valid: bool, error_message: str or None)
        """
        # Check if both sides have data
        if not bids or not asks:
            return False, "Empty orderbook - missing bids or asks"

        # Check for crossed spread (bid >= ask)
        best_bid_price = bids[0][0]
        best_ask_price = asks[0][0]

        if best_bid_price >= best_ask_price:
            return False, f"Crossed spread detected: bid={best_bid_price}, ask={best_ask_price}"

        # Validate bids are sorted descending
        for i in range(len(bids) - 1):
            if bids[i][0] <= bids[i + 1][0]:
                return False, f"Bids not sorted descending: {bids[i][0]} <= {bids[i + 1][0]}"

        # Validate asks are sorted ascending
        for i in range(len(asks) - 1):
            if asks[i][0] >= asks[i + 1][0]:
                return False, f"Asks not sorted ascending: {asks[i][0]} >= {asks[i + 1][0]}"

        return True, None

    def format_lean_row(self, timestamp_ms, bids, asks):
        """
        Format orderbook snapshot as LEAN CSV row

        LEAN Format:
        milliseconds,bid1_price,bid1_size,bid2_price,bid2_size,...,ask1_price,ask1_size,...

        Args:
            timestamp_ms: Milliseconds since midnight
            bids: List of (price, size) tuples
            asks: List of (price, size) tuples

        Returns:
            list: CSV row as list of values
        """
        row = [timestamp_ms]

        # Add bid levels
        for price, size in bids:
            row.extend([price, size])

        # Pad bids if less than required levels
        for _ in range(DEPTH_LEVELS - len(bids)):
            row.extend([0, 0])

        # Add ask levels
        for price, size in asks:
            row.extend([price, size])

        # Pad asks if less than required levels
        for _ in range(DEPTH_LEVELS - len(asks)):
            row.extend([0, 0])

        return row


def scan_files(data_dir, pattern="*.csv.gz"):
    """
    Scan directory for data files

    Args:
        data_dir: Data directory path
        pattern: File matching pattern

    Returns:
        list: List of Path objects
    """
    data_path = Path(data_dir)

    if not data_path.exists():
        logger.warning(f"Directory not found: {data_path}")
        return []

    files = sorted(data_path.glob(pattern))
    logger.info(f"Found {len(files)} files in {data_path}")

    return files


def parse_filename(filename):
    """
    Parse Gate.io filename to extract symbol and datetime

    Filename format: AAPL_USDT-2023042504.csv.gz

    Args:
        filename: Filename string

    Returns:
        dict: {'symbol': str, 'date': str, 'hour': str} or None
    """
    import re

    # Pattern: SYMBOL-YYYYMMDDHH.csv.gz
    pattern = r"(.+)-(\d{10})\.csv\.gz$"
    match = re.match(pattern, filename)

    if match:
        symbol = match.group(1)
        datetime_str = match.group(2)

        # Extract date and hour
        date = datetime_str[:8]  # YYYYMMDD
        hour = datetime_str[8:10]  # HH

        return {
            'symbol': symbol,
            'date': date,
            'hour': hour
        }

    logger.warning(f"Cannot parse filename: {filename}")
    return None


def process_hourly_file(src_file, base_date):
    """
    Process a single hourly file and return snapshots

    Args:
        src_file: Source file path (csv.gz)
        base_date: Base date for timestamp calculation (pd.Timestamp)

    Returns:
        list: List of snapshot rows, or None if error
    """
    # Read Gate.io data (no header in CSV)
    # Spot format (7 columns): timestamp,side,action,price,amount,begin_id,merged (side: 1=ask, 2=bid)
    # Future format (6 columns): timestamp,action,price,size,begin_id,merged (size: positive=bid, negative=ask)
    try:
        with gzip.open(src_file, 'rt') as f:
            df_raw = pd.read_csv(f, header=None)
    except Exception as e:
        logger.error(f"Failed to read {src_file.name}: {e}")
        return None

    if df_raw.empty:
        logger.warning(f"No data in {src_file.name}")
        return None

    # Detect format based on column count
    num_cols = len(df_raw.columns)

    if num_cols == 7:
        # Spot format: timestamp,side,action,price,amount,begin_id,merged
        df_raw.columns = ['Timestamp', 'Side', 'Action', 'Price', 'Amount', 'Begin_Id', 'Merged']
        logger.debug(f"  Detected spot format (7 columns)")
        df = df_raw.copy()
    elif num_cols == 6:
        # Future format: timestamp,action,price,size,begin_id,merged (signed size)
        df_raw.columns = ['Timestamp', 'Action', 'Price', 'Size', 'Begin_Id', 'Merged']
        logger.debug(f"  Detected future format (6 columns)")

        # Convert signed size to amount + side
        df = df_raw.copy()
        df['Amount'] = df['Size'].abs()
        # Positive size = bid (side=2), negative size = ask (side=1)
        df['Side'] = (df['Size'] > 0).astype(int) + 1  # True->2, False->1
    else:
        logger.error(f"Unexpected column count: {num_cols}, expected 6 or 7")
        return None

    # Build orderbook and collect snapshots
    builder = OrderbookBuilder()
    snapshots = []

    # Group updates by timestamp to ensure atomic processing
    # This prevents outputting snapshots in the middle of processing updates for the same timestamp
    current_timestamp = None
    current_timestamp_ms = None

    # Use itertuples for better performance (10-100x faster than iterrows)
    for row in df.itertuples(index=False):
        timestamp = row.Timestamp
        side = int(row.Side)
        action = row.Action
        price = float(row.Price)
        amount = float(row.Amount)

        # Convert timestamp to milliseconds since midnight
        timestamp_dt = pd.Timestamp(timestamp, unit='s', tz='UTC')
        time_delta = timestamp_dt - base_date
        timestamp_ms = int(time_delta.total_seconds() * 1000)

        # Check if we've moved to a new timestamp
        if current_timestamp is not None and timestamp != current_timestamp:
            # We've finished processing all updates for the previous timestamp
            # Now check if we should output a snapshot for it
            if builder.should_output_snapshot(current_timestamp_ms):
                # Get top N levels
                bids, asks = builder.get_snapshot(levels=DEPTH_LEVELS)

                # Skip if orderbook is empty
                if bids and asks:
                    # Validate snapshot before writing
                    is_valid, error_msg = builder.validate_snapshot(bids, asks)
                    if not is_valid:
                        if not ALLOW_CROSSED_SPREAD:
                            logger.debug(f"  Skipping invalid snapshot at {current_timestamp_ms}ms: {error_msg}")
                        else:
                            # Allow crossed spreads if configured
                            row_data = builder.format_lean_row(current_timestamp_ms, bids, asks)
                            snapshots.append(row_data)
                    else:
                        # Format as LEAN row
                        row_data = builder.format_lean_row(current_timestamp_ms, bids, asks)
                        snapshots.append(row_data)

        # Update current timestamp tracking
        current_timestamp = timestamp
        current_timestamp_ms = timestamp_ms

        # Apply update to orderbook
        builder.apply_update(timestamp, side, action, price, amount)

    # Don't forget to process the last timestamp group
    if current_timestamp is not None:
        if builder.should_output_snapshot(current_timestamp_ms):
            bids, asks = builder.get_snapshot(levels=DEPTH_LEVELS)

            if bids and asks:
                is_valid, error_msg = builder.validate_snapshot(bids, asks)
                if not is_valid:
                    if not ALLOW_CROSSED_SPREAD:
                        logger.debug(f"  Skipping invalid snapshot at {current_timestamp_ms}ms: {error_msg}")
                    else:
                        row_data = builder.format_lean_row(current_timestamp_ms, bids, asks)
                        snapshots.append(row_data)
                else:
                    row_data = builder.format_lean_row(current_timestamp_ms, bids, asks)
                    snapshots.append(row_data)

    return snapshots


def convert_daily_orderbook_depth(date_files, dst_root, lean_symbol, date_str):
    """
    Convert all hourly files for a single day into one LEAN depth file

    Args:
        date_files: List of hourly files for this date
        dst_root: Output root directory
        lean_symbol: LEAN symbol name
        date_str: Date string (YYYYMMDD)
    """
    logger.info(f"\n📅 Processing {lean_symbol} for {date_str} ({len(date_files)} hours)")

    # Get base date (midnight of this day in UTC)
    base_date = pd.Timestamp(date_str, tz='UTC')

    # Collect all snapshots for this day
    all_snapshots = []

    for src_file in sorted(date_files):
        metadata = parse_filename(src_file.name)
        hour_str = metadata['hour']
        logger.info(f"  Hour {hour_str}: Processing {src_file.name}...")

        snapshots = process_hourly_file(src_file, base_date)

        if snapshots:
            all_snapshots.extend(snapshots)
            logger.info(f"  Hour {hour_str}: Generated {len(snapshots)} snapshots")
        else:
            logger.warning(f"  Hour {hour_str}: No snapshots generated")

    if not all_snapshots:
        logger.warning(f"❌ No valid snapshots for {date_str}")
        return

    # Create output DataFrame
    columns = ['milliseconds']
    for i in range(1, DEPTH_LEVELS + 1):
        columns.extend([f'bid{i}_price', f'bid{i}_size'])
    for i in range(1, DEPTH_LEVELS + 1):
        columns.extend([f'ask{i}_price', f'ask{i}_size'])

    out_df = pd.DataFrame(all_snapshots, columns=columns)

    # Remove duplicate timestamps (keep last)
    out_df = out_df.drop_duplicates(subset=['milliseconds'], keep='last')

    # Sort by timestamp
    out_df = out_df.sort_values('milliseconds').reset_index(drop=True)

    logger.info(f"  📊 Total snapshots for {date_str}: {len(out_df)}")

    # Create output directory
    dst_dir = Path(dst_root) / lean_symbol.lower()
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Output filenames
    # Follow LEAN standard naming: {date}_{symbol}_{resolution}_{datatype}.csv
    zip_filename = f"{date_str}_depth.zip"
    csv_filename = f"{date_str}_{lean_symbol.lower()}_tick_depth.csv"
    zip_path = dst_dir / zip_filename

    # Write to zip file
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        with zf.open(csv_filename, 'w') as f:
            # Write without header
            out_df.to_csv(f, index=False, header=False)

    logger.info(f"  ✅ Created: {zip_path} ({len(out_df)} snapshots)")


def main_convert(input_dir=None, output_dir=None, symbol=None, market_type='crypto'):
    """
    Main conversion function (can be called from other scripts)

    Args:
        input_dir: Input directory containing Gate.io CSV files
        output_dir: Output directory for LEAN data
        symbol: Specific symbol to convert (Gate.io format)
        market_type: Market type - 'crypto' (spot) or 'cryptofuture' (futures_usdt)
    """
    # Use defaults if not provided
    if input_dir is None:
        input_dir = 'raw_data/gate_orderbook_tick/202509'
    if output_dir is None:
        output_dir = f'Data/{market_type}/gate/tick'

    # Determine target symbols
    if symbol:
        target_symbols = [symbol]
    else:
        target_symbols = list(SYMBOL_MAP.keys())

    logger.info("=" * 60)
    logger.info("Gate.io Orderbook Depth Converter for LEAN")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_dir}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Symbols: {', '.join(target_symbols)}")
    logger.info(f"Depth Levels: {DEPTH_LEVELS}")
    logger.info(f"Snapshot Interval: {SNAPSHOT_INTERVAL_MS}ms")
    logger.info("=" * 60)

    # Scan for files
    files = scan_files(input_dir, "*.csv.gz")

    if not files:
        logger.error("No files found!")
        return

    # Group files by (symbol, date)
    files_by_symbol_date = defaultdict(lambda: defaultdict(list))

    for file in files:
        metadata = parse_filename(file.name)
        if not metadata:
            continue

        gate_symbol = metadata['symbol']
        date_str = metadata['date']

        # Check if this symbol is in our target list
        if target_symbols and gate_symbol not in target_symbols:
            continue

        # Check if we have a mapping for this symbol
        if gate_symbol not in SYMBOL_MAP:
            continue

        files_by_symbol_date[gate_symbol][date_str].append(file)

    # Process each symbol-date combination
    for gate_symbol in sorted(files_by_symbol_date.keys()):
        lean_symbol = SYMBOL_MAP[gate_symbol]
        logger.info(f"\n{'='*60}")
        logger.info(f"Symbol: {gate_symbol} → {lean_symbol}")
        logger.info(f"{'='*60}")

        dates_dict = files_by_symbol_date[gate_symbol]

        for date_str in sorted(dates_dict.keys()):
            date_files = dates_dict[date_str]
            convert_daily_orderbook_depth(
                date_files,
                output_dir,
                lean_symbol,
                date_str
            )

    logger.info("\n" + "=" * 60)
    logger.info("✅ Conversion Complete!")
    logger.info("=" * 60)


def main():
    """
    Main function for command-line usage
    """
    parser = argparse.ArgumentParser(
        description='Convert Gate.io orderbook depth to LEAN format (Kraken-style)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all target symbols
  python gateio_depth_convertor.py

  # Convert specific symbol
  python gateio_depth_convertor.py --symbol AAPLX_USDT

  # Custom input/output paths
  python gateio_depth_convertor.py --input raw_data/gate_tick/202509 --output Data/crypto/kraken/tick
        """
    )

    parser.add_argument(
        '--input',
        default='raw_data/gate_orderbook_tick/202509',
        help='Input directory containing Gate.io CSV files (default: raw_data/gate_orderbook_tick/202509)'
    )

    parser.add_argument(
        '--output',
        default='Data/crypto/kraken/tick',
        help='Output directory for LEAN data (default: Data/crypto/kraken/tick)'
    )

    parser.add_argument(
        '--symbol',
        help='Specific symbol to convert (Gate.io format, e.g., AAPLX_USDT). If not specified, converts all mapped symbols.'
    )

    args = parser.parse_args()

    # Call main conversion function
    main_convert(
        input_dir=args.input,
        output_dir=args.output,
        symbol=args.symbol
    )


if __name__ == "__main__":
    main()
