# Gate Margin Mode Leverage Verification Test

## 测试目的

验证在多账户模式下，Gate 账户配置为 Margin 模式时，Crypto 类型的证券能否正确获得 5x 杠杆。

## 测试场景

- **账户**: Gate（单账户）
- **账户类型**: Margin
- **初始资金**: $50,000 USDT
- **测试证券**:
  - TSLAXUSDT (Gate market)
  - AAPLXUSDT (Gate market)
- **预期杠杆**: 5x（根据 `GateBrokerageModel._maxLeverage = 5m`）
- **日期范围**: 2025-09-04 至 2025-09-10

## 关键测试点

1. ✅ 验证 Gate 账户正确配置为 Margin 模式
2. ✅ 验证 TSLAXUSDT 的 Leverage = 5x
3. ✅ 验证 AAPLXUSDT 的 Leverage = 5x
4. ✅ 验证 BuyingPowerModel 类型正确
5. ✅ 日志输出完整的调用堆栈信息

## 配置文件关键部分

```json
{
  "multi-account-config": {
    "accounts": {
      "Gate": {
        "cash": 50000,
        "brokerage": "GateUnifiedBrokerage",
        "currency": "USDT",
        "brokerage-params": {
          "accountType": "Margin"  // ← 关键：必须指定 Margin
        }
      }
    }
  }
}
```

### ⚠️ 重要说明

**必须在 `brokerage-params` 中指定 `accountType`！**

- ❌ 错误配置（缺少 `brokerage-params`）：
  ```json
  "Gate": {
    "cash": 50000,
    "brokerage": "GateUnifiedBrokerage",
    "currency": "USDT"
    // 缺少 brokerage-params - 将使用默认构造函数
  }
  ```
  结果：Leverage = 1x（错误）

- ✅ 正确配置：
  ```json
  "Gate": {
    "cash": 50000,
    "brokerage": "GateUnifiedBrokerage",
    "currency": "USDT",
    "brokerage-params": {
      "accountType": "Margin"  // ← 必须指定
    }
  }
  ```
  结果：Leverage = 5x（正确）

## 运行测试

### 方法 1: 使用 Lean CLI（推荐）

```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll --config ../../../arbitrage/tests/integration/test_multi_account_leverage/config.json
```

### 方法 2: 直接运行（从项目根目录）

```bash
dotnet run --project Launcher -- --config arbitrage/tests/integration/test_multi_account_leverage/config.json
```

## 预期输出

```
================================================================================
GATE MARGIN MODE LEVERAGE VERIFICATION TEST
================================================================================

📊 Adding Gate Crypto Securities...
--------------------------------------------------------------------------------
✅ Added TSLAXUSDT (Gate)
✅ Added AAPLXUSDT (Gate)

🔍 Multi-Account Configuration:
--------------------------------------------------------------------------------
✅ Multi-Account Portfolio Detected!
📊 Gate Account:
   Cash: $50,000.00
   Currency: USDT

🔍 Security Configuration Details:
================================================================================

📌 TSLAXUSDT:
   Market: Gate
   SecurityType: Crypto
   BrokerageModel: RoutedBrokerageModel
   BuyingPowerModel: SecurityMarginModel
   ⭐ Leverage: 5x
   IsTradable: True
   IsInternalFeed: False
   ✅ PASS: Leverage is 5.0x (Margin mode)

📌 AAPLXUSDT:
   Market: Gate
   SecurityType: Crypto
   BrokerageModel: RoutedBrokerageModel
   BuyingPowerModel: SecurityMarginModel
   ⭐ Leverage: 5x
   IsTradable: True
   IsInternalFeed: False
   ✅ PASS: Leverage is 5.0x (Margin mode)

🔍 Additional Diagnostics:
--------------------------------------------------------------------------------
Algorithm Type: MultiAccountLeverageTest

Total Securities: 2
  TSLAXUSDT: Leverage=5x, Type=Crypto
  AAPLXUSDT: Leverage=5x, Type=Crypto

================================================================================
INITIALIZATION COMPLETE
================================================================================
```

## Leverage 调用堆栈

在多账户模式下，获取 `security.Leverage` 的完整调用堆栈：

```
[Python 代码]
security.Leverage
    ↓
[Security.cs:540]
Security.Leverage → Holdings.Leverage
    ↓
[SecurityHolding.cs:156-162]
SecurityHolding.Leverage → _security.BuyingPowerModel.GetLeverage(_security)
    ↓
[多账户路由层]
RoutedBrokerageModel.GetLeverage(security)
    1. 根据 security.Symbol.ID.Market 查找对应的 BrokerageModel
    2. 在本例中，Market = "Gate" → GateBrokerageModel
    ↓
[GateBrokerageModel.cs:74-100]
GateBrokerageModel.GetLeverage(security)
    - AccountType = Margin
    - SecurityType = Crypto
    - 返回 _maxLeverage = 5m
```

## 问题排查

### 问题：Leverage 始终是 1x

**原因**：配置文件中缺少 `brokerage-params`。

**解决方案**：在 `config.json` 的账户配置中添加：

```json
"brokerage-params": {
  "accountType": "Margin"
}
```

### 问题：找不到 Gate market 的数据

**原因**：数据文件不存在或路径不正确。

**解决方案**：
1. 确认 `Data/crypto/gate/minute/` 目录存在
2. 确认有 TSLAXUSDT 和 AAPLXUSDT 的数据文件
3. 检查 `data-folder` 配置是否正确

## 相关文件

- **配置**: `arbitrage/tests/integration/test_multi_account_leverage/config.json`
- **算法**: `arbitrage/tests/integration/test_multi_account_leverage/main.py`
- **文档**:
  - `BROKERAGE_PARAMS_CONFIG.md` - brokerage-params 配置指南
  - `Common/Brokerages/GateBrokerageModel.cs` - Gate 杠杆实现
  - `Common/Brokerages/RoutedBrokerageModel.cs` - 多账户路由实现

## 下一步

如果这个测试通过（Leverage = 5x），则可以继续测试：
1. 使用杠杆进行实际交易
2. 验证买入力计算是否正确（应为 Cash × Leverage）
3. 测试 Margin Call 机制
