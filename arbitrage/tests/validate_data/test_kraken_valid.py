"""
Kraken 数据验证测试 (Gate.io 数据源)

更新内容 (2025-12-13):
- 改用 BaseDataValidation 基类
- 使用 leg1/leg2 命名规则
- 配置化设计，仅需提供 get_config()
- 代码从 280 行减少到 35 行

验证从 gate.io 转换的加密货币 tick 数据:
- 日期范围: 2025-09-02 至 2025-09-05 (UTC 时间)
- 交易对: AAPLUSD, TSLAUSD (AAPLx/USD, TSLAx/USD)
- 交易策略: 每天 UTC 10:00 开仓, UTC 14:00 平仓
- 预期交易: AAPL 和 TSLA 各 4 天 = 8 次回转交易 = 16 笔订单
- 验证: Kraken 格式兼容性、数据完整性、交易执行
"""

import sys
from pathlib import Path

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from tests.validate_data.base.base_data_validation import BaseDataValidation


class KrakenValidationTest(BaseDataValidation):
    """Kraken/Gate.io 加密货币数据验证"""

    def get_config(self):
        return {
            # Leg 1: AAPLUSD Crypto
            'leg1_symbol': 'AAPLUSD',
            'leg1_security_type': SecurityType.Crypto,
            'leg1_market': Market.Kraken,
            'leg1_resolution': Resolution.Tick,
            'leg1_data_normalization': DataNormalizationMode.Raw,

            # Leg 2: TSLAUSD Crypto
            'leg2_symbol': 'TSLAUSD',
            'leg2_security_type': SecurityType.Crypto,
            'leg2_market': Market.Kraken,
            'leg2_resolution': Resolution.Tick,
            'leg2_data_normalization': DataNormalizationMode.Raw,

            # Backtest Configuration
            'start_date': (2025, 9, 2),
            'end_date': (2025, 9, 5),
            'initial_cash': 100000,
            'timezone': 'UTC',  # UTC 时间
            'brokerage': BrokerageName.Kraken,
            'account_type': AccountType.Cash,

            # Trading Configuration
            'open_hour': 10,   # 10:00 UTC
            'close_hour': 14,  # 14:00 UTC
            'trade_quantity': 100,
            'expected_order_count': 16,  # 2 symbols × 4 days × 2 trades/day
            'allow_fee_variance': True,  # 加密货币有手续费，允许误差
        }
