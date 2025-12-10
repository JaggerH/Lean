#!/usr/bin/env python
"""
Gate.io Data Collector

Downloads historical market data from Gate.io's public data archive.
Supports both crypto (spot) and cryptofuture (USDT-margined perpetual futures) markets.
Supports orderbook (incremental depth updates) and trade (transaction records) data types.

Usage:
    from collectors.gate_collector import GateCollector, DownloadConfig

    config = DownloadConfig(
        market_type='crypto',
        data_type='orderbook',
        symbols=['TSLAX_USDT', 'AAPLX_USDT'],
        start_date=datetime(2025, 9, 1),
        end_date=datetime(2025, 9, 30),
        concurrent_workers=5,
        output_dir='raw_data/gate_orderbook_tick'
    )

    collector = GateCollector(config)
    stats = collector.execute_downloads()
    print(f"Success: {stats.successful}, Failed: {stats.failed}, Skipped: {stats.skipped}")
"""

import gzip
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class DownloadConfig:
    """Configuration for download operation"""
    market_type: str  # 'crypto' or 'cryptofuture'
    data_type: str  # 'orderbook' or 'trade'
    symbols: List[str]  # ['TSLAX_USDT', 'AAPLX_USDT']
    start_date: datetime
    end_date: datetime
    concurrent_workers: int = 5
    output_dir: str = 'raw_data'


@dataclass
class DownloadTask:
    """Represents a single file download task"""
    url: str
    local_path: Path
    symbol: str
    date: datetime
    hour: Optional[int] = None  # For hourly files (orderbook)
    file_size: Optional[int] = None


@dataclass
class DownloadResult:
    """Result of a download operation"""
    task: DownloadTask
    success: bool
    skipped: bool = False  # True for 404 (file doesn't exist)
    error_message: Optional[str] = None


@dataclass
class DownloadStats:
    """Statistics for download operation"""
    total: int
    successful: int
    failed: int
    skipped: int
    total_time_seconds: float


class GateCollector:
    """
    Gate.io data collector implementation

    Downloads historical market data from Gate.io's public data archive using ThreadPoolExecutor
    for parallel downloads. Supports crypto (spot) and cryptofuture (futures_usdt) markets,
    with orderbook (hourly) and trade (monthly) data types.
    """

    # Gate.io download base URL
    BASE_URL = "https://download.gatedata.org"

    # Market type mapping: LEAN -> Gate.io API
    MARKET_MAP = {
        'crypto': 'spot',
        'cryptofuture': 'futures_usdt'
    }

    # Data type mapping: LEAN -> Gate.io API
    # Note: trade data type differs between markets:
    #   - crypto (spot): uses 'deals'
    #   - cryptofuture (futures_usdt): uses 'trades'
    DATA_TYPE_MAP = {
        'orderbook': 'orderbooks',
        'trade': {
            'crypto': 'deals',
            'cryptofuture': 'trades'
        }
    }

    # Retry configuration
    MAX_RETRIES = 3
    BACKOFF_FACTOR = 2  # Exponential backoff: 2, 4, 8 seconds

    # File validation
    MIN_FILE_SIZE = 100  # Minimum valid file size in bytes
    GZIP_MAGIC = b'\x1f\x8b'  # Gzip file header

    def __init__(self, config: DownloadConfig):
        """
        Initialize collector with configuration

        Args:
            config: DownloadConfig with market_type, data_type, symbols, dates, etc.
        """
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LEAN-Data-Collector/1.0'
        })

        # Validate configuration
        self._validate_config()

    def _validate_config(self):
        """Validate configuration parameters"""
        if self.config.market_type not in self.MARKET_MAP:
            raise ValueError(f"Invalid market_type: {self.config.market_type}. "
                           f"Must be one of: {list(self.MARKET_MAP.keys())}")

        if self.config.data_type not in self.DATA_TYPE_MAP:
            raise ValueError(f"Invalid data_type: {self.config.data_type}. "
                           f"Must be one of: {list(self.DATA_TYPE_MAP.keys())}")

        if not self.config.symbols:
            raise ValueError("symbols list cannot be empty")

        if self.config.start_date > self.config.end_date:
            raise ValueError("start_date must be before or equal to end_date")

    def build_url(self, symbol: str, year: int, month: int,
                  day: Optional[int] = None, hour: Optional[int] = None) -> str:
        """
        Build Gate.io download URL

        URL patterns:
        - Orderbook (hourly): {BASE}/{biz}/orderbooks/{YYYYMM}/{SYMBOL}-{YYYYMMDDHH}.csv.gz
        - Trade (monthly):
          * Crypto (spot): {BASE}/spot/deals/{YYYYMM}/{SYMBOL}-{YYYYMM}.csv.gz
          * CryptoFuture (futures_usdt): {BASE}/futures_usdt/trades/{YYYYMM}/{SYMBOL}-{YYYYMM}.csv.gz

        Args:
            symbol: Trading pair symbol (e.g., 'TSLAX_USDT')
            year: Year (e.g., 2025)
            month: Month (1-12)
            day: Day of month (1-31) - required for orderbook
            hour: Hour (0-23) - required for orderbook

        Returns:
            Full download URL

        Examples:
            >>> build_url('TSLAX_USDT', 2025, 9, 15, 10)  # Crypto orderbook
            'https://download.gatedata.org/spot/orderbooks/202509/TSLAX_USDT-2025091510.csv.gz'

            >>> build_url('TSLAX_USDT', 2025, 9)  # Crypto trade
            'https://download.gatedata.org/spot/deals/202509/TSLAX_USDT-202509.csv.gz'

            >>> build_url('TSLAX_USDT', 2025, 9)  # CryptoFuture trade
            'https://download.gatedata.org/futures_usdt/trades/202509/TSLAX_USDT-202509.csv.gz'
        """
        # Get Gate.io API naming
        biz = self.MARKET_MAP[self.config.market_type]

        # Get data type API path (trade depends on market type)
        data_type_mapping = self.DATA_TYPE_MAP[self.config.data_type]
        if isinstance(data_type_mapping, dict):
            # Trade data type varies by market
            data_type_api = data_type_mapping[self.config.market_type]
        else:
            # Orderbook is same for all markets
            data_type_api = data_type_mapping

        # Build year-month string
        year_month = f"{year:04d}{month:02d}"

        # Build filename based on data type
        if self.config.data_type == 'orderbook':
            # Hourly files - require day and hour
            if day is None or hour is None:
                raise ValueError("day and hour are required for orderbook data")
            filename = f"{symbol}-{year:04d}{month:02d}{day:02d}{hour:02d}.csv.gz"
        else:  # trade
            # Monthly files
            filename = f"{symbol}-{year_month}.csv.gz"

        # Build full URL
        url = f"{self.BASE_URL}/{biz}/{data_type_api}/{year_month}/{filename}"
        return url

    def generate_tasks(self) -> List[DownloadTask]:
        """
        Generate list of download tasks based on configuration

        For orderbook (hourly granularity):
            - Creates tasks for each hour of each day in date range
            - Example: 2 symbols * 30 days * 24 hours = 1440 tasks

        For trade (monthly granularity):
            - Creates one task per symbol per month
            - Example: 2 symbols * 1 month = 2 tasks

        Returns:
            List of DownloadTask objects
        """
        tasks = []

        # Generate month ranges from start_date to end_date
        current_date = self.config.start_date.replace(day=1)
        end_date = self.config.end_date.replace(day=1)

        while current_date <= end_date:
            year = current_date.year
            month = current_date.month
            year_month = f"{year:04d}{month:02d}"

            # Determine the base output directory
            base_output_dir = Path(self.config.output_dir)
            # Add market type subdirectory
            market_output_dir = base_output_dir / self.config.market_type / year_month

            for symbol in self.config.symbols:
                if self.config.data_type == 'orderbook':
                    # Hourly files - generate tasks for each hour
                    # Determine actual day range for this month
                    if current_date.year == self.config.start_date.year and \
                       current_date.month == self.config.start_date.month:
                        # First month - start from start_date
                        day_start = self.config.start_date.day
                    else:
                        day_start = 1

                    if current_date.year == self.config.end_date.year and \
                       current_date.month == self.config.end_date.month:
                        # Last month - end at end_date
                        day_end = self.config.end_date.day
                    else:
                        # Full month - find last day of month
                        if month == 12:
                            next_month = current_date.replace(year=year + 1, month=1)
                        else:
                            next_month = current_date.replace(month=month + 1)
                        day_end = (next_month - timedelta(days=1)).day

                    # Generate tasks for each day and hour
                    for day in range(day_start, day_end + 1):
                        for hour in range(24):
                            url = self.build_url(symbol, year, month, day, hour)
                            filename = f"{symbol}-{year:04d}{month:02d}{day:02d}{hour:02d}.csv.gz"
                            local_path = market_output_dir / filename

                            task = DownloadTask(
                                url=url,
                                local_path=local_path,
                                symbol=symbol,
                                date=datetime(year, month, day, hour),
                                hour=hour
                            )
                            tasks.append(task)

                else:  # trade
                    # Monthly files - one file per symbol per month
                    url = self.build_url(symbol, year, month)
                    filename = f"{symbol}-{year_month}.csv.gz"
                    local_path = market_output_dir / filename

                    task = DownloadTask(
                        url=url,
                        local_path=local_path,
                        symbol=symbol,
                        date=current_date
                    )
                    tasks.append(task)

            # Move to next month
            if month == 12:
                current_date = current_date.replace(year=year + 1, month=1)
            else:
                current_date = current_date.replace(month=month + 1)

        logger.info(f"Generated {len(tasks)} download tasks")
        return tasks

    def validate_file(self, file_path: Path) -> Tuple[bool, str]:
        """
        Validate downloaded file

        Checks:
        1. File exists
        2. Size > MIN_FILE_SIZE bytes (not empty/error page)
        3. Valid gzip header (1f 8b)
        4. Can decompress first 1KB

        Args:
            file_path: Path to file to validate

        Returns:
            (is_valid, error_message)
            - (True, "") if valid
            - (False, "error message") if invalid
        """
        if not file_path.exists():
            return False, "File does not exist"

        file_size = file_path.stat().st_size
        if file_size < self.MIN_FILE_SIZE:
            return False, f"File too small ({file_size} bytes)"

        try:
            with open(file_path, 'rb') as f:
                # Check gzip magic number
                header = f.read(2)
                if header != self.GZIP_MAGIC:
                    return False, "Not a valid gzip file"

                # Try to decompress first 1KB
                f.seek(0)
                try:
                    with gzip.open(f, 'rb') as gz:
                        gz.read(1024)
                except Exception as e:
                    return False, f"Cannot decompress gzip: {e}"

        except Exception as e:
            return False, f"File validation error: {e}"

        return True, ""

    def download_file(self, task: DownloadTask, retry_count: int = 0) -> DownloadResult:
        """
        Download a single file with retry logic

        Steps:
        1. Check if file already exists and is valid (skip if yes)
        2. Send GET request
        3. Validate response (status code, content type, size)
        4. Validate gzip format
        5. Save to temporary location
        6. Verify file integrity
        7. Move to final location

        Args:
            task: DownloadTask to execute
            retry_count: Current retry attempt (0-based)

        Returns:
            DownloadResult with success/failure/skip status
        """
        # Check if valid file already exists
        if task.local_path.exists():
            is_valid, error_msg = self.validate_file(task.local_path)
            if is_valid:
                logger.debug(f"Skipping existing file: {task.local_path.name}")
                return DownloadResult(task=task, success=True, skipped=True)
            else:
                logger.warning(f"Existing file invalid ({error_msg}), re-downloading: {task.local_path.name}")

        try:
            # Create output directory
            task.local_path.parent.mkdir(parents=True, exist_ok=True)

            # Download file
            logger.debug(f"Downloading: {task.url}")
            response = self.session.get(task.url, timeout=30, stream=True)

            # Handle 404 - file doesn't exist (expected for some date/symbol combinations)
            if response.status_code == 404:
                logger.debug(f"File not found (404): {task.local_path.name}")
                return DownloadResult(task=task, success=False, skipped=True,
                                    error_message="File not found (404)")

            # Handle other HTTP errors
            response.raise_for_status()

            # Download content
            content = response.content

            # Validate content size
            if len(content) < self.MIN_FILE_SIZE:
                error_msg = f"Downloaded content too small ({len(content)} bytes)"
                logger.warning(error_msg)
                return DownloadResult(task=task, success=False, error_message=error_msg)

            # Validate gzip format
            if content[:2] != self.GZIP_MAGIC:
                # Check if it's an HTML error page
                content_str = content[:500].decode('utf-8', errors='ignore').lower()
                if 'html' in content_str or 'error' in content_str:
                    error_msg = "Received HTML error page instead of data"
                    logger.warning(f"{error_msg}: {task.local_path.name}")
                    return DownloadResult(task=task, success=False, error_message=error_msg)
                else:
                    error_msg = "Not a valid gzip file"
                    logger.warning(f"{error_msg}: {task.local_path.name}")
                    return DownloadResult(task=task, success=False, error_message=error_msg)

            # Test decompression
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(content[:1000])) as gz:
                    gz.read(10)
            except Exception as e:
                error_msg = f"Gzip decompression test failed: {e}"
                logger.warning(f"{error_msg}: {task.local_path.name}")
                return DownloadResult(task=task, success=False, error_message=error_msg)

            # Save to file
            with open(task.local_path, 'wb') as f:
                f.write(content)

            # Verify saved file
            is_valid, error_msg = self.validate_file(task.local_path)
            if not is_valid:
                task.local_path.unlink(missing_ok=True)
                return DownloadResult(task=task, success=False, error_message=error_msg)

            task.file_size = len(content)
            logger.debug(f"Downloaded successfully: {task.local_path.name} ({len(content)} bytes)")
            return DownloadResult(task=task, success=True)

        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {e}"
            logger.warning(f"{error_msg}: {task.url}")

            # Retry if not exceeded max retries
            if retry_count < self.MAX_RETRIES:
                wait_time = self.BACKOFF_FACTOR ** retry_count
                logger.info(f"Retrying in {wait_time} seconds... (attempt {retry_count + 1}/{self.MAX_RETRIES})")
                time.sleep(wait_time)
                return self.download_file(task, retry_count + 1)

            return DownloadResult(task=task, success=False, error_message=error_msg)

        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(f"{error_msg}: {task.url}")
            return DownloadResult(task=task, success=False, error_message=error_msg)

    def execute_downloads(self) -> DownloadStats:
        """
        Execute downloads using ThreadPoolExecutor

        Features:
        - Parallel downloads with configurable worker count
        - Batch processing (50 tasks per batch) to avoid memory issues
        - Progress tracking with ETA calculation
        - Error aggregation and reporting

        Returns:
            DownloadStats with success/failure/skip counts and timing
        """
        start_time = time.time()

        # Generate tasks
        tasks = self.generate_tasks()

        if not tasks:
            logger.warning("No tasks to download")
            return DownloadStats(
                total=0, successful=0, failed=0, skipped=0, total_time_seconds=0
            )

        # Check for existing files
        existing_valid = 0
        tasks_to_download = []
        for task in tasks:
            if task.local_path.exists():
                is_valid, _ = self.validate_file(task.local_path)
                if is_valid:
                    existing_valid += 1
                else:
                    tasks_to_download.append(task)
            else:
                tasks_to_download.append(task)

        if existing_valid > 0:
            logger.info(f"Found {existing_valid} existing valid files, will download {len(tasks_to_download)} files")

        if not tasks_to_download:
            logger.info("All files already exist and are valid")
            return DownloadStats(
                total=len(tasks), successful=existing_valid, failed=0, skipped=0,
                total_time_seconds=time.time() - start_time
            )

        # Statistics
        successful = existing_valid
        failed = 0
        skipped = 0

        # Process in batches
        batch_size = 50
        total_tasks = len(tasks_to_download)

        logger.info(f"Starting download of {total_tasks} files with {self.config.concurrent_workers} workers")

        with ThreadPoolExecutor(max_workers=self.config.concurrent_workers) as executor:
            for batch_start in range(0, total_tasks, batch_size):
                batch_end = min(batch_start + batch_size, total_tasks)
                batch_tasks = tasks_to_download[batch_start:batch_end]
                batch_num = (batch_start // batch_size) + 1
                total_batches = (total_tasks + batch_size - 1) // batch_size

                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_tasks)} tasks)")

                # Submit batch
                future_to_task = {
                    executor.submit(self.download_file, task): task
                    for task in batch_tasks
                }

                # Process results
                for future in as_completed(future_to_task):
                    result = future.result()

                    if result.success:
                        if not result.skipped:
                            successful += 1
                        else:
                            skipped += 1
                    else:
                        if result.skipped:
                            skipped += 1
                        else:
                            failed += 1

                # Progress update
                processed = batch_end
                progress_pct = (processed / total_tasks) * 100
                elapsed = time.time() - start_time

                if processed > 0:
                    avg_time = elapsed / processed
                    remaining = total_tasks - processed
                    eta_seconds = remaining * avg_time
                    eta_minutes = eta_seconds / 60

                    logger.info(f"Progress: {processed}/{total_tasks} ({progress_pct:.1f}%) "
                              f"- ETA: {eta_minutes:.1f} minutes")
                    logger.info(f"Stats: Success={successful}, Failed={failed}, Skipped={skipped}")

        total_time = time.time() - start_time

        # Final summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Download Complete")
        logger.info(f"{'='*60}")
        logger.info(f"Total tasks: {len(tasks)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Skipped (404): {skipped}")
        logger.info(f"Total time: {total_time / 60:.1f} minutes")
        logger.info(f"{'='*60}\n")

        return DownloadStats(
            total=len(tasks),
            successful=successful,
            failed=failed,
            skipped=skipped,
            total_time_seconds=total_time
        )


if __name__ == "__main__":
    # Example usage
    config = DownloadConfig(
        market_type='crypto',
        data_type='orderbook',
        symbols=['TSLAX_USDT', 'AAPLX_USDT'],
        start_date=datetime(2025, 9, 1),
        end_date=datetime(2025, 9, 1),  # Just 1 day for testing
        concurrent_workers=5,
        output_dir='raw_data/gate_orderbook_tick'
    )

    collector = GateCollector(config)
    stats = collector.execute_downloads()
