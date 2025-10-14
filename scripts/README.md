# LEAN 数据转换脚本

本目录包含用于将各种数据源转换为 LEAN 格式的脚本。

## 目录结构

```
scripts/
├── data_converter_cli.py          # 统一交互式入口（推荐）
└── converters/                     # 转换器模块
    ├── __init__.py
    ├── gateio_depth_convertor.py   # Gate.io 深度数据转换器
    ├── gateio_trade_convertor.py   # Gate.io 交易数据转换器
    └── nasdaq_data_convertor.py    # Nasdaq 数据转换器
```

## 快速开始

### 使用交互式 CLI（推荐）

从项目根目录运行：

```bash
python scripts/data_converter_cli.py
```

或者从 scripts 目录运行：

```bash
cd scripts
python data_converter_cli.py
```

按照提示选择数据源、格式和符号即可。

### 使用独立转换器

每个转换器也可以独立使用：

**Gate.io 深度数据：**
```bash
python scripts/converters/gateio_depth_convertor.py
python scripts/converters/gateio_depth_convertor.py --symbol AAPLX_USDT
python scripts/converters/gateio_depth_convertor.py --input raw_data/gate_orderbook_tick/202509 --output Data/crypto/kraken/tick
```

**Gate.io 交易数据：**
```bash
python scripts/converters/gateio_trade_convertor.py
python scripts/converters/gateio_trade_convertor.py --symbol TSLAX_USDT
python scripts/converters/gateio_trade_convertor.py --input raw_data/gate_trade_tick --output Data/crypto/kraken/tick
```

**Nasdaq 数据：**
```bash
python scripts/converters/nasdaq_data_convertor.py
python scripts/converters/nasdaq_data_convertor.py --type quote --symbol AAPL
python scripts/converters/nasdaq_data_convertor.py --type all --symbol TSLA
```

## 支持的数据源

### 1. Gate.io（加密货币）

**可用数据类型：**
- ✅ **Depth**（深度数据）：订单簿快照
- ✅ **Trade**（交易数据）：逐笔成交

**支持符号：**
- AAPLX_USDT → AAPLXUSD
- TSLAX_USDT → TSLAXUSD

**输入数据结构：**
```
raw_data/
├── gate_orderbook_tick/
│   └── 202509/
│       ├── AAPLX_USDT-2025090201.csv.gz  (hourly depth updates)
│       ├── AAPLX_USDT-2025090202.csv.gz
│       └── ...
└── gate_trade_tick/
    ├── AAPLX_USDT-202509.csv.gz          (monthly trades)
    ├── TSLAX_USDT-202509.csv.gz
    └── ...
```

**输出格式：**
```
Data/crypto/kraken/tick/
├── aaplxusd/
│   ├── 20250902_depth.zip   # Depth snapshots (every 250ms, 10 levels)
│   ├── 20250902_trade.zip   # Trade ticks
│   └── ...
└── tslaxusd/
    ├── 20250902_depth.zip
    ├── 20250902_trade.zip
    └── ...
```

### 2. Nasdaq（股票）

**可用数据类型：**
- ✅ **Quote**（报价）：最佳买卖价（MBP-1）
- ✅ **Trade**（交易）：逐笔成交

**输入数据结构：**
```
raw_data/
├── us_trade_tick/
│   ├── xnas-itch-20250827.trades.csv.zst
│   └── ...
└── us_mbp_tick/
    ├── xnas-itch-20250827.mbp-1.AAPL.csv.zst
    ├── xnas-itch-20250827.mbp-1.TSLA.csv.zst
    └── ...
```

**输出格式：**
```
Data/equity/usa/tick/
├── aapl/
│   ├── 20250827_quote.zip
│   ├── 20250827_trade.zip
│   └── ...
└── tsla/
    ├── 20250827_quote.zip
    ├── 20250827_trade.zip
    └── ...
```

## 数据格式说明

### Gate.io Depth 数据

**输入格式**（增量更新）：
```csv
timestamp,side,action,price,amount,begin_id,merged
1756684800.123,2,set,231.98,10.5,1234567,0
```

- `side`: 1=ask(卖), 2=bid(买)
- `action`: set(设置), make(添加), take(减少)

**输出格式**（LEAN Depth）：
```csv
milliseconds,bid1_price,bid1_size,bid2_price,bid2_size,...,ask1_price,ask1_size,...
123456,23198000000,1050000000,23197000000,2000000000,...,23199000000,800000000,...
```

### Gate.io Trade 数据

**输入格式**：
```csv
timestamp,id,price,amount,side
1756684825.928483,448459,231.98,0.11,2
```

- `side`: 1=sell, 2=buy

**输出格式**（LEAN Trade）：
```csv
milliseconds,price,volume,exchange,condition,suspicious
123456,23198000000,11000000,X,,
```

### Nasdaq Trade 数据

**输入格式**（ITCH）：
```csv
ts_event,symbol,price,size,...
1724716800123456789,AAPL,225.50,100,...
```

**输出格式**（LEAN Trade）：
```csv
milliseconds,price,volume,exchange,condition,suspicious
123456,2255000,100,T,0,0
```

### Nasdaq Quote 数据

**输入格式**（MBP-1）：
```csv
ts_event,bid_px_00,bid_sz_00,ask_px_00,ask_sz_00,...
1724716800123456789,225.45,500,225.50,300,...
```

**输出格式**（LEAN Quote）：
```csv
milliseconds,bid_price,bid_size,ask_price,ask_size,exchange,condition,suspicious
123456,2254500,500,2255000,300,T,0,0
```

## 技术细节

### 价格精度

- **Crypto (Gate.io)**: 8 decimal places → multiply by 100,000,000 (satoshis)
- **Equity (Nasdaq)**: 2 decimal places → multiply by 10,000 (deci-cents)

### 时间处理

所有时间戳统一转换为：
- UTC 时区
- 从当日午夜起算的毫秒数

### 数据清洗

**Quote 数据：**
- 移除无效报价（bid/ask <= 0）
- 移除交叉报价（bid >= ask）
- 去重（连续相同报价只保留第一个）

**Trade 数据：**
- 保留所有有效交易
- 无额外过滤

### 快照频率

- **Gate.io Depth**: 每 250ms 一个快照（可在脚本中配置）
- **Gate.io Trade**: 每笔交易一个 tick
- **Nasdaq**: 原始频率（microsecond 精度）

## 添加新数据源

要添加新的数据源转换器：

1. 在 `converters/` 目录创建新转换器文件，例如 `binance_convertor.py`
2. 实现 `main_convert()` 函数，参数为 `(input_dir, output_dir, symbol)`
3. 在 `converters/__init__.py` 中添加到 `__all__` 列表
4. 在 `data_converter_cli.py` 中添加新的 Converter 类

## 常见问题

### Q: 为什么要重构目录结构？

**A:** 随着转换器数量增加，统一的目录结构可以：
- 更好地组织代码
- 便于维护和扩展
- 清晰地分离CLI和转换器逻辑

### Q: 旧版脚本还能用吗？

**A:** 可以。根目录下的旧版脚本仍然可用，但建议使用新的 `scripts/` 目录下的版本。

### Q: 如何从项目根目录运行？

**A:** 直接运行：
```bash
python scripts/data_converter_cli.py
```

Python 会自动处理路径。

### Q: 转换失败怎么办？

**A:**
1. 检查输入目录是否正确
2. 检查文件格式是否匹配
3. 查看详细错误信息
4. 确保有足够的磁盘空间

## 许可

本项目是 QuantConnect LEAN 的一部分。
