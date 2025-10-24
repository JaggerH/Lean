# 多账户状态存储与恢复

本目录提供多账户状态持久化和恢复功能的测试和示例。

## 功能说明

多账户状态存储与恢复功能允许算法在重启时自动恢复账户状态（现金余额和持仓），确保交易连续性。

### 工作原理

1. **状态存储**: 算法正常退出时，自动将多账户状态（现金、持仓）保存到 JSON 文件
2. **状态恢复**: 算法启动时，检测到状态文件则自动恢复账户状态
3. **数据验证**: 恢复后验证数据完整性和一致性

## 文件结构

```
test_account_restore/
├── persistence.py                    # 存储测试算法
├── recovery.py                       # 恢复测试算法
├── persistence-config.json           # 存储测试配置
├── recovery-config.json              # 恢复测试配置
├── persistence-config.example.json   # 存储配置示例（可安全提交 git）
├── recovery-config.example.json      # 恢复配置示例（可安全提交 git）
├── persistence-local-config.json     # 本地存储测试配置（包含真实密钥）
├── live-config.json                  # Live Paper 模式配置
├── README.md                         # 本文件
└── .state/                           # 状态文件目录
    └── recovery.json                 # 状态文件（自动生成）
```

## 配置文件说明

### 状态持久化配置

在配置文件中添加以下字段启用状态持久化：

```json
{
  "multi-account-persistence": "../../../arbitrage/.state/recovery.json"
}
```

**路径说明**:
- 生产环境: `arbitrage/.state/recovery.json`
- 测试环境: `arbitrage/tests/integration/test_account_restore/.state/recovery.json`

### 多账户路由配置

```json
{
  "multi-account-config": {
    "accounts": {
      "IBKR": 50000,
      "Kraken": 50000
    },
    "router": {
      "type": "Market",
      "mappings": {
        "USA": "IBKR",
        "Kraken": "Kraken"
      },
      "default": "IBKR"
    }
  }
}
```

**说明**:
- `accounts`: 各账户初始资金
- `router.mappings`: 市场到账户的路由规则
- `router.default`: 默认账户

## 快速开始

### 1. 准备配置文件

复制示例配置并填入真实密钥：

```bash
cd arbitrage/tests/integration/test_account_restore
copy persistence-config.example.json persistence-config.json
copy recovery-config.example.json recovery-config.json
```

然后编辑配置文件，填入真实的 API 密钥（仅限本地使用，不要提交到 git）。

### 2. 运行存储测试

```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll --config ../../../arbitrage/tests/integration/test_account_restore/persistence-config.json
```

**预期输出**:
```
💾 Saving multi-account state to: .state/recovery.json
✅ Multi-account state saved successfully
📄 Saved State Summary:
   Accounts: ['IBKR', 'Kraken']
   - IBKR: Cash=1 entries, Holdings=X
   - Kraken: Cash=1 entries, Holdings=Y
```

### 3. 验证状态文件

```bash
type .state\recovery.json
```

**状态文件格式**:
```json
{
  "timestamp": "2025-01-23 10:30:00",
  "accounts": {
    "IBKR": {
      "cash": [
        {"Amount": 48000.0, "Currency": "USD"}
      ],
      "holdings": [
        {
          "Symbol": "AAPL R735QTJ8XC9X",
          "Quantity": 100,
          "AveragePrice": 150.0
        }
      ]
    },
    "Kraken": {
      "cash": [
        {"Amount": 52000.0, "Currency": "USD"}
      ],
      "holdings": [
        {
          "Symbol": "AAPLxUSD XJ",
          "Quantity": 100,
          "AveragePrice": 151.0
        }
      ]
    }
  }
}
```

### 4. 运行恢复测试

```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll --config ../../../arbitrage/tests/integration/test_account_restore/recovery-config.json
```

**预期输出**:
```
🔄 RECOVERY MODE - Loading state from: .state/recovery.json
📸 Restoring account 'IBKR':
   Cash: USD = $48,000.00
   Holdings: AAPL R735QTJ8XC9X, Qty=100, AvgPrice=$150.00
📸 Restoring account 'Kraken':
   Cash: USD = $52,000.00
   Holdings: AAPLxUSD XJ, Qty=100, AvgPrice=$151.00

🔍 Verifying restored state...
✅ IBKR - Cash verified
✅ IBKR - Holdings verified
✅ Kraken - Cash verified
✅ Kraken - Holdings verified
✅✅✅ STATE RECOVERY TEST PASSED ✅✅✅
```

## 集成到生产环境

### 1. 配置生产环境

编辑 `arbitrage/config_live_paper.json`，添加状态持久化配置：

```json
{
  "multi-account-persistence": "../../../arbitrage/.state/recovery.json",
  "multi-account-config": {
    "accounts": {
      "IBKR": 50000,
      "Kraken": 50000
    },
    "router": {
      "type": "Market",
      "mappings": {
        "USA": "IBKR",
        "Kraken": "Kraken"
      },
      "default": "IBKR"
    }
  }
}
```

### 2. 启动算法

```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll --config ../../../arbitrage/config_live_paper.json
```

### 3. 重启算法

算法重启时会自动：
1. 检测状态文件是否存在
2. 恢复账户现金和持仓
3. 继续执行交易策略

**无需手动干预**！

## 状态文件管理

### 备份状态文件

建议定期备份状态文件到安全位置：

```bash
# Windows
copy arbitrage\.state\recovery.json arbitrage\.state\recovery.json.backup_%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%

# Linux/Mac
cp arbitrage/.state/recovery.json arbitrage/.state/recovery.json.backup.$(date +%Y%m%d_%H%M%S)
```

### 清理状态文件

如需从零开始（清空所有持仓和状态）：

```bash
del arbitrage\.state\recovery.json
```

**警告**: 删除状态文件后，下次启动将使用配置文件中的初始资金，所有历史持仓将丢失！

## 故障排查

### 状态文件未创建

**检查**:
1. 配置文件是否包含 `multi-account-persistence` 字段
2. `.state` 目录是否存在且有写入权限
3. 算法是否正常退出（非强制终止）

### 恢复失败

**检查**:
1. 状态文件 JSON 格式是否正确: `python -m json.tool .state/recovery.json`
2. 状态文件是否被手动修改
3. 配置文件的账户名称是否与状态文件一致

### 持仓数量不匹配

**检查**:
1. 是否在两次运行之间修改了策略参数
2. 数据源是否正常
3. 是否有手动交易未记录到状态文件

## 核心实现文件

### C# 实现

- **状态恢复**: `Brokerages/Paper/PaperBrokerage.cs` - `RestoreAccountState()` 方法
- **Setup Handler**: `Engine/Setup/BrokerageRecoverySetupHandler.cs` - 初始化恢复逻辑

### Python 实现

- **状态存储**: `arbitrage/monitoring/state_persistence.py` - `StatePersistence` 类
- **测试算法**:
  - `arbitrage/tests/integration/test_account_restore/persistence.py` - 存储测试
  - `arbitrage/tests/integration/test_account_restore/recovery.py` - 恢复测试

## 相关文档

- `arbitrage/STATE_RECOVERY_CONFIG_DRIVEN_IMPLEMENTATION.md` - 完整实施文档
- `arbitrage/STATE_RECOVERY_IMPLEMENTATION_SUMMARY.md` - 实施总结

---

**最后更新**: 2025-01-24
