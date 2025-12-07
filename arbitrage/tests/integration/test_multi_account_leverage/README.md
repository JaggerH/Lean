# Multi-Account Leverage Ratio Verification Test

## 测试目的

此集成测试验证 `RoutedBrokerageModel` 在多账户环境下的杠杆比率设置和执行。

## 测试场景

### 账户配置
- **IBKR账户**: $10,000 USD, 2x杠杆 (交易 TSLA)
- **Gate账户**: $10,000 USDT, 3x杠杆 (交易 BTCUSDT)

### 测试项目

1. **杠杆比率验证**
   - 确认 TSLA 的杠杆为 2x
   - 确认 BTCUSDT 的杠杆为 3x

2. **买入力测试 - IBKR账户**
   - 测试略高于杠杆比例(105%)的订单 → 应被拒绝
   - 测试略低于杠杆比例(95%)的订单 → 应成功

3. **买入力测试 - Gate账户**
   - 测试略高于杠杆比例(105%)的订单 → 应被拒绝
   - 测试略低于杠杆比例(95%)的订单 → 应成功

## 运行测试

### 使用 Lean CLI (推荐)
```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll --config ../../../arbitrage/tests/integration/test_multi_account_leverage/config.json
```

### 使用 Python Test Runner
```bash
PythonTestRunner/pytest.bat arbitrage/tests/integration/test_multi_account_leverage/main.py
```

## 预期结果

测试应该输出以下结果：
```
✅ ibkr_leverage_verified: PASS
✅ gate_leverage_verified: PASS
✅ high_leverage_order_rejected: PASS
✅ safe_leverage_order_accepted: PASS
```

## 测试验证点

### 1. 账户现金验证
- IBKR 初始现金: $10,000
- Gate 初始现金: $10,000
- 总现金: $20,000

### 2. 杠杆配置验证
- TSLA (IBKR): 2x 杠杆
- BTCUSDT (Gate): 3x 杠杆

### 3. 买入力计算验证
- 最大买入力 = 现金 × 杠杆倍数
- 订单金额 > 最大买入力 → 拒绝
- 订单金额 ≤ 最大买入力 → 接受

## 相关文件

- `main.py`: 测试算法主文件
- `config.json`: 多账户配置文件
- `Common/Brokerages/RoutedBrokerageModel.cs`: 被测试的核心类
- `Tests/Brokerages/RoutedBrokerageModelTests.cs`: 单元测试

## 技术细节

### RoutedBrokerageModel
根据证券的 `Market` 属性路由到不同的 `BrokerageModel`:
- `Market.USA` → InteractiveBrokersBrokerageModel
- `Market.Gate` → GateBrokerageModel

### 杠杆实现
每个 `BrokerageModel` 通过 `GetLeverage()` 方法返回对应的杠杆倍数，影响 `BuyingPowerModel` 的计算。

### 多账户隔离
每个子账户维护独立的：
- 现金余额
- 持仓
- 买入力计算
- Margin使用量
