"""
Databento 数据验证测试

更新内容 (2025-12-13):
- 改用 BaseDataValidation 基类
- 使用 leg1/leg2 命名规则
- 配置化设计，仅需提供 get_config()
- 代码从 270 行减少到 30 行

验证从 databento 转换的 TSLA 和 AAPL tick 数据：
- 日期范围: 2025-09-02 至 2025-09-05 (美东时间)
- 交易策略: 每天 10:00 开仓, 14:00 平仓 (美东时间)
- 预期交易: TSLA 和 AAPL 各 4 天 = 8 次回转交易 = 16 笔订单
- 验证: 数据时间戳转换、数据完整性、交易执行
"""

import sys
from pathlib import Path

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from tests.validate_data.base.base_data_validation import BaseDataValidation


class DatabentoValidationTest(BaseDataValidation):
    """Databento 股票数据验证"""

    def get_config(self):
        return {
            # Leg 1: TSLA Stock
            'leg1_symbol': 'TSLA',
            'leg1_security_type': SecurityType.Equity,
            'leg1_market': Market.USA,
            'leg1_resolution': Resolution.Tick,
            'leg1_data_normalization': DataNormalizationMode.Raw,

            # Leg 2: AAPL Stock
            'leg2_symbol': 'AAPL',
            'leg2_security_type': SecurityType.Equity,
            'leg2_market': Market.USA,
            'leg2_resolution': Resolution.Tick,
            'leg2_data_normalization': DataNormalizationMode.Raw,

            # Backtest Configuration
            'start_date': (2025, 9, 2),
            'end_date': (2025, 9, 5),
            'initial_cash': 100000,
            'timezone': 'America/New_York',  # 美东时间

            # Trading Configuration
            'open_hour': 10,   # 10:00 ET
            'close_hour': 14,  # 14:00 ET
            'trade_quantity': 300,
            'expected_order_count': 16,  # 2 symbols × 4 days × 2 trades/day
            'allow_fee_variance': False,  # 股票不需要考虑手续费误差
        }
