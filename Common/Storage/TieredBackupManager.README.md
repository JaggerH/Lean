# TieredBackupManager 使用文档

## 概述

`TieredBackupManager` 是一个分层备份管理系统，用于自动管理算法状态的备份和清理，防止无限制的磁盘占用增长。

**核心特性：**
- ✅ 三层备份策略（分钟/小时/天）
- ✅ 自动清理旧备份
- ✅ 多存储后端支持
- ✅ 速率限制（防止过于频繁的备份）
- ✅ 备份恢复和统计

---

## 快速开始

### 1. 基本用法（使用默认配置）

```csharp
using QuantConnect.Storage;

public class MyAlgorithm : QCAlgorithm
{
    private TieredBackupManager _backupManager;

    public override void Initialize()
    {
        // 自动使用算法的 ObjectStore 和类型名称
        _backupManager = TieredBackupManager.Create(this);
    }

    // 保存备份
    private void SaveState()
    {
        var json = JsonConvert.SerializeObject(myState);
        _backupManager.SaveBackup(json);
    }

    // 恢复备份
    private void LoadState()
    {
        var json = _backupManager.RestoreLatest();
        if (json != null)
        {
            myState = JsonConvert.DeserializeObject<MyState>(json);
        }
    }
}
```

**默认配置：**
- **分钟层**：每 5 分钟一次，保留最近 50 个
- **小时层**：每 1 小时一次，保留最近 24 个
- **天层**：每 1 天一次，保留最近 7 个
- **存储后端**：算法的 ObjectStore

---

## 自定义配置

### 2. 自定义备份间隔和保留数量

```csharp
var options = new BackupOptions
{
    MinuteTier = new TierSettings("min", TimeSpan.FromMinutes(10), 30),   // 每10分钟，保留30个
    HourTier = new TierSettings("hour", TimeSpan.FromHours(2), 12),       // 每2小时，保留12个
    DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 14),      // 每1天，保留14个
    AlgorithmName = "MyCustomAlgorithm"  // 可选：自定义算法名称（默认使用类型名）
};

_backupManager = TieredBackupManager.Create(this, options);
```

### 3. 使用多个存储后端

```csharp
// 示例：同时备份到 ObjectStore 和自定义存储
var customStorage = new MyCustomBackupStorage();

var options = new BackupOptions
{
    // AdditionalStorages 会添加到默认的 ObjectStore 之后
    AdditionalStorages = new IBackupStorage[] { customStorage }
};

_backupManager = TieredBackupManager.Create(this, options);
```

### 4. 替换默认存储后端

```csharp
// 示例：只使用自定义存储，不使用 ObjectStore
var redisStorage = new RedisBackupStorage("localhost:6379");
var s3Storage = new S3BackupStorage("my-bucket");

var options = new BackupOptions
{
    // Storages 会完全替换默认的 ObjectStore
    Storages = new IBackupStorage[] { redisStorage, s3Storage }
};

_backupManager = TieredBackupManager.Create(this, options);
```

---

## API 参考

### TieredBackupManager

#### 工厂方法

```csharp
// 使用默认配置创建
public static TieredBackupManager Create(IAlgorithm algorithm)

// 使用自定义配置创建
public static TieredBackupManager Create(IAlgorithm algorithm, BackupOptions options)
```

#### 核心方法

```csharp
// 保存备份
// 返回 true 表示成功保存，false 表示速率限制（间隔未满足）
public bool SaveBackup(string content)

// 恢复最新备份
// 返回备份内容，如果没有备份则返回 null
public string RestoreLatest()

// 获取备份统计信息
public BackupStatistics GetStatistics()
```

### BackupOptions

```csharp
public class BackupOptions
{
    // 分钟层配置（默认：5分钟间隔，保留50个）
    public TierSettings MinuteTier { get; set; }

    // 小时层配置（默认：1小时间隔，保留24个）
    public TierSettings HourTier { get; set; }

    // 天层配置（默认：1天间隔，保留7个）
    public TierSettings DailyTier { get; set; }

    // 完全替换默认存储后端（如果指定，则不使用 ObjectStore）
    public IBackupStorage[] Storages { get; set; }

    // 添加到默认 ObjectStore 的额外存储后端
    public IBackupStorage[] AdditionalStorages { get; set; }

    // 自定义算法名称（默认使用 algorithm.GetType().Name）
    public string AlgorithmName { get; set; }

    // 获取默认配置
    public static BackupOptions Default { get; }
}
```

### TierSettings

```csharp
public class TierSettings
{
    // tier：层级名称（如 "min"、"hour"、"daily"）
    // interval：保存间隔（如 TimeSpan.FromMinutes(5)）
    // maxCount：最大保留数量（如 50）
    public TierSettings(string name, TimeSpan interval, int maxCount)
}
```

### BackupStatistics

```csharp
public class BackupStatistics
{
    public int MinuteCount { get; set; }      // 分钟层备份数量
    public int HourCount { get; set; }        // 小时层备份数量
    public int DailyCount { get; set; }       // 天层备份数量
    public int TotalCount { get; }            // 总备份数量
    public DateTime? OldestBackup { get; set; }  // 最旧备份时间
    public DateTime? NewestBackup { get; set; }  // 最新备份时间
}
```

---

## 工作原理

### 分层备份策略

1. **速率限制**：第一层（分钟层）的间隔作为全局速率限制
   - 如果距离上次备份不足 5 分钟，`SaveBackup()` 返回 `false`

2. **自动层级选择**：
   - 满足速率限制后，自动选择应该保存的层级
   - 优先级：分钟层 → 小时层 → 天层

3. **自动清理**：
   - 每次保存后自动检查该层级是否超过最大数量
   - 如果超过，删除最旧的备份

### 存储键格式

备份使用以下格式存储：
```
trade_data/{algorithmName}/backups/{tier}/{yyyyMMdd_HHmmss}
```

示例：
```
trade_data/MyAlgorithm/backups/min/20251126_030500
trade_data/MyAlgorithm/backups/hour/20251126_030000
trade_data/MyAlgorithm/backups/daily/20251126_000000
```

---

## 实现自定义存储后端

实现 `IBackupStorage` 接口：

```csharp
using QuantConnect.Storage;

public class RedisBackupStorage : IBackupStorage
{
    private readonly IDatabase _redis;

    public string Name => "Redis";

    public RedisBackupStorage(string connectionString)
    {
        var connection = ConnectionMultiplexer.Connect(connectionString);
        _redis = connection.GetDatabase();
    }

    public bool Save(string key, string content)
    {
        return _redis.StringSet(key, content);
    }

    public string Read(string key)
    {
        return _redis.StringGet(key);
    }

    public bool Delete(string key)
    {
        return _redis.KeyDelete(key);
    }

    public bool Exists(string key)
    {
        return _redis.KeyExists(key);
    }

    public IEnumerable<string> ListKeys(string prefix)
    {
        var server = _redis.Multiplexer.GetServer(_redis.Multiplexer.GetEndPoints().First());
        return server.Keys(pattern: $"{prefix}*").Select(k => k.ToString());
    }
}
```

---

## 最佳实践

### 1. 定期保存

```csharp
public override void Initialize()
{
    _backupManager = TieredBackupManager.Create(this);

    // 每5分钟尝试备份一次（受速率限制保护）
    Schedule.On(DateRules.EveryDay(), TimeRules.Every(TimeSpan.FromMinutes(5)),
        () => SaveState());
}
```

### 2. 启动时恢复

```csharp
public override void Initialize()
{
    _backupManager = TieredBackupManager.Create(this);

    // 首先尝试恢复状态
    LoadState();

    // 如果没有恢复到状态，初始化新状态
    if (_myState == null)
    {
        _myState = InitializeNewState();
    }
}
```

### 3. 监控备份统计

```csharp
private void LogBackupStats()
{
    var stats = _backupManager.GetStatistics();

    Log($"Backup Statistics:");
    Log($"  Total: {stats.TotalCount}");
    Log($"  Minute tier: {stats.MinuteCount}");
    Log($"  Hour tier: {stats.HourCount}");
    Log($"  Daily tier: {stats.DailyCount}");
    Log($"  Oldest: {stats.OldestBackup}");
    Log($"  Newest: {stats.NewestBackup}");
}
```

### 4. 优雅降级

```csharp
private void SaveState()
{
    try
    {
        var json = JsonConvert.SerializeObject(_myState);

        if (!_backupManager.SaveBackup(json))
        {
            // 速率限制 - 这是正常的，不需要特殊处理
            Debug("Backup skipped due to rate limit");
        }
    }
    catch (Exception ex)
    {
        Error($"Failed to save backup: {ex.Message}");
        // 不要让备份失败影响算法运行
    }
}
```

---

## 常见问题 (FAQ)

### Q: SaveBackup() 返回 false 是什么意思？
A: 表示距离上次备份的时间不足（未满足速率限制）。这是正常行为，不需要特殊处理。

### Q: 如何更改算法名称？
A: 在 `BackupOptions` 中设置 `AlgorithmName` 属性，否则默认使用 `algorithm.GetType().Name`。

### Q: 可以禁用某个层级吗？
A: 不建议。所有三个层级共同工作以提供合理的备份保留策略。如果确实需要，可以设置很大的间隔。

### Q: 备份会影响性能吗？
A: 影响很小。SaveBackup() 是快速的 I/O 操作，并且有速率限制保护。建议在调度事件中调用，而不是在 OnData() 中。

### Q: 如何从特定时间点恢复？
A: 当前只支持恢复最新备份。如果需要从特定时间点恢复，需要直接使用存储后端的 ListKeys() 和 Read() 方法。

### Q: 多个存储后端如何工作？
A: SaveBackup() 会写入所有存储后端。RestoreLatest() 只从第一个存储后端读取。

---

## 示例：TradingPairManager 集成

`TradingPairManager` 已集成 `TieredBackupManager`：

```csharp
public class TradingPairManager
{
    private readonly TieredBackupManager _backupManager;

    public TradingPairManager(AIAlgorithm algorithm)
    {
        // 自动初始化备份管理器
        _backupManager = TieredBackupManager.Create(algorithm);
    }

    // 保存状态（在对账方法中调用）
    private void PersistState()
    {
        var json = SerializeState();
        _backupManager.SaveBackup(json);  // 自动管理备份
    }

    // 恢复状态（启动时调用）
    public void RestoreState()
    {
        var json = _backupManager.RestoreLatest();
        if (json != null)
        {
            DeserializeState(json);
        }
    }
}
```

---

## 版本历史

- **v1.0** (2025-11-26)
  - 初始版本
  - 三层备份策略
  - 多存储后端支持
  - 自动清理和速率限制

---

## 相关文件

- `Common/Storage/TieredBackupManager.cs` - 主要实现
- `Common/Storage/BackupTypes.cs` - 数据类型定义
- `Common/Interfaces/IBackupStorage.cs` - 存储接口
- `Common/Storage/ObjectStoreBackupStorage.cs` - ObjectStore 实现
- `Tests/Common/Storage/TieredBackupManagerTests.cs` - 单元测试
