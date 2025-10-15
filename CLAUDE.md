# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## About LEAN

LEAN is an open-source algorithmic trading engine developed by QuantConnect. It's a professional-caliber, event-driven platform that supports backtesting and live trading across multiple asset classes (equities, forex, crypto, futures, options, etc.).

## Build Commands

**Build the solution:**
```bash
dotnet build QuantConnect.Lean.sln
```

**Build for Release:**
```bash
dotnet build /p:Configuration=Release QuantConnect.Lean.sln
```

**Run the Launcher (executes algorithms):**
```bash
cd Launcher/bin/Debug
dotnet QuantConnect.Lean.Launcher.dll
```

Or in Visual Studio: Open `QuantConnect.Lean.sln` and press F5.

## Testing

**Run all tests:**
```bash
dotnet test Tests/QuantConnect.Tests.csproj
```

**Run tests excluding Travis CI-specific tests:**
```bash
dotnet test ./Tests/bin/Release/QuantConnect.Tests.dll --filter "TestCategory!=TravisExclude&TestCategory!=ResearchRegressionTests"
```

**Run a specific test:**
```bash
dotnet test --filter "FullyQualifiedName=QuantConnect.Tests.Namespace.ClassName.MethodName"
```

**Run tests matching a pattern:**
```bash
dotnet test --filter "FullyQualifiedName~Namespace.Class"
```

## Python Testing

LEAN includes a dedicated **PythonTestRunner** tool for running Python unit tests with full LEAN environment support (AlgorithmImports, Symbol.Create(), etc.).

**Run Python unit tests:**
```bash
# Method 1: Using .NET CLI
dotnet PythonTestRunner/bin/Debug/PythonTestRunner.dll arbitrage/tests/test_spread_manager.py

# Method 2: Using batch script (Windows)
PythonTestRunner/pytest.bat arbitrage/tests/test_spread_manager.py

# Method 3: Run other test files
PythonTestRunner/pytest.bat arbitrage/tests/test_limit_order_optimizer.py
```

**Key Features:**
- Automatically initializes LEAN providers (DataProvider, MapFileProvider, FactorFileProvider)
- Sets up Python.NET environment with correct working directory
- Configures sys.path for arbitrage modules
- Runs tests using Python's unittest framework with verbose output
- Returns detailed test results (passed, failed, errors, skipped)

**Build PythonTestRunner (if needed):**
```bash
dotnet build PythonTestRunner/PythonTestRunner.csproj
```

## Configuration

The main configuration file is `Launcher/config.json`, which controls:
- **environment**: "backtesting" or "live-paper" or other live modes
- **algorithm-type-name**: The algorithm class to run
- **algorithm-language**: "CSharp" or "Python"
- **algorithm-location**: Path to the algorithm DLL or Python file
- **data-folder**: Path to market data (default: "../../../Data/")

Change the `algorithm-type-name` and `algorithm-location` to run different algorithms.

## High-Level Architecture

### Core Components

**Algorithm**: The base `QCAlgorithm` class (in `Algorithm/QCAlgorithm.cs`) is what users inherit from to build trading strategies. It provides:
- Data subscription management
- Order placement and portfolio management
- Event handlers (OnData, OnOrderEvent, etc.)
- Indicators, charting, and scheduling

**Algorithm.Framework**: Modular framework for building algorithms using separate components:
- **Alphas**: Generate trading signals
- **Portfolio**: Construct portfolios from signals
- **Execution**: Execute orders from portfolio targets
- **Risk**: Manage portfolio risk
- **Selection**: Define security universes

**Engine**: The core execution engine (`Engine/`) orchestrates everything:
- **AlgorithmManager**: Manages algorithm lifecycle
- **DataFeeds**: Streams market data to algorithms
- **RealTime**: Handles scheduled events
- **Results**: Processes algorithm results and statistics
- **TransactionHandlers**: Processes orders and fills
- **Setup**: Initializes algorithm environment

**Common**: Shared infrastructure (`Common/`):
- Core data types (Symbol, Security, Order, etc.)
- Interfaces (IAlgorithm, IBrokerage, IDataFeed, etc.)
- Securities modeling (Equity, Forex, Crypto, Options, Futures)
- Data structures and utilities

**Brokerages**: Brokerage integrations for live trading (`Brokerages/`).

**Data**: Sample/test market data in various formats (`Data/`).

**Indicators**: Technical indicators (`Indicators/`).

**Launcher**: Entry point that initializes and runs the engine (`Launcher/Program.cs`).

### Brokerage Integration Architecture

New brokerages are added by:

1. **Implement IBrokerage** (defined in `Common/Interfaces/IBrokerage.cs`):
   - Inherit from the base `Brokerage` class (`Brokerages/Brokerage.cs`)
   - Implement order operations: PlaceOrder, UpdateOrder, CancelOrder
   - Implement account operations: GetAccountHoldings, GetCashBalance
   - Implement connection: Connect, Disconnect, IsConnected
   - Handle real-time events: OrderIdChanged, OrdersStatusChanged, AccountChanged, Message

2. **Implement IBrokerageFactory** (defined in `Common/Interfaces/IBrokerageFactory.cs`):
   - Inherit from `BrokerageFactory` (`Brokerages/BrokerageFactory.cs`)
   - Implement CreateBrokerage to instantiate your brokerage
   - Implement GetBrokerageModel to provide brokerage-specific behavior (fees, margin, etc.)

3. **Add Brokerage Model** (in `Common/Brokerages/`):
   - Implement IBrokerageModel to define brokerage-specific rules
   - Define fee models, slippage models, margin requirements
   - Specify supported security types and order types

Brokerages typically live in `Brokerages/<BrokerageName>/` with their factories. Tests go in `Tests/Brokerages/<BrokerageName>/`.

### Data Flow

1. **DataFeed** pulls data from data providers based on subscriptions
2. Data is aggregated and synchronized by time
3. **Engine** feeds data to the algorithm via OnData events
4. Algorithm generates orders
5. **TransactionHandler** processes orders
6. **Brokerage** executes orders (in live mode) or **BacktestingBrokerage** simulates fills
7. Order events flow back to algorithm via OnOrderEvent
8. **Results** collect statistics and generate reports

## Code Style

- Follow Microsoft C# coding guidelines
- Use 4 spaces for indentation (soft tabs)
- All code must include unit tests
- Framework modules should be focused and do one thing well
- No logging/debugging inside framework modules (users handle this in their algorithms)
- No charting inside framework modules

## Branch Naming

- Bug fixes: `bug-<issue#>-<description>`
- Features: `feature-<issue#>-<description>`
- Always branch from and merge back to `master`

## Python Support

LEAN supports both C# and Python algorithms through Python.NET. Python algorithms follow the same structure as C# algorithms by inheriting from QCAlgorithm.

Configuration for Python:
- Set `"algorithm-language": "Python"` in config.json
- Set `"algorithm-location"` to path of .py file
- Optional: Set `"python-venv"` to use a virtual environment

**Python Environment:**
- A conda environment named `lean` is configured with Python 3.11 and Lean CLI
- Always use `conda run -n lean` prefix when running Python or Lean CLI commands
- Examples:
  ```bash
  conda run -n lean lean create-project --language python myproject
  conda run -n lean lean backtest myproject
  conda run -n lean python script.py
  ```

## Key Entry Points

- **Launcher/Program.cs**: Main entry point that initializes the engine
- **Algorithm/QCAlgorithm.cs**: Base class for all user algorithms
- **Engine/Engine.cs**: Core engine implementation
- **AlgorithmFactory/Loader.cs**: Loads algorithm instances from DLLs or Python files

## Important Notes

- The main branch is `master` (not main)
- Data folder structure is important - market data must follow the expected directory layout
- Algorithm class name must match the `algorithm-type-name` in config.json
- Tests should not be marked as TravisExclude unless truly necessary for CI environment