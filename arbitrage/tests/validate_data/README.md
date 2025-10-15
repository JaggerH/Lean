# 数据验证测试

验证从不同数据源转换的 tick 数据格式和交易执行。

## 测试概览

### 1. Databento 数据验证 (`test_databento_valid.py`)

**数据源**: Databento
**资产类型**: 美股 (TSLA, AAPL)
**数据类型**: Tick (trade + quote)
**时区**: 美东时间 (America/New_York)
**日期范围**: 2025-09-02 至 2025-09-05

**交易策略**:
- 每天 10:00 开仓 (买入 TSLA 10股 + AAPL 10股)
- 每天 14:00 平仓 (卖出 TSLA 10股 + AAPL 10股)
- 4个交易日 × 2个品种 × 2次操作 = **16笔交易**

**验证内容**:
- ✅ Unix 时间戳正确转换为美东时间
- ✅ 每日数据时间范围完整
- ✅ 订单成功创建和成交
- ✅ 持仓数量和价格准确
- ✅ 最终持仓归零

**数据位置**:
```
Data/equity/usa/tick/tsla/
├── 20250902_trade.zip
├── 20250903_trade.zip
├── 20250904_trade.zip
└── 20250905_trade.zip

Data/equity/usa/tick/aapl/
├── 20250902_trade.zip
├── 20250902_quote.zip
├── 20250903_trade.zip
├── 20250903_quote.zip
├── 20250904_trade.zip
├── 20250904_quote.zip
├── 20250905_trade.zip
└── 20250905_quote.zip
```

---

### 2. Kraken 加密货币数据验证 (`test_kraken_valid.py`)

**数据源**: Gate.io (作为 Kraken 格式使用)
**资产类型**: 加密货币 (AAPLXUSDT, TSLAXUSDT)
**数据类型**: Tick (quote/orderbook)
**时区**: UTC
**日期范围**: 2025-09-02 至 2025-09-05

**交易策略**:
- 每天 UTC 10:00 开仓 (买入 AAPLX 0.1 + TSLAX 0.1)
- 每天 UTC 14:00 平仓 (卖出 AAPLX 0.1 + TSLAX 0.1)
- 4个交易日 × 2个品种 × 2次操作 = **16笔交易**

**验证内容**:
- ✅ Kraken brokerage model 兼容性
- ✅ 加密货币符号格式正确 (AAPLXUSDT)
- ✅ Unix 时间戳正确转换为 UTC 时间
- ✅ 每日数据时间范围完整
- ✅ 订单成功创建和成交
- ✅ 持仓数量和价格准确
- ✅ 最终持仓归零

**数据位置**:
```
Data/crypto/kraken/tick/aaplxusdt/
├── 20250902_quote.zip
├── 20250903_quote.zip
├── 20250904_quote.zip
└── 20250905_quote.zip

Data/crypto/kraken/tick/tslaxusdt/
├── 20250902_quote.zip
├── 20250903_quote.zip
├── 20250904_quote.zip
└── 20250905_quote.zip
```

---

## 运行测试

### 方式一: 单独运行

**Databento 测试**:
```bash
cd arbitrage/tests/validate_data
./run_databento_test.bat
```

**Kraken 测试**:
```bash
cd arbitrage/tests/validate_data
./run_kraken_test.bat
```

### 方式二: 运行所有验证测试

```bash
cd arbitrage/tests/validate_data
./run_all_validation_tests.bat
```

### 方式三: 使用 Python 运行器

```python
from testing.test_runner import LeanTestRunner

# Databento 测试
runner = LeanTestRunner()
results = runner.run_test("arbitrage/tests/configs/config_databento_validation.json")
runner.print_results(results)

# Kraken 测试
results = runner.run_test("arbitrage/tests/configs/config_kraken_validation.json")
runner.print_results(results)
```

---

## 测试输出

### 成功输出示例

```
============================================
Databento Data Validation Test
============================================

🧪 TEST PHASE: initialization
✅ PASS | assert_not_none | TSLA Symbol 应该存在
✅ PASS | assert_not_none | AAPL Symbol 应该存在
✅ PASS | assert_equal | 初始现金应为 $100,000

🧪 TEST PHASE: open_positions_2025-09-02
✅ PASS | assert_greater | TSLA 订单ID应大于0 at 2025-09-02 10:00:00
✅ PASS | assert_greater | AAPL 订单ID应大于0 at 2025-09-02 10:00:00

🧪 TEST PHASE: order_filled_TSLA_0
✅ 订单成交: TSLA | 数量: 10 | 价格: $235.42 | 时间: 2025-09-02 10:00:01

...

============================================================
📊 每日数据时间范围 (美东时间, Unix 时间戳)
============================================================

日期: 2025-09-02
  首笔数据: 2025-09-02 04:00:00 (Unix: 1725264000)
  末笔数据: 2025-09-02 19:59:59 (Unix: 1725321599)
  时间跨度: 15.99 小时

日期: 2025-09-03
  首笔数据: 2025-09-03 04:00:00 (Unix: 1725350400)
  末笔数据: 2025-09-03 19:59:59 (Unix: 1725407999)
  时间跨度: 15.99 小时

...

============================================================
📝 UNIT TEST RESULTS
============================================================
Total Assertions: 48
Passed: 48 ✅
Failed: 0 ❌
Pass Rate: 100.0%
Checkpoints: 1

✅ All tests passed!
```

### 输出文件

测试输出保存在:
- `Launcher/bin/Debug/databento_test_output.txt`
- `Launcher/bin/Debug/kraken_test_output.txt`

---

## 常见问题

### Q1: 为什么 Databento 测试使用美东时间？

A: 美股数据基于美东时间 (ET)，需要验证时间戳转换正确。

### Q2: 为什么 Kraken 测试使用 UTC？

A: 加密货币市场 24/7 运行，UTC 是标准时区。

### Q3: 如果测试失败怎么办？

A: 检查以下几点:
1. 数据文件是否存在且格式正确
2. 时间戳转换是否有问题
3. 符号格式是否符合 LEAN 要求
4. 查看详细输出日志

### Q4: 如何验证时间戳转换？

A: 测试会输出每日数据的 Unix 时间戳和转换后的时间，可以对比验证:
```
首笔数据: 2025-09-02 04:00:00 (Unix: 1725264000)
```

使用在线工具验证: https://www.epochconverter.com/

### Q5: 预期交易数不匹配怎么办？

A: 检查:
1. 日期范围是否覆盖 4 个交易日
2. 数据文件是否完整 (2025-09-02 至 2025-09-05)
3. 是否有数据缺失导致订单未成交

---

## 配置文件

- **Databento**: `arbitrage/tests/configs/config_databento_validation.json`
- **Kraken**: `arbitrage/tests/configs/config_kraken_validation.json`

---

## 相关文档

- [TestableAlgorithm 框架](../testing/README.md)
- [数据格式说明](../../../raw_data/README.md)
- [LEAN 数据要求](https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/key-concepts)
