# Arbitrage Algorithm - Kraken xStocks Monitoring

本项目是基于 LEAN 引擎的套利算法，用于监控 Kraken xStocks（代币化股票）的实时订单簿数据。

## ⚠️ 重要更新 (2025-11-20)

**架构重构：SpreadManager → SubscriptionHelper + TradingPairs**

订阅和价差管理架构已重构以充分利用 LEAN 的原生 TradingPair 基础设施：

- ✅ **新代码**: 使用 `subscription_helper.py` + 直接访问 `algorithm.TradingPairs`
- ⚠️ **旧代码**: `spread_manager.py` 已标记为弃用但仍可用于向后兼容
- 📖 **迁移指南**: 查看 [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) 了解如何迁移现有代码
- 🎯 **参考实现**: 查看 `spot_future_arbitrage.py` 了解新架构的完整示例

**关键改进**:
- 减少 ~750 行 Python 代码
- 使用 LEAN 标准的 `CollectionChanged` 事件
- 在 OnData 中直接访问 `slice.TradingPairs`
- 统一的订阅逻辑

## 项目结构

```
..\
├── Lean\                           # LEAN 主项目
│   ├── arbitrage\                  # 本套利算法目录
│   │   ├── main.py                # 算法主文件
│   │   ├── utils.py               # 工具函数（获取xStocks、映射到数据库）
│   │   ├── add_xstocks.py         # 添加xStocks到符号数据库的脚本
│   │   └── README.md              # 本文档
│   ├── Launcher\
│   │   ├── config.json            # 配置文件（Kraken API密钥等）
│   │   └── run.bat                # 启动脚本
│   └── Data\
│       └── symbol-properties\
│           └── symbol-properties-database.csv  # 符号属性数据库
│
├── Lean.Brokerages.Kraken\        # Kraken Brokerage 插件
│   └── QuantConnect.KrakenBrokerage\
│       └── KrakenBrokerage.cs     # **已修改：注释了订阅验证**
│
└── Lean.Brokerages.InteractiveBrokers\  # IB Brokerage 插件
    └── QuantConnect.Brokerages.InteractiveBrokers\
```

## 1. Brokerage 源代码仓库

### 自动化构建脚本（推荐）

使用 `build_brokerage.py` 自动化完成克隆、编译、复制 DLL 的全过程：

```bash
# 在 Lean 根目录下运行

# 首次设置：自动克隆、编译、复制所有 Brokerage
python build_brokerage.py

# 重新编译特定 Brokerage（修改代码后）
python build_brokerage.py --rebuild Kraken
python build_brokerage.py --rebuild InteractiveBrokers

# 重新编译所有 Brokerage
python build_brokerage.py --rebuild all
```

**脚本功能**:
- ✅ 自动验证是否在 LEAN 根目录
- ✅ 克隆 Brokerage 仓库（如果不存在）
- ✅ 编译 LEAN 和 Brokerage 项目
- ✅ 复制 DLL 到 `Launcher/bin/Debug/`
- ✅ 智能跳过已完成的步骤
- ✅ 彩色输出，清晰的进度提示

### Brokerage 仓库信息

#### Kraken Brokerage
- **仓库链接**: https://github.com/QuantConnect/Lean.Brokerages.Kraken
- **位置**: `..\Lean.Brokerages.Kraken`

#### Interactive Brokers Brokerage
- **仓库链接**: https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers
- **位置**: `..\Lean.Brokerages.InteractiveBrokers`

## 2. Kraken Brokerage 代码修改

### 修改文件
`Lean.Brokerages.Kraken\QuantConnect.KrakenBrokerage\KrakenBrokerage.cs`

### 修改位置
**第 543 行** - 注释掉订阅验证（用于本地开发，避免 QuantConnect 云订阅验证）

```csharp
// 原代码（第 543 行）：
ValidateSubscription();

// 修改后：
// ValidateSubscription(); // Commented out for local development
```

### 修改原因
- `ValidateSubscription()` 用于验证 QuantConnect 云平台的付费订阅
- 本地开发不需要云订阅，因此注释掉此验证
- **注意**: 每次从源码仓库拉取更新后，需要重新注释此行

### 重新编译修改后的代码
```bash
cd ..\Lean.Brokerages.Kraken
dotnet build QuantConnect.KrakenBrokerage.sln
copy "QuantConnect.KrakenBrokerage\bin\Debug\QuantConnect.KrakenBrokerage.dll" "..\Lean\Launcher\bin\Debug\"
```

## 3. 运行测试

### 方式 1: 使用 run.bat (推荐)

**文件位置**: `..\Lean\Launcher\run.bat`

**run.bat 内容**:
```batch
@echo off
REM Auto-detect Python DLL path from conda environment
for /f "tokens=*" %%i in ('conda run -n lean python -c "import sys; print(sys.base_prefix + '\\python311.dll')"') do set PYTHONNET_PYDLL=%%i

copy /Y config.json bin\Debug\config.json
cd bin\Debug
dotnet QuantConnect.Lean.Launcher.dll
```

**运行命令**:
```bash
cd ..\Launcher
./run.bat
```

**功能说明**:
1. **自动检测 Python DLL 路径** - 从 conda `lean` 环境中动态获取
2. **复制配置文件** - 将 `Launcher/config.json` 复制到 `bin/Debug/`
3. **切换工作目录** - 进入 `bin/Debug/` 目录（Python 模块加载需要）
4. **启动 LEAN 引擎** - 运行算法

### 方式 2: 直接运行 dotnet

```bash
cd ..\Lean\Launcher\bin\Debug
set PYTHONNET_PYDLL=C:\Users\Jagger\anaconda3\envs\lean\python311.dll
dotnet QuantConnect.Lean.Launcher.dll
```

## 4. 配置文件

### Launcher/config.json 关键配置

```json
{
  "environment": "live-paper",
  "algorithm-type-name": "Arbitrage",
  "algorithm-language": "Python",
  "algorithm-location": "../../../arbitrage/main.py",
  "data-folder": "../../../Data/",

  "kraken-api-key": "你的API密钥",
  "kraken-api-secret": "你的API密钥",

  "environments": {
    "live-paper": {
      "live-mode": true,
      "live-mode-brokerage": "PaperBrokerage",
      "data-queue-handler": ["KrakenBrokerage"],
      ...
    }
  }
}
```

## 5. xStocks 符号数据库

### 添加 xStocks 到数据库

运行脚本自动从 Kraken API 获取所有 xStocks 并添加到符号数据库：

```bash
python add_xstocks_to_symbol_database.py
```

**功能**:
- 从 Kraken API 获取所有 xStocks（代币化股票）
- 映射为 LEAN 符号属性格式
- 添加到两个 CSV 文件（自动去重）:
  - `Data/symbol-properties/symbol-properties-database.csv`
  - `Launcher/bin/Debug/symbol-properties/symbol-properties-database.csv`

### 手动查看已添加的 xStocks

```bash
grep "^kraken,.*USD,crypto,.*x/" "..\Lean\Data\symbol-properties\symbol-properties-database.csv"
```

## 6. Python 环境

### Conda 环境: lean

```bash
# 激活环境
conda activate lean

# 安装依赖
conda run -n lean pip install requests

# 查看 Python 版本
conda run -n lean python --version  # Python 3.11
```

## 7. 常见问题

### Q: 运行时提示 "Invalid api user id or token"
**A**: 需要注释 `KrakenBrokerage.cs` 第 543 行的 `ValidateSubscription()` 并重新编译。

### Q: 运行时提示 "Python DLL not found"
**A**: 确保 `PYTHONNET_PYDLL` 环境变量指向正确的 `python311.dll` 路径，或使用 `run.bat`（自动检测）。

### Q: xStocks 符号无法订阅
**A**: 运行 `python add_xstocks_to_symbol_database.py` 将 xStocks 添加到符号数据库。

### Q: 提示 "Symbol not found in symbol database"
**A**: 确保已运行 `add_xstocks_to_symbol_database.py`，并且 CSV 文件同时更新了两个位置（Data/ 和 Launcher/bin/Debug/）。

## 8. 算法说明

### main.py - 主算法

**功能**:
- 从 Kraken API 获取所有 xStocks
- 使用 `KrakenSymbolMapper` 检查符号是否在数据库中
- 订阅前 5 个可用的 xStocks（测试用）
- 接收实时 Tick 数据（bid/ask/spread）
- 每 100 个 tick 输出一次订单簿数据

**关键代码**:
```python
from QuantConnect.Brokerages.Kraken import KrakenSymbolMapper

# 初始化 mapper
self.kraken_mapper = KrakenSymbolMapper()

# 检查符号是否在数据库中
if self.kraken_mapper.IsKnownLeanSymbol(lean_symbol):
    crypto = self.add_crypto(symbol_str, Resolution.TICK, Market.KRAKEN)
```

### utils.py - 工具函数

**函数**:
- `get_xstocks_from_kraken()` - 从 Kraken API 获取 xStocks
- `map_xstocks_to_symbol_database()` - 映射为 CSV 格式
- `add_xstocks_to_database()` - 添加到数据库（带去重）
