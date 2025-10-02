"""
Conditional import wrapper for AlgorithmImports

Handles three runtime environments:
1. Development/testing from arbitrage/ - uses stub classes
2. Testing from arbitrage/tests/ - uses stub classes
3. Production via Launcher (run.bat) - uses real AlgorithmImports

The real AlgorithmImports requires Python.NET and LEAN DLLs which are only
available in the Launcher/bin/Debug environment.
"""

# Try to import real AlgorithmImports (environment 3)
try:
    from AlgorithmImports import *
    LEAN_AVAILABLE = True

except (ImportError, ModuleNotFoundError):
    # Fallback to stub classes for testing/development (environments 1 & 2)
    LEAN_AVAILABLE = False

    class Symbol:
        """Stub Symbol class for testing"""
        def __init__(self):
            self.Value = ""
            self.SecurityType = None
            self.Market = None

        @staticmethod
        def Create(symbol_str, security_type, market):
            """Create a mock Symbol object"""
            obj = Symbol()
            obj.Value = symbol_str
            obj.SecurityType = security_type
            obj.Market = market
            return obj

        def __str__(self):
            return self.Value

        def __repr__(self):
            return f"Symbol({self.Value})"

    class Security:
        """Stub Security class for testing"""
        def __init__(self):
            self.Symbol = None

    class Market:
        """Stub Market class for testing"""
        USA = "usa"
        Kraken = "kraken"
        KRAKEN = "kraken"

    class SecurityType:
        """Stub SecurityType class for testing"""
        Equity = 1
        Crypto = 2

    class QCAlgorithm:
        """Stub QCAlgorithm class for testing"""
        pass
