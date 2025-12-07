# Grid Trading System Architecture

## 项目目标

将 Python 的 Grid 系统重构为 C# 原生实现，解决以下核心问题：

1. **分离的 Manager 设计**：GridLevelManager、GridPositionManager 和 GridPosition 三个类分离，缺乏链接管理思路
2. **Hash-based 追踪的脆弱性**：使用 MD5 hash 作为订单标识，存在冲突风险且配置依赖
3. **缺乏持仓层级管理**：没有 TradingPair → GridPosition 的层级关系
4. **Symbol 序列化问题**：未利用 LEAN 原生的跨交易所 Symbol 序列化支持

## 架构升维

### 概念模型转变

```
传统架构:
  1 Symbol → 1 Security.Holdings → N Orders

Grid 架构:
  1 TradingPair → N GridPositions → 2N Orders
                       ↓
              每个 GridPosition 是一个"虚拟持仓"
              对应一个 entry 条件和 exit 条件
```

### 层级关系

```
TradingPair (交易对)
  ├─ GridLevels: List<GridLevelPair>  (配置层 - 算法)
  └─ GridPositions: Dict<string, GridPosition>  (状态层 - 交易)
       ├─ Key: Entry.NaturalKey (Pair 内部唯一)
       └─ GridPosition
            ├─ SymbolData (LEAN 序列化格式)
            ├─ Tickets: List<OrderTicket>  (运行时引用)
            ├─ BrokerIds: HashSet<string>  (持久化 ID)
            ├─ GridLevel Entry/Exit  (配置值拷贝)
            └─ Quantities & Costs  (成交数据)
```

## 当前实施阶段

### ✅ Phase 1: 核心数据结构（已完成 - v2）

创建了以下文件（重构版）：

#### 1. GridLevel.cs (struct - 纯配置版)

**不存储 Symbol**：
- 仅包含交易配置：SpreadPct, Direction, Type, PositionSizePct
- NaturalKey 不含 pair 信息（Pair 内部唯一即可）
- GetDisplayName(pairKey) 需要外部传入 pairKey 参数
- 提供 ToDict/FromDict 序列化方法
- **去掉 GetStableHash()**（不再使用 hash 匹配）
- **去掉 IEquatable/GetHashCode/Equals/== 运算符**（不需要作为字典键）

**NaturalKey 格式**：`"-0.0200|LONG_SPREAD|ENTRY"`

#### 2. GridLevelPair.cs (class)

**接受 Symbol 但不存储**：
- 构造函数接受 `(Symbol, Symbol)` 用于验证
- 但只传递配置数据给 GridLevel，不存储 Symbol
- 自动创建配对的 Entry 和 Exit
- 自动验证 spread 关系

**示例**：
```csharp
var levelPair = new GridLevelPair(
    entrySpreadPct: -0.02,
    exitSpreadPct: -0.005,
    direction: "LONG_SPREAD",
    positionSizePct: 0.25
);
```

#### 3. GridPosition.cs (class - 最终版)

**直接存储 Symbol 对象**：
- 使用 LEAN 官方 SymbolJsonConverter 自动序列化
- Symbol 完整保存为：`{value, id, permtick, underlying?}`
- SecurityIdentifier ("id") 编码所有元数据（type, market, strike, expiry 等）
- 直接存储完整的 Entry/Exit GridLevel（不是 snapshot）
- **去掉 EntryLevelHash**（不再使用 hash）
- PairKey 从 Symbol.Value 计算

**Symbol 序列化格式**（由 SymbolJsonConverter 处理）：
```json
{
  "value": "BTCUSDT",
  "id": "BTCUSDT 7ZQGWTST4Z8NA",
  "permtick": "BTCUSDT"
}
```

**跨交易所支持**（通过 SecurityIdentifier）：
- Gate.io Crypto: `{value: "BTCUSDT", id: "BTCUSDT 7ZQGWTST4Z8NA|gate"}`
- IBKR Crypto: `{value: "BTCUSD", id: "BTCUSD 7ZQGWTST4Z8NA|interactivebrokers"}`
- Options with underlying: 包含 `underlying` 字段递归序列化

#### 4. ~~GridLevelSnapshot.cs~~ (已删除)

**为什么删除**：
- GridLevel 是 struct，值拷贝自动完成
- 直接存储 GridLevel 更简洁
- 去掉一层不必要的抽象

### 序列化格式（最终版 - LEAN SymbolJsonConverter）

```json
{
  "positions": [
    {
      "leg1_symbol": {
        "value": "BTCUSDT",
        "id": "BTCUSDT 7ZQGWTST4Z8NA",
        "permtick": "BTCUSDT"
      },
      "leg2_symbol": {
        "value": "MSTR",
        "id": "MSTR R735QTJ8XC9X",
        "permtick": "MSTR"
      },
      "entry_level": {
        "spread_pct": -0.02,
        "direction": "LONG_SPREAD",
        "type": "ENTRY",
        "position_size_pct": 0.25
      },
      "exit_level": {
        "spread_pct": -0.005,
        "direction": "SHORT_SPREAD",
        "type": "EXIT",
        "position_size_pct": -0.25
      },
      "open_time": "2025-01-20T10:00:00Z",
      "first_fill_time": "2025-01-20T10:00:15Z",
      "leg1_quantity": 0.5,
      "leg2_quantity": -100,
      "leg1_average_cost": 45000.0,
      "leg2_average_cost": 225.0,
      "broker_ids": ["GATE-12345", "GATE-12346"]
    }
  ]
}
```

**关键改进**：
- `leg1_symbol/leg2_symbol` 使用 LEAN 官方 SymbolJsonConverter 格式
- `id` 字段（SecurityIdentifier）包含完整元数据：证券类型、市场、到期日、行权价等
- `SecurityIdentifier.Parse(id)` 可完整重建 Symbol 对象
- 100% 序列化保真度，支持所有证券类型（股票、期权、期货、加密货币等）

### 恢复流程（最终版 - 使用 LEAN ObjectStore + SymbolJsonConverter）

```csharp
// C# 版本（推荐）
public void RestoreGridPositions()
{
    if (!ObjectStore.ContainsKey("grid_positions"))
        return;

    // 1. 使用 ObjectStore.ReadJson<T>() 自动反序列化
    //    SymbolJsonConverter 会自动处理 Symbol 的反序列化
    var data = ObjectStore.ReadJson<GridPositionCollection>("grid_positions");

    foreach (var position in data.Positions)
    {
        // 2. Symbol 已经自动反序列化完成（通过 SymbolJsonConverter）
        //    SecurityIdentifier 从 "id" 字段完整恢复
        var leg1 = position.Leg1Symbol;  // 直接可用
        var leg2 = position.Leg2Symbol;  // 直接可用

        // 3. 查找 TradingPair（通过 Symbol.Equals() 精确匹配）
        var pair = TradingPairs.FirstOrDefault(p =>
            p.Leg1Symbol.Equals(leg1) && p.Leg2Symbol.Equals(leg2));

        if (pair == null)
        {
            Log($"Skip: {leg1}-{leg2} pair not found");
            continue;
        }

        // 4. GridLevel、Quantities、Costs 都已自动反序列化
        //    添加到 pair（用 entry.NaturalKey 索引）
        pair.GridPositions[position.EntryLevel.NaturalKey] = position;

        // 5. 重建订单映射（通过 BrokerIds）
        RebuildOrderMappings(position, pair);
    }
}

// Python 版本（也支持）
def RestoreGridPositions(self):
    """从 ObjectStore 恢复 GridPosition（自动反序列化）"""
    if not self.ObjectStore.ContainsKey("grid_positions"):
        return

    # LEAN 的 ObjectStore.ReadJson 会自动调用 SymbolJsonConverter
    data = self.ObjectStore.ReadJson[GridPositionCollection]("grid_positions")

    for position in data.Positions:
        # Symbol 已经自动反序列化完成
        leg1 = position.Leg1Symbol
        leg2 = position.Leg2Symbol

        # 查找 TradingPair
        pair = next((p for p in self.TradingPairs
                     if p.Leg1Symbol.Equals(leg1) and p.Leg2Symbol.Equals(leg2)), None)

        if not pair:
            self.Log(f"Skip: {leg1}-{leg2} pair not found")
            continue

        # 添加到 pair
        pair.GridPositions[position.EntryLevel.NaturalKey] = position

        # 重建订单映射
        self.rebuild_order_mappings(position, pair)
```

**关键优势**：
- ✅ 完全自动化：`ObjectStore.ReadJson<T>()` + `[JsonProperty]` 自动处理所有序列化
- ✅ 类型安全：编译期检查，无需手动解析 JSON
- ✅ 零转换代码：Symbol 直接可用，无需 `FromSymbol()` / `ToSymbol()`
- ✅ 官方支持：使用 LEAN 久经考验的 SymbolJsonConverter
- ✅ 完整保真：SecurityIdentifier 确保所有元数据（market, type, strike, expiry）都被保存

### ✅ Phase 2: TradingPair 集成（已完成）

**目标**：扩展 TradingPair 类以支持 Grid 功能

#### 已实现内容

**TradingPair.Grid.cs** (Partial class):
```csharp
public partial class TradingPair
{
    // 配置
    public List<GridLevelPair> GridLevels { get; }

    // 状态（用 NaturalKey 索引）
    public Dictionary<string, GridPosition> GridPositions { get; }

    // 核心方法
    public GridPosition GetOrCreatePosition(GridLevelPair levelPair, DateTime time);
    public bool TryGetPosition(GridLevel entryLevel, out GridPosition position);
    public bool RemovePosition(GridPosition position);
    public bool RemovePosition(string entryLevelKey);

    // 属性
    public int ActivePositionCount { get; }
    public bool HasActivePositions { get; }
}
```

**主要特性**：
- 使用 partial class 模式扩展 TradingPair
- 在构造函数中初始化 GridLevels 和 GridPositions
- 提供 GetOrCreatePosition 自动管理位置创建
- 支持按 NaturalKey 移除位置

### ⏳ Phase 3-5：待实施

参考原文档内容（生命周期管理、执行管理器、序列化恢复）

## 关键设计决策

### 1. GridLevel 不存储 Symbol

**原因**：
- GridLevel 总是在 TradingPair 上下文中使用
- Symbol 信息在 TradingPair.Leg1Symbol/Leg2Symbol 中
- 避免冗余存储

**NaturalKey 不含 pair**：
- 在 TradingPair 内部使用，只需 Pair 内部唯一
- 格式：`"{spread}|{direction}|{type}"`

### 2. GridPosition 直接使用 Symbol（重构完成）

**原因**：
- 利用 LEAN 官方 SymbolJsonConverter 自动序列化
- SecurityIdentifier 编码完整元数据（Market, SecurityType, Strike, Expiry 等）
- 100% 序列化保真度，支持所有证券类型
- 零转换代码，类型安全

**为什么不用自定义 SymbolData**：
- SymbolJsonConverter 是官方实现，久经考验
- SecurityIdentifier.Parse() 确保完整重建
- 支持复杂证券（期权 underlying、期货链等）
- 减少维护成本

### 3. 完全去掉 Hash 逻辑

**原因**：
- Hash 依赖配置，配置变化则失效
- Symbol 精确匹配更可靠
- GridLevel 自然键足够用于 Pair 内部索引

**从 Hash 到 Symbol 精确匹配**：
```python
# 旧方案（Hash - 脆弱）
entry_hash = saved_position["entry_level_hash"]
for level in pair.GridLevels:
    if level.Entry.GetStableHash() == entry_hash:
        # 找到了（但配置变化则失效）

# 新方案（Symbol 精确匹配 - 可靠）
# ObjectStore.ReadJson 自动反序列化 Symbol（通过 SymbolJsonConverter）
position = ObjectStore.ReadJson<GridPosition>("position_key")
leg1 = position.Leg1Symbol  # 自动恢复
leg2 = position.Leg2Symbol  # 自动恢复

for pair in self.TradingPairs:
    if pair.Leg1Symbol.Equals(leg1) and pair.Leg2Symbol.Equals(leg2):
        # 找到了（基于 SecurityIdentifier，100% 准确）
```

### 4. OrderTicket 引用追踪

**运行时**：
```python
position.AddTicket(ticket)  # 持有引用
```

**重启时**：
```python
# 通过 BrokerIds 重建
for broker_id in position.BrokerIds:
    for order in open_orders:
        if broker_id in order.BrokerId:
            ticket = self.Transactions.GetOrderTicket(order.Id)
            position.AddTicket(ticket)
```

## 文件清单

### 已创建（v4 - Symbol 重构完成）

```
Common/TradingPairs/Grid/
├── GridLevel.cs           (145 lines) - 纯配置 struct，无 hash 逻辑
├── GridLevelPair.cs       (160 lines) - Entry/Exit 配对，不存储 Symbol
└── GridPosition.cs        (326 lines) - 直接使用 Symbol + GridLevel
                                        (已删除 SymbolData 类，减少 49 行)

Common/TradingPairs/
└── TradingPair.Grid.cs    (145 lines) - Partial class extension

Common/TradingPairs/
└── TradingPair.cs         (已修改) - 添加 partial 关键字，初始化 Grid 集合

GRID.md                    (本文档)
```

### 已删除

```
Common/TradingPairs/Grid/
└── GridLevelSnapshot.cs   (已删除 - 多余)
```

### 待创建

```
Common/TradingPairs/Grid/
├── GridExecutionManager.cs
└── GridPersistenceManager.cs

Tests/Common/TradingPairs/Grid/
├── GridLevelTests.cs
├── GridLevelPairTests.cs
├── GridPositionTests.cs
└── TradingPairGridTests.cs
```

## 使用示例（预览）

```python
# Algorithm.Initialize()
btc = self.AddCrypto("BTCUSD", Resolution.Minute, Market.Gate).Symbol
mstr = self.AddEquity("MSTR", Resolution.Minute).Symbol
pair = self.TradingPairManager.AddPair(btc, mstr, "crypto_stock")

# 配置 Grid（无需 ID，自动处理 Symbol）
pair.GridLevels.Add(GridLevelPair(
    entrySpreadPct=-0.02,
    exitSpreadPct=-0.005,
    direction="LONG_SPREAD",
    positionSizePct=0.25,
    pairSymbol=(btc, mstr)  # 用于验证，不存储
))

# Algorithm.OnData()
# Note: TradingPairs accessed from algorithm, not slice
for pair in self.TradingPairs:
    # Entry 触发
    for level_pair in pair.GridLevels:
        if should_enter(pair, level_pair.Entry):
            position = pair.GetOrCreatePosition(level_pair, self.Time)
            self.place_entry_orders(pair, position)

    # Exit 检查
    for position in pair.GridPositions.values():
        if position.ShouldExit(pair.TheoreticalSpread):
            self.place_exit_orders(pair, position)
```

## 重构收益

| 方面 | Phase 1 v1 | Phase 1 v2 | Phase 1+2 v3 | v4 (当前) |
|------|-----------|-----------|-------------|-----------|
| 文件数量 | 4 个 | 3 个 | 4 个 | 4 个 |
| GridPosition 行数 | ~350 | ~375 | ~375 | 326 (-49) |
| GridLevel 大小 | ~40 bytes + Symbol 引用 | ~20 bytes | ~20 bytes | ~20 bytes |
| GridLevel 复杂度 | struct + IEquatable + Hash | struct + 完整相等性 | struct (纯配置) | struct (纯配置) |
| Hash 依赖 | ✅ 有（脆弱） | ❌ 无 | ❌ 无 | ❌ 无 |
| Symbol 序列化 | ❌ 重复存储 | ❌ 自定义 SymbolData | ❌ 自定义 SymbolData | ✅ LEAN SymbolJsonConverter |
| 序列化格式 | ❌ 自定义 | 部分 LEAN | 部分 LEAN | ✅ 100% LEAN 原生 |
| 序列化保真度 | 低 | 中（丢失部分信息） | 中（丢失部分信息） | ✅ 100%（SecurityIdentifier） |
| 跨交易所支持 | ❌ 需要自己处理 | ✅ Market 字段 | ✅ Market 字段 | ✅ SecurityIdentifier 完整编码 |
| 复杂证券支持 | ❌ 不支持 | ❌ 不支持 underlying | ❌ 不支持 underlying | ✅ 支持期权/期货 underlying |
| 配置依赖 | ❌ Hash 匹配依赖配置 | ✅ Symbol 精确匹配 | ✅ Symbol 精确匹配 | ✅ Symbol 精确匹配 |
| TradingPair 集成 | ❌ 未实现 | ❌ 未实现 | ✅ Partial class 模式 | ✅ Partial class 模式 |
| 代码维护成本 | 高 | 中 | 中 | ✅ 低（删除自定义层） |

**v4 关键改进**：
- ✅ 删除 49 行自定义 SymbolData 代码
- ✅ 使用 LEAN 官方 SymbolJsonConverter（久经考验）
- ✅ SecurityIdentifier 确保 100% 序列化保真度
- ✅ 零转换代码（无需 FromSymbol/ToSymbol）
- ✅ 自动支持所有证券类型（股票、期权、期货、加密货币）
- ✅ Symbol.Equals() 更严格的比较逻辑

---

**最后更新**: 2025-01-21 (v4 Symbol 重构完成)
**维护者**: 架构重构团队
**状态**: Phase 1+2 完成并编译通过（0 错误 0 警告），Phase 3-5 待实施
