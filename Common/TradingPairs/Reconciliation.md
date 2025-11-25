# TradingPairManager 对账机制

## 概述

对账机制确保 TradingPairManager 的内部状态(GridPositions)与实际投资组合状态保持同步,即使面对网络断开、订单事件丢失或其他系统故障也能保持一致。

### 设计目标

1. **检测差异** 投资组合持仓与网格仓位聚合之间的差异
2. **恢复丢失的成交** 通过查询券商的执行历史
3. **防止重复处理** 通过基于 ExecutionId 的去重
4. **维护状态连续性** 通过检查点机制在算法重启后恢复
5. **高效运行** 最小化性能开销

### 设计原则

- **基线驱动**: 跟踪预期差异 (LP - GP) 作为基线,检测实际差异
- **ExecutionId 去重**: 防止重复处理的主要防护
- **基于时间的过滤**: 避免处理旧执行记录的次要防护
- **基于检查点的恢复**: 对于处理 ExecutionHistory 保留限制至关重要

---

## 对账触发器

### 1. 定期基线比较(主要)

**频率**: 在实盘模式下每 5 分钟一次

**入口点**: `AQCAlgorithm.PostInitialize()` (第 78-90 行)

**流程**:
```
定时任务(每 5 分钟)
    ↓
TradingPairs.CompareBaseline(Portfolio)
    ├─ 计算当前 (LP - GP)
    ├─ 与存储的 _baseline 比较
    └─ 如果检测到差异:
        ├─ 调用 Reconciliation()
        └─ 调用 PersistState()
    └─ 如果没有差异:
        ├─ 调用 CleanupProcessedExecutions()
        └─ 调用 PersistState()
```

**目的**: 定期健康检查,捕捉任何丢失的成交或状态漂移。

### 2. 重连触发(次要)

**触发器**: `OnBrokerageReconnect()` 事件

**入口点**: `AQCAlgorithm.OnBrokerageReconnect()` (第 98-111 行)

**流程**:
```
Brokerage.Message (重连事件)
    ↓
Engine → Algorithm.OnBrokerageReconnect()
    ↓
TradingPairs.CompareBaseline(Portfolio)
    └─ (与定期检查相同的流程)
```

**目的**: 连接恢复后立即对账,捕捉断开期间的成交。

### 3. 手动调用(测试/调试)

**入口点**: 直接调用 `TradingPairs.Reconciliation()`

**用途**: 集成测试、调试、强制对账

---

## 对账流程架构

### 完整流程图

```
1. 触发器(定时/重连/手动)
   ↓
2. CompareBaseline(Portfolio)
   ├─ 计算当前基线: LP - GP
   │   ├─ LP (账本仓位): 投资组合持仓
   │   └─ GP (网格仓位): 所有 GridPosition 数量的聚合
   ├─ 与存储的 _baseline 比较
   └─ 检测差异
   ↓
3. 如果检测到差异 → Reconciliation()
   ├─ 确定查询时间范围
   │   └─ startTime = min(_lastFillTimeByMarket) - 5 分钟
   ├─ 查询 ExecutionHistoryProvider.GetExecutionHistory(startTime, endTime)
   ├─ 通过 ShouldProcessExecution() 过滤执行记录
   │   ├─ ExecutionId 去重(第一层)
   │   └─ 基于时间的过滤(第二层)
   ├─ 转换 ExecutionRecord → OrderEvent
   └─ 对每个执行记录调用 ProcessGridOrderEvent()
   ↓
4. ProcessGridOrderEvent()
   ├─ ExecutionId 去重检查
   ├─ 从标签解析订单上下文
   ├─ 更新 GridPosition 数量/成本
   ├─ 在 _processedExecutions 中记录执行
   └─ 更新 _lastFillTimeByMarket
   ↓
5. 对账完成后(或没有差异):
   └─ PersistState() 将 3 个组件保存到 ObjectStore
      ├─ GridPositions (所有交易对,扁平化)
      ├─ _lastFillTimeByMarket
      └─ _processedExecutions
```

---

## 状态持久化策略

### 内存状态(C#)

三个关键字典维护对账状态:

1. **`_processedExecutions`**: `Dictionary<string, ExecutionSnapshot>`
   - 目的: 基于 ExecutionId 的去重
   - 内容: {ExecutionId, TimeUtc, Market}
   - 生命周期: 在成功的基线检查后清理

2. **`_lastFillTimeByMarket`**: `Dictionary<string, DateTime>`
   - 目的: 对账查询的基于时间的过滤
   - 内容: Market → 最后成交时间戳
   - 生命周期: 每次成交时更新,与状态一起持久化

3. **`_baseline`**: `Dictionary<Symbol, decimal>`
   - 目的: 用于差异检测的预期差异 (LP - GP)
   - 内容: Symbol → 预期差异数量
   - 生命周期: 初始化一次,用于比较

### 持久化状态(ObjectStore) - 关键检查点

**时机**: 成功对账后(每 5 分钟,或重连时)

**内容**: 完整的 TradingPairManager 状态,包含 3 个组件:

1. **GridPositions** (从所有交易对扁平化)
   - 直接序列化 GridPosition 对象数组,无额外包装层
   - 通过 JsonProperty 属性自动序列化: first_fill_time, leg1/leg2 symbols/quantities/costs
   - 包含嵌套的 level_pair 配置(entry/exit 级别)

2. **_lastFillTimeByMarket** (Dictionary<string, DateTime>)
   - 重启时基于时间的过滤所需
   - 决定对账查询的开始时间

3. **_processedExecutions** (Dictionary<string, ExecutionSnapshot>)
   - 重启时 ExecutionId 去重所需
   - 防止重启后重复处理执行记录

**位置**:
- 最新: `trade_data/trading_pair_manager/state`
- 备份: `trade_data/trading_pair_manager/backups/{yyyyMMdd_HHmmss}`

**格式**: 带版本控制和时间戳的 JSON

**重要变化**:
- `grid_positions` 直接存储 GridPosition 对象数组(扁平化),无额外包装
- GridPosition 包含完整信息: symbols, quantities, costs, level_pair
- 依靠 JsonProperty 属性自动序列化(无需手动构建嵌套结构)

```json
{
  "timestamp": "2025-11-25T10:30:00Z",
  "version": "1.0",
  "grid_positions": [
    {
      "first_fill_time": "2025-11-25T10:28:30Z",
      "leg1_symbol": "BTCUSD XYJKLZ",
      "leg2_symbol": "MSTR R735QTJ8XC9X",
      "leg1_quantity": 0.5000,
      "leg2_quantity": -150.0000,
      "leg1_average_cost": 95234.50,
      "leg2_average_cost": 318.25,
      "level_pair": {
        "entry": {
          "spread_pct": -0.0200,
          "direction": "LONG_SPREAD",
          "type": "ENTRY",
          "position_size_pct": 0.25
        },
        "exit": {
          "spread_pct": 0.0100,
          "direction": "SHORT_SPREAD",
          "type": "EXIT",
          "position_size_pct": -0.25
        }
      }
    }
  ],
  "last_fill_time_by_market": [
    {
      "market": "coinbase",
      "last_fill_time": "2025-11-25T10:29:45Z"
    },
    {
      "market": "tradier",
      "last_fill_time": "2025-11-25T10:29:43Z"
    }
  ],
  "processed_executions": [
    {
      "execution_id": "exec_123456",
      "snapshot": {
        "execution_id": "exec_123456",
        "time_utc": "2025-11-25T10:29:30Z",
        "market": "coinbase"
      }
    }
  ]
}
```

**GridPosition 字段说明**:
- `first_fill_time`: 仓位首次成交时间
- `leg1_symbol/leg2_symbol`: 使用 LEAN 的 SymbolJsonConverter 自动序列化
- `leg1_quantity/leg2_quantity`: 带符号的数量(正=long,负=short)
- `leg1_average_cost/leg2_average_cost`: 加权平均成本
- `level_pair`: 嵌套的网格级别配置(entry + exit)

**实现细节** (`TradingPairManager.Reconciliation.cs`):

1. **保存 (PersistState, 第 338-400 行)**:
   ```csharp
   // 1. 直接收集所有 GridPosition 对象(无包装)
   var allGridPositions = new List<Grid.GridPosition>();
   foreach (var pair in GetAll()) {
       foreach (var position in pair.GridPositions.Values) {
           allGridPositions.Add(position);  // 直接添加对象
       }
   }

   // 2. 依赖 JsonProperty 自动序列化
   var stateData = new {
       grid_positions = allGridPositions,  // 自动序列化为完整 JSON
       // ...
   };
   ```

2. **恢复 (RestoreState, 第 406-477 行)**:
   ```csharp
   // 1. 反序列化 GridPosition (使用 JsonConstructor)
   var position = JsonConvert.DeserializeObject<GridPosition>(posData.ToString());

   // 2. 确保 TradingPair 存在(幂等)
   var pair = AddPair(position.Leg1Symbol, position.Leg2Symbol);

   // 3. 恢复父引用(GridPosition.Invested 属性需要)
   position.SetTradingPair(pair);

   // 4. 使用 Tag 属性作为字典键
   var tag = position.Tag;  // 从 level_pair 计算得出
   pair.GridPositions[tag] = position;
   ```

**关键设计决策**:
- **扁平化存储**: 所有 GridPosition 存储在单一数组中,避免嵌套 TradingPair 层级
- **自动序列化**: GridPosition 类已配置 JsonProperty,无需手动构建 JSON
- **Tag 重建**: 恢复时使用 `position.Tag` 属性(从 level_pair 计算)作为字典键
- **父引用恢复**: 调用 `SetTradingPair()` 以恢复 `Invested` 属性所需的父引用

### 为什么检查点至关重要(不仅仅是优化)

**ExecutionHistoryProvider 有时间限制**:
- 典型保留期: 券商级别 7-30 天
- 保留期过后: 数据**永久丢失**

**没有检查点**:
- 30 天后算法重启 = 无法查询完整的执行历史
- 缺失的执行记录 = GridPosition 状态无法重建
- 结果: **永久数据丢失**

**有检查点**:
- 恢复最后一个检查点(< 7 天前)
- 从检查点时间到现在查询 ExecutionHistory
- 只要检查点在保留期内就能完全恢复

**安全边际**:
- 检查点频率: 5 分钟
- 保留期: 7+ 天
- 安全边际: 5 分钟 << 7 天 = **充足的覆盖范围**

### 为什么不在每次成交后保存?

**每次成交方法**:
- 频率: 活跃交易期间约每小时数百次
- 风险: 存储写入过多,可能导致写入不完整
- 好处: 实时状态备份

**对账后保存方法**(已选择):
- 频率: 每小时约 12 次(每 5 分钟)
- 好处: 保证状态一致性,平衡写入负载
- 理由: ExecutionHistory 可以恢复检查点之间的成交

---

## 去重和过滤机制

### 1. ExecutionId 去重(主要)

**目的**: 防止重复处理同一执行记录

**实现**: `_processedExecutions` 字典

**逻辑** (`ShouldProcessExecution` - 第 228 行):
```csharp
if (_processedExecutions.ContainsKey(execution.ExecutionId))
{
    return false; // 跳过 - 已处理
}
```

**何时记录**: 成功执行 `ProcessGridOrderEvent()` 后

**清理**: 基线检查后移除 `TimeUtc < lastFillTime` 的执行记录

### 2. 基于时间的过滤(次要)

**目的**: 避免处理非常旧的执行记录,减少查询负载

**实现**: `_lastFillTimeByMarket` 字典

**逻辑** (`ShouldProcessExecution` - 第 234 行):
```csharp
if (_lastFillTimeByMarket.TryGetValue(market, out var lastFillTime))
{
    if (execution.TimeUtc < lastFillTime)
    {
        return false; // 跳过 - 比最后处理的成交更旧
    }
}
```

**边缘情况处理**: 保留时间相等的执行记录(可能是并发订单)

### 3. 清理策略

**时机**: CompareBaseline 确认没有差异后

**方法**: `CleanupProcessedExecutions()` (第 299 行)

**逻辑**:
- 移除 `TimeUtc < lastFillTime` 的执行记录
- 保留时间相等的执行记录(并发订单安全)
- 仅在状态一致时清理(安全操作)

**目的**: 防止 `_processedExecutions` 字典无限增长

---

## 恢复机制

### 冷启动(算法重启)

**入口点**: `AQCAlgorithm.PostInitialize()` → `TradingPairs.RestoreState()`

**流程**:
```
1. RestoreState() 从 ObjectStore 加载检查点
   ├─ 恢复所有 TradingPairs 的 GridPositions
   ├─ 恢复 _lastFillTimeByMarket (时间过滤状态)
   └─ 恢复 _processedExecutions (去重缓存)

2. 提取检查点时间戳

3. Reconciliation() 查询 ExecutionHistory
   ├─ startTime = 检查点时间戳
   ├─ endTime = DateTime.UtcNow
   └─ 使用恢复的 _lastFillTimeByMarket 和 _processedExecutions

4. 对每个执行记录调用 ProcessGridOrderEvent()
   ├─ 时间过滤使用恢复的状态
   └─ 去重使用恢复的缓存

5. InitializeBaseline() 建立新基线

6. 恢复定期对账(每 5 分钟)
```

**关键要求**: 检查点时间戳必须在 ExecutionHistoryProvider 的保留期内。

**为什么需要全部 3 个组件**:
- **仅 GridPositions**: 无法过滤重复执行 → 重复计数
- **+ _processedExecutions**: 无法按时间过滤 → 可能处理非常旧的执行记录
- **+ _lastFillTimeByMarket**: 完整状态 → 正确对账

**恢复保证**:
- ✅ 如果检查点在 ExecutionHistory 保留期内: **可以完全恢复**
- ⚠️ 如果检查点早于保留期: **部分数据丢失**(检查点和保留期之间的间隙)
- 💡 解决方案: 确保检查点频率 << 保留期

### 热重连(连接恢复)

**入口点**: `OnBrokerageReconnect()` → `TradingPairs.CompareBaseline()`

**流程**:
```
1. OnBrokerageReconnect() 触发立即对账

2. 使用现有的 _lastFillTimeByMarket 作为查询开始时间
   └─ 无需从检查点恢复(内存状态完好)

3. ExecutionHistoryProvider 获取断开期间的丢失成交

4. 时间过滤 + ExecutionId 去重防止重复

5. 增量更新 GridPosition 状态

6. 对账后 PersistState() 保存更新的状态
```

**优势**: 比冷启动更快,不需要状态恢复

---

## 券商要求

### IExecutionHistoryProvider 接口

券商必须实现:

```csharp
public interface IExecutionHistoryProvider
{
    List<ExecutionRecord> GetExecutionHistory(DateTime startTimeUtc, DateTime endTimeUtc);
}
```

**参考**: `Common/Interfaces/IExecutionHistoryProvider.cs`

### ExecutionRecord 字段

必需字段:

```csharp
public class ExecutionRecord
{
    public string ExecutionId { get; set; }    // 唯一,券商提供
    public Symbol Symbol { get; set; }
    public decimal Quantity { get; set; }      // 带符号(买/卖)
    public decimal Price { get; set; }
    public DateTime TimeUtc { get; set; }      // 执行时间戳
    public string Tag { get; set; }            // 用于上下文解析的订单标签
    public decimal Fee { get; set; }
    public string FeeCurrency { get; set; }
}
```

**参考**: `Common/TradingPairs/ExecutionRecord.cs`

### ExecutionId 保证

1. **唯一性**: 每个执行记录必须唯一(全局或每个市场)
2. **稳定性**: 重复查询时同一执行记录返回相同 ID
3. **来源**: 应由券商 API 提供(非客户端生成)
4. **格式**: 字符串,任何格式均可(通常为字母数字)

### 连接事件处理

券商必须:

1. 连接恢复时触发 `BrokerageMessageEvent.Reconnected()`
2. 确保 Engine 调用 `Algorithm.OnBrokerageReconnect()`

**参考**: `Common/Brokerages/BrokerageMessageEvent.cs`

### 参考实现

- **InteractiveBrokers**: `Brokerages/InteractiveBrokers/InteractiveBrokersBrokerage.cs`
- **Provider 包装器**: `Engine/ExecutionHistory/BrokerageExecutionHistoryProvider.cs`
- **多账户聚合**: `Engine/MultiBrokerageManager.cs` (第 468-510 行)

---

## 测试覆盖

### 单元测试 (`TradingPairManagerReconciliationTests.cs`)

**总计**: 24 个综合测试

**类别**:

1. **AggregateGridPositions** (6 个测试)
   - 空管理器
   - 单个/多个交易对
   - 仓位聚合
   - 净仓位
   - 零数量

2. **CalculateBaseline** (7 个测试)
   - 投资组合匹配 GP
   - 空投资组合/GP
   - 投资组合 > GP / < GP
   - Symbol 边缘情况
   - 零差异过滤

3. **CompareBaseline** (6 个测试)
   - 基线匹配当前
   - 单个/多个差异
   - 基线/当前 symbol 不匹配
   - 空基线/当前

4. **ExecutionHistoryProvider 集成** (5 个测试)
   - Provider 注入
   - Null 处理
   - 空结果
   - 执行处理
   - 时间范围验证

**参考**: `Tests/Common/TradingPairs/TradingPairManagerReconciliationTests.cs`

### 手动测试场景

1. **断开测试**:
   - 活跃交易期间断开券商连接
   - 重连
   - 验证对账被触发
   - 验证丢失的成交被恢复

2. **差异测试**:
   - 创建手动仓位差异
   - 等待定期检查(最多 5 分钟)
   - 验证检测和对账

3. **重启测试**:
   - 运行有活跃仓位的算法
   - 停止算法
   - 重启算法
   - 验证从 ObjectStore 恢复 GridPosition
   - 验证对账捕获丢失的成交

4. **去重测试**:
   - 多次处理相同的 ExecutionId
   - 验证去重防止重复计数

---

## 配置和调优

### 1. 对账频率

**默认**: 5 分钟

**位置**: `AQCAlgorithm.cs` 第 80 行

**调整**:
```csharp
TimeRules.Every(System.TimeSpan.FromMinutes(N))
```

**权衡**:
- 更频繁 = 更快的差异检测
- 更频繁 = 更多的 ExecutionHistoryProvider 查询
- 建议范围: 1-15 分钟

### 2. 时间查询缓冲

**默认**: min(_lastFillTimeByMarket) - 5 分钟

**位置**: `TradingPairManager.Reconciliation.cs` 第 163 行

**目的**: 时间相等执行的安全缓冲

**调整**: 在 `Reconciliation()` 方法中修改缓冲值

### 3. 清理阈值

**逻辑**: 移除 `TimeUtc < lastFillTime` 的执行记录

**安全**: 保留时间相等的执行记录(并发订单保护)

**触发器**: 仅在未检测到差异时(安全状态)

### 4. 检查点保留策略

**最新**: `trade_data/trading_pair_manager/state`

**备份**: `trade_data/trading_pair_manager/backups/{timestamp}`

**保留**: 建议最少 7 天(与 ExecutionHistory 保留对齐)

**未来**: 自动清理早于保留期的备份

**云备份**: 考虑多区域复制(S3, Azure Blob)

---

## 已知限制和未来工作

### 当前限制

1. **仅实盘模式**: 回测中禁用对账(设计使然)
2. **券商依赖**: 需要 IExecutionHistoryProvider 实现
3. **无自动重试**: ExecutionHistoryProvider 失败不重试
4. **数据丢失风险**: 如果检查点早于 ExecutionHistory 保留期
5. **无损坏检测**: 检查点完整性未验证

### 未来增强

1. **检查点验证**: 启动时验证检查点年龄 < 保留期
2. **多区域备份**: 将检查点复制到云存储
3. **检查点清理**: 自动删除早于保留策略的备份
4. **检查点完整性**: 添加校验和/签名以检测损坏
5. **指标/监控**: 跟踪对账频率、差异计数
6. **通知**: 对账事件的电子邮件/webhook 警报
7. **对账历史**: 所有对账操作的审计日志

---

## 总结

对账机制通过以下方式为 TradingPairManager 提供强大的状态管理:

- **多层保护**: 基线比较 + ExecutionId 去重 + 时间过滤
- **关键检查点**: 状态持久化确保在 ExecutionHistory 限制内恢复
- **灵活触发器**: 定期 + 重连 + 手动调用
- **全面测试**: 24 个单元测试覆盖所有核心功能

**关键要点**: 检查点不是可选的优化——结合 ExecutionHistory 保留限制,它们对于防止永久数据丢失至关重要。
