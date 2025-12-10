#!/usr/bin/env python
"""
Gate.io Data Collector CLI

Interactive command-line interface for downloading Gate.io historical market data.
Supports crypto (spot) and cryptofuture (USDT-margined perpetual futures) markets.
Supports orderbook (incremental depth) and trade (transaction records) data types.

Usage:
    python scripts/data_collector.py

The CLI will guide you through:
1. Selecting market type (crypto/cryptofuture/both)
2. Selecting data type (orderbook/trade/both)
3. Entering symbols to download
4. Setting date range
5. Configuring concurrent workers
6. Setting output directories

Example output structure:
    raw_data/
    ├── gate_orderbook_tick/
    │   ├── crypto/202509/SYMBOL-YYYYMMDDHH.csv.gz
    │   └── cryptofuture/202509/SYMBOL-YYYYMMDDHH.csv.gz
    └── gate_trade_tick/
        ├── crypto/202509/SYMBOL-YYYYMM.csv.gz
        └── cryptofuture/202509/SYMBOL-YYYYMM.csv.gz
"""

import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.collectors.gate_collector import GateCollector, DownloadConfig, DownloadStats


class GateDataCollectorCLI:
    """Interactive CLI for Gate.io data collection"""

    # Market type options
    MARKET_TYPES = {
        '1': ('crypto', 'Crypto (Spot)'),
        '2': ('cryptofuture', 'Crypto Futures (USDT-margined perpetual)'),
        '3': ('both', 'Both Crypto and Crypto Futures')
    }

    # Data type options
    DATA_TYPES = {
        '1': ('orderbook', 'Orderbook (Incremental Depth Updates - Hourly)'),
        '2': ('trade', 'Trade (Transaction Records - Monthly)'),
        '3': ('funding_apply', 'Funding Apply (Funding Rate Records - Monthly, Futures Only)'),
        '4': ('all', 'All Data Types (Orderbook + Trade + Funding Apply)')
    }

    # Default configuration
    DEFAULT_SYMBOLS = ['TSLAX_USDT', 'AAPLX_USDT']
    DEFAULT_START_DATE = '2025-09-01'
    DEFAULT_CONCURRENT_WORKERS = 5
    DEFAULT_ORDERBOOK_OUTPUT = 'raw_data/gate_orderbook_tick'
    DEFAULT_TRADE_OUTPUT = 'raw_data/gate_trade_tick'
    DEFAULT_FUNDING_APPLY_OUTPUT = 'raw_data/gate_funding_apply'

    def __init__(self):
        """Initialize CLI"""
        self.market_types_selected = []
        self.data_types_selected = []
        self.symbols = []
        self.start_date = None
        self.end_date = None
        self.concurrent_workers = self.DEFAULT_CONCURRENT_WORKERS
        self.orderbook_output = self.DEFAULT_ORDERBOOK_OUTPUT
        self.trade_output = self.DEFAULT_TRADE_OUTPUT
        self.funding_apply_output = self.DEFAULT_FUNDING_APPLY_OUTPUT

    def print_header(self, text: str, width: int = 60):
        """Print formatted header"""
        print(f"\n{'=' * width}")
        print(text)
        print(f"{'=' * width}\n")

    def print_step(self, step_num: int, text: str):
        """Print step header"""
        print(f"\nStep {step_num}: {text}")
        print("-" * 40)

    def get_input(self, prompt: str, default: str = None) -> str:
        """Get user input with optional default value"""
        if default:
            user_input = input(f"{prompt} [{default}]: ").strip()
            return user_input if user_input else default
        return input(f"{prompt}: ").strip()

    def select_market_type(self) -> bool:
        """
        Step 1: Select market type(s)

        Returns:
            True if selection successful, False to exit
        """
        self.print_step(1, "Select Market Type")

        for key, (value, desc) in self.MARKET_TYPES.items():
            print(f"  [{key}] {desc}")

        while True:
            choice = self.get_input("\nPlease select (1-3)").strip()

            if choice in self.MARKET_TYPES:
                market_type, desc = self.MARKET_TYPES[choice]

                if market_type == 'both':
                    self.market_types_selected = ['crypto', 'cryptofuture']
                else:
                    self.market_types_selected = [market_type]

                print(f"Selected: {desc}")
                return True
            else:
                print("Invalid selection. Please choose 1, 2, or 3.")

    def select_data_type(self) -> bool:
        """
        Step 2: Select data type(s)

        Returns:
            True if selection successful, False to exit
        """
        self.print_step(2, "Select Data Type")

        for key, (value, desc) in self.DATA_TYPES.items():
            print(f"  [{key}] {desc}")

        while True:
            choice = self.get_input("\nPlease select (1-4)").strip()

            if choice in self.DATA_TYPES:
                data_type, desc = self.DATA_TYPES[choice]

                if data_type == 'all':
                    self.data_types_selected = ['orderbook', 'trade', 'funding_apply']
                else:
                    self.data_types_selected = [data_type]

                print(f"Selected: {desc}")
                return True
            else:
                print("Invalid selection. Please choose 1-4.")

    def configure_symbols(self) -> bool:
        """
        Step 3: Configure symbols

        Returns:
            True if configuration successful, False to exit
        """
        self.print_step(3, "Enter Symbols")

        default_symbols_str = ','.join(self.DEFAULT_SYMBOLS)
        symbols_input = self.get_input(
            "Enter symbols (comma-separated)",
            default_symbols_str
        )

        # Parse symbols
        self.symbols = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]

        if not self.symbols:
            print("Error: At least one symbol is required")
            return False

        print(f"Symbols: {', '.join(self.symbols)}")
        return True

    def configure_date_range(self) -> bool:
        """
        Step 4: Configure date range

        Returns:
            True if configuration successful, False to exit
        """
        self.print_step(4, "Enter Date Range")

        # Start date
        while True:
            start_date_str = self.get_input(
                "Start date (YYYY-MM-DD)",
                self.DEFAULT_START_DATE
            )

            try:
                self.start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
                break
            except ValueError:
                print(f"Invalid date format: {start_date_str}. Please use YYYY-MM-DD")

        # End date
        default_end_date = datetime.now().strftime("%Y-%m-%d")
        while True:
            end_date_str = self.get_input(
                "End date (YYYY-MM-DD)",
                default_end_date
            )

            try:
                self.end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

                # Validate date range
                if self.end_date < self.start_date:
                    print("Error: End date must be on or after start date")
                    continue

                break
            except ValueError:
                print(f"Invalid date format: {end_date_str}. Please use YYYY-MM-DD")

        print(f"Date range: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}")
        return True

    def configure_workers(self) -> bool:
        """
        Step 5: Configure concurrent workers

        Returns:
            True if configuration successful, False to exit
        """
        self.print_step(5, "Concurrent Workers")

        while True:
            workers_str = self.get_input(
                "Number of concurrent downloads (1-20)",
                str(self.DEFAULT_CONCURRENT_WORKERS)
            )

            try:
                workers = int(workers_str)
                if 1 <= workers <= 20:
                    self.concurrent_workers = workers
                    print(f"Concurrent workers: {workers}")
                    return True
                else:
                    print("Please enter a number between 1 and 20")
            except ValueError:
                print(f"Invalid number: {workers_str}")

    def configure_output_dirs(self) -> bool:
        """
        Step 6: Configure output directories

        Returns:
            True if configuration successful, False to exit
        """
        self.print_step(6, "Output Directories")

        # Orderbook output (if needed)
        if 'orderbook' in self.data_types_selected:
            self.orderbook_output = self.get_input(
                "Orderbook output directory",
                self.DEFAULT_ORDERBOOK_OUTPUT
            )
            print(f"Orderbook output: {self.orderbook_output}")

        # Trade output (if needed)
        if 'trade' in self.data_types_selected:
            self.trade_output = self.get_input(
                "Trade output directory",
                self.DEFAULT_TRADE_OUTPUT
            )
            print(f"Trade output: {self.trade_output}")

        # Funding Apply output (if needed)
        if 'funding_apply' in self.data_types_selected:
            self.funding_apply_output = self.get_input(
                "Funding Apply output directory",
                self.DEFAULT_FUNDING_APPLY_OUTPUT
            )
            print(f"Funding Apply output: {self.funding_apply_output}")

        return True

    def show_summary(self):
        """Display configuration summary"""
        self.print_header("Download Configuration Summary")

        # Market types
        market_desc = ', '.join([self.MARKET_TYPES[k][1] for k, (v, d) in self.MARKET_TYPES.items()
                                 if v in self.market_types_selected or
                                 (v == 'both' and set(self.market_types_selected) == {'crypto', 'cryptofuture'})])
        print(f"Market Type(s): {market_desc}")

        # Data types
        data_desc = ', '.join([self.DATA_TYPES[k][1] for k, (v, d) in self.DATA_TYPES.items()
                               if v in self.data_types_selected or
                               (v == 'both' and set(self.data_types_selected) == {'orderbook', 'trade'})])
        print(f"Data Type(s): {data_desc}")

        # Symbols
        print(f"Symbols: {', '.join(self.symbols)}")

        # Date range
        print(f"Date Range: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}")

        # Workers
        print(f"Concurrent Workers: {self.concurrent_workers}")

        # Output paths
        print(f"\nOutput Directories:")
        if 'orderbook' in self.data_types_selected:
            for market_type in self.market_types_selected:
                year_month = self.start_date.strftime('%Y%m')
                print(f"  - Orderbook ({market_type}): {self.orderbook_output}/{market_type}/{year_month}/")

        if 'trade' in self.data_types_selected:
            for market_type in self.market_types_selected:
                year_month = self.start_date.strftime('%Y%m')
                print(f"  - Trade ({market_type}): {self.trade_output}/{market_type}/{year_month}/")

        if 'funding_apply' in self.data_types_selected:
            # Funding apply is only for cryptofuture
            if 'cryptofuture' in self.market_types_selected:
                year_month = self.start_date.strftime('%Y%m')
                print(f"  - Funding Apply (cryptofuture): {self.funding_apply_output}/cryptofuture/{year_month}/")

        print()

    def confirm_download(self) -> bool:
        """
        Ask user to confirm download

        Returns:
            True to proceed, False to cancel
        """
        while True:
            response = self.get_input("Confirm download? [Y/n]", "Y").lower()

            if response in ['y', 'yes', '']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print("Please enter Y or N")

    def execute_download(self, market_type: str, data_type: str) -> DownloadStats:
        """
        Execute download for a single market type and data type combination

        Args:
            market_type: 'crypto' or 'cryptofuture'
            data_type: 'orderbook', 'trade', or 'funding_apply'

        Returns:
            DownloadStats from the download operation
        """
        # Determine output directory
        if data_type == 'orderbook':
            output_dir = self.orderbook_output
        elif data_type == 'trade':
            output_dir = self.trade_output
        else:  # funding_apply
            output_dir = self.funding_apply_output

        # Create configuration
        config = DownloadConfig(
            market_type=market_type,
            data_type=data_type,
            symbols=self.symbols,
            start_date=self.start_date,
            end_date=self.end_date,
            concurrent_workers=self.concurrent_workers,
            output_dir=output_dir
        )

        # Create collector and execute
        print(f"\n{'='*60}")
        print(f"Downloading {market_type} {data_type} data...")
        print(f"{'='*60}\n")

        collector = GateCollector(config)
        return collector.execute_downloads()

    def run(self):
        """Run the interactive CLI"""
        self.print_header("Gate.io Data Downloader")

        # Configuration wizard
        if not self.select_market_type():
            return

        if not self.select_data_type():
            return

        if not self.configure_symbols():
            return

        if not self.configure_date_range():
            return

        if not self.configure_workers():
            return

        if not self.configure_output_dirs():
            return

        # Show summary and confirm
        self.show_summary()

        if not self.confirm_download():
            print("Download cancelled.")
            return

        # Execute downloads
        all_stats = []

        for market_type in self.market_types_selected:
            for data_type in self.data_types_selected:
                # Skip funding_apply for crypto market (only available for cryptofuture)
                if data_type == 'funding_apply' and market_type != 'cryptofuture':
                    print(f"\n⚠️  Skipping funding_apply for {market_type} (only available for cryptofuture)")
                    continue

                stats = self.execute_download(market_type, data_type)
                all_stats.append((market_type, data_type, stats))

        # Final summary
        self.print_header("Final Summary - All Downloads")

        total_successful = 0
        total_failed = 0
        total_skipped = 0
        total_time = 0

        for market_type, data_type, stats in all_stats:
            print(f"\n{market_type.upper()} {data_type.upper()}:")
            print(f"  Total: {stats.total}")
            print(f"  Successful: {stats.successful}")
            print(f"  Failed: {stats.failed}")
            print(f"  Skipped (404): {stats.skipped}")
            print(f"  Time: {stats.total_time_seconds / 60:.1f} minutes")

            total_successful += stats.successful
            total_failed += stats.failed
            total_skipped += stats.skipped
            total_time += stats.total_time_seconds

        print(f"\n{'='*60}")
        print(f"GRAND TOTAL:")
        print(f"  Successful: {total_successful}")
        print(f"  Failed: {total_failed}")
        print(f"  Skipped (404): {total_skipped}")
        print(f"  Total time: {total_time / 60:.1f} minutes")
        print(f"{'='*60}\n")

        if total_failed > 0:
            print(f"⚠️  {total_failed} downloads failed. Check logs for details.")
        else:
            print("✅ All downloads completed successfully!")


def main():
    """Main entry point"""
    try:
        cli = GateDataCollectorCLI()
        cli.run()
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
