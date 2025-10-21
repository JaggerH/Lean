# LEAN Testing Framework

在回测流程中嵌入单元测试的框架，实现"回测即测试"。

## 核心理念

传统单元测试和回测是分离的：
- **单元测试**：Mock 数据，测试孤立函数
- **回测**：真实数据，统计交易结果

本框架融合两者：
- ✅ 在真实回测中插入断言
- ✅ 自动收集测试结果
- ✅ 双重统计（回测指标 + 测试通过率）
- ✅ 支持 pytest 集成

## 快速开始

### 1. 创建可测试算法

```python
from testing.testable_algorithm import TestableAlgorithm

class MyTest(TestableAlgorithm):
    def initialize(self):
        self.set_start_date(2013, 10, 7)
        self.set_cash(100000)
        self.spy = self.add_equity("SPY", Resolution.DAILY)

        # 断言初始状态
        self.assert_equal(self.portfolio.cash, 100000)

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.Filled:
            # 在成交时验证
            self.assert_equal(order_event.fill_quantity, 100)
            self.assert_true(self.portfolio.invested)
```

### 2. 运行测试

**方式一：直接运行 LEAN**
```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll --config path/to/test_config.json
```

**方式二：使用 Python 运行器**
```python
from testing.test_runner import LeanTestRunner

runner = LeanTestRunner()
results = runner.run_test("path/to/test_config.json")
runner.print_results(results)
```

**方式三：使用 pytest**
```bash
cd arbitrage/tests
pytest test_with_pytest.py -v
```

## 核心功能

### 断言方法

```python
# 相等性断言
self.assert_equal(actual, expected, "消息")
self.assert_true(condition, "消息")
self.assert_false(condition, "消息")

# 数值比较
self.assert_greater(value, threshold, "消息")
self.assert_less(value, threshold, "消息")
self.assert_greater_equal(value, threshold, "消息")

# 存在性
self.assert_not_none(value, "消息")
```

### 检查点机制

记录关键时刻的状态，稍后验证：

```python
# 记录检查点
def on_data(self, data):
    self.checkpoint('before_order',
                   cash=self.portfolio.cash,
                   price=data[self.spy.symbol].close)

    # ... 下单 ...

# 验证检查点
def on_end_of_algorithm(self):
    self.verify_checkpoint('before_order', {
        'cash': 100000,
        'price': lambda p: 140 < p < 160  # 支持 lambda
    })
```

### 测试阶段管理

组织测试流程：

```python
def on_data(self, data):
    self.begin_test_phase("order_placement")

    # ... 测试代码 ...

    self.end_test_phase()
    # 自动输出该阶段统计
```

## 测试结果

### 实时输出
```
🧪 TEST PHASE: initialization
✅ PASS | assert_equal | 初始现金应为 $100,000
✅ PASS | assert_not_none | SPY Symbol 应该存在
```

### 最终统计
```
📝 UNIT TEST RESULTS
============================================================
Total Assertions: 32
Passed: 32 ✅
Failed: 0 ❌
Pass Rate: 100.0%
Checkpoints: 3

✅ All tests passed!
```

### JSON 输出
```json
{
  "total_assertions": 32,
  "passed": 32,
  "failed": 0,
  "pass_rate": 1.0,
  "checkpoints": ["initialization", "before_order", "after_fill"],
  "assertions": [...]
}
```

## 目录结构

```
arbitrage/
├── testing/                      # 测试框架
│   ├── __init__.py
│   ├── testable_algorithm.py    # TestableAlgorithm 基类
│   ├── test_runner.py           # LeanTestRunner
│   └── README.md                # 本文档
│
├── tests/
│   ├── unit/                    # Layer 1: 纯单元测试
│   │   └── test_spread_manager.py
│   │
│   ├── integration/             # Layer 2: 集成测试
│   │   ├── test_order_execution.py
│   │   └── run_order_execution_test.bat
│   │
│   ├── configs/                 # 测试配置
│   │   └── config_order_execution.json
│   │
│   ├── test_with_pytest.py      # Pytest 集成
│   └── run_all_tests.bat        # 运行所有测试
```

## 三层测试架构

### Layer 1: 单元测试
- 纯 Python，无需 LEAN
- Mock 所有依赖
- 极快速度（秒级）

### Layer 2: 集成测试（本框架）
- 真实 LEAN 回测
- 事件驱动中插入断言
- 验证交易流程

### Layer 3: 回归测试
- 端到端验证
- 检查回测统计指标

## 示例：完整测试流程

参见 `tests/integration/test_order_execution.py`：

```python
class OrderExecutionTest(TestableAlgorithm):
    def initialize(self):
        # 测试阶段1: 初始化
        self.begin_test_phase("initialization")
        self.assert_equal(self.portfolio.cash, 100000)
        self.checkpoint('initialization', cash=100000)
        self.end_test_phase()

    def on_data(self, data):
        # 测试阶段2: 下单
        self.begin_test_phase("order_placement")
        ticket = self.market_order(self.spy.symbol, 100)
        self.assert_greater(ticket.order_id, 0)
        self.end_test_phase()

    def on_order_event(self, order_event):
        # 测试阶段3: 成交验证
        if order_event.status == OrderStatus.Filled:
            self.begin_test_phase("order_filled")
            self.assert_equal(order_event.fill_quantity, 100)
            self.assert_true(self.portfolio.invested)
            self.checkpoint('after_fill', quantity=100)
            self.end_test_phase()

    def on_end_of_algorithm(self):
        # 测试阶段4: 最终验证
        self.verify_checkpoint('initialization', {'cash': 100000})
        self.verify_checkpoint('after_fill', {'quantity': 100})
        super().on_end_of_algorithm()
```

运行结果：
- ✅ 32 个断言全部通过
- ✅ 3 个检查点验证成功
- ✅ 回测盈亏统计正常

## 最佳实践

1. **使用测试阶段** - 清晰组织测试流程
2. **记录检查点** - 在关键节点记录状态
3. **lambda 验证** - 灵活验证范围条件
4. **实时反馈** - 每个断言立即输出结果
5. **双重验证** - 既看测试通过率，也看回测指标

## 与 Pytest 集成

```python
# tests/test_with_pytest.py
def test_order_execution():
    runner = LeanTestRunner()
    results = runner.run_test("path/to/config.json")

    assert results['success']
    assert results['test_results']['failed'] == 0
    assert results['test_results']['pass_rate'] == 1.0
```

运行：
```bash
pytest arbitrage/tests/test_with_pytest.py -v
```

## 常见问题

**Q: 为什么不用 Mock？**
A: Mock 测试无法验证真实市场数据下的行为，本框架在真实回测中测试。

**Q: 性能影响？**
A: 断言开销极小（< 0.1ms），对回测速度几乎无影响。

**Q: 如何调试失败的断言？**
A: 查看实时输出的 `❌ FAIL` 消息，或在 `on_end_of_algorithm()` 查看失败列表。

**Q: 可以用于实盘吗？**
A: 不建议。这是测试框架，仅用于回测验证。

## 参考

- 示例测试：`tests/integration/test_order_execution.py`
- API 文档：`testable_algorithm.py` 中的 docstring
- 运行器：`test_runner.py`
