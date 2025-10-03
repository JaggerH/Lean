/*
 * Python Test Runner for LEAN
 * Provides LEAN environment (AlgorithmImports, etc.) to Python unit tests
 *
 * Usage:
 *   dotnet PythonTestRunner.dll path/to/test_file.py
 *   PythonTestRunner.exe arbitrage/tests/test_spread_manager.py
 */

using System;
using System.IO;
using Python.Runtime;
using QuantConnect.Configuration;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Python;
using QuantConnect.Util;

namespace QuantConnect.PythonTestRunner
{
    class Program
    {
        /// <summary>
        /// Initialize LEAN providers (DataProvider, MapFileProvider, FactorFileProvider)
        /// This is required for Symbol.Create() and other LEAN APIs to work correctly
        /// </summary>
        private static void InitializeLeanProviders()
        {
            Console.WriteLine("🔧 Initializing LEAN providers...");

            var dataProvider = Composer.Instance.GetExportedValueByTypeName<IDataProvider>(
                Config.Get("data-provider", "DefaultDataProvider"));
            var mapFileProvider = Composer.Instance.GetExportedValueByTypeName<IMapFileProvider>(
                Config.Get("map-file-provider", "LocalDiskMapFileProvider"));
            var factorFileProvider = Composer.Instance.GetExportedValueByTypeName<IFactorFileProvider>(
                Config.Get("factor-file-provider", "LocalDiskFactorFileProvider"));

            mapFileProvider.Initialize(dataProvider);
            factorFileProvider.Initialize(mapFileProvider, dataProvider);

            Console.WriteLine("✅ Initialized LEAN providers (DataProvider, MapFileProvider, FactorFileProvider)");
        }

        static int Main(string[] args)
        {
            if (args.Length == 0)
            {
                Console.WriteLine("Usage: PythonTestRunner <test_file.py>");
                Console.WriteLine("");
                Console.WriteLine("Examples:");
                Console.WriteLine("  dotnet PythonTestRunner.dll arbitrage/tests/test_limit_order_optimizer.py");
                Console.WriteLine("  PythonTestRunner.exe arbitrage/tests/test_spread_manager.py");
                return 1;
            }

            var testFilePath = args[0];

            // Convert to absolute path BEFORE changing working directory
            testFilePath = Path.GetFullPath(testFilePath);

            if (!File.Exists(testFilePath))
            {
                Console.WriteLine($"❌ Test file not found: {testFilePath}");
                return 1;
            }

            Console.WriteLine($"Python Test Runner for LEAN");
            Console.WriteLine($"Running: {testFilePath}");
            Console.WriteLine("");

            try
            {
                // Initialize LEAN configuration FIRST
                Config.Reset();
                Log.LogHandler = new ConsoleLogHandler();

                // Change to Launcher/bin/Debug directory (where AlgorithmImports.py is located)
                // BEFORE initializing Python.NET so DLLs can be loaded correctly
                var assemblyDir = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
                // From PythonTestRunner/bin/Debug -> Launcher/bin/Debug
                var launcherBinDebug = Path.GetFullPath(Path.Combine(assemblyDir, "../../../Launcher/bin/Debug"));

                if (Directory.Exists(launcherBinDebug))
                {
                    Directory.SetCurrentDirectory(launcherBinDebug);
                    Console.WriteLine($"✅ Changed working directory to: {launcherBinDebug}");
                }
                else
                {
                    Console.WriteLine($"⚠️  Warning: Launcher/bin/Debug not found at {launcherBinDebug}");
                    Console.WriteLine($"   (Assembly dir: {assemblyDir})");
                    Console.WriteLine("   AlgorithmImports may not be available");
                }

                // Set data folder AFTER changing directory (relative to current dir)
                var dataFolder = Path.GetFullPath("../../../Data/");
                Config.Set("data-folder", dataFolder);
                Console.WriteLine($"✅ Set data-folder to: {dataFolder}");

                // Initialize LEAN providers BEFORE Python.NET
                InitializeLeanProviders();

                // Initialize Python.NET AFTER changing directory and initializing providers
                if (!PythonEngine.IsInitialized)
                {
                    Console.WriteLine("✅ Initializing Python.NET...");
                    PythonEngine.Initialize();
                    PythonEngine.BeginAllowThreads();
                }

                using (Py.GIL())
                {
                    // Add test file directory to Python path
                    var testFileDir = Path.GetDirectoryName(Path.GetFullPath(testFilePath));
                    var testFileName = Path.GetFileNameWithoutExtension(testFilePath);

                    dynamic sys = Py.Import("sys");

                    // Add current working directory (where AlgorithmImports.py is) to sys.path
                    var currentDir = Directory.GetCurrentDirectory();
                    sys.path.insert(0, currentDir);
                    Console.WriteLine($"✅ Added to sys.path: {currentDir}");

                    // Add test directory to path
                    if (!string.IsNullOrEmpty(testFileDir))
                    {
                        sys.path.insert(0, testFileDir);
                        Console.WriteLine($"✅ Added to sys.path: {testFileDir}");
                    }

                    // Add arbitrage directory to path (if test is in arbitrage/tests)
                    if (testFileDir.Contains("arbitrage"))
                    {
                        var arbitrageDir = testFileDir;
                        while (!arbitrageDir.EndsWith("arbitrage") && Directory.GetParent(arbitrageDir) != null)
                        {
                            arbitrageDir = Directory.GetParent(arbitrageDir).FullName;
                        }
                        if (arbitrageDir.EndsWith("arbitrage"))
                        {
                            sys.path.insert(0, arbitrageDir);
                            Console.WriteLine($"✅ Added to sys.path: {arbitrageDir}");
                        }
                    }

                    // Run the test using Python's unittest discovery
                    var testCode = $@"
import sys
import unittest
import os

# Change to test file directory for relative imports
os.chdir(r'{testFileDir}')

# Import the test module
test_module = __import__('{testFileName}')

# Discover and run tests
loader = unittest.TestLoader()
suite = loader.loadTestsFromModule(test_module)

# Run with verbose output
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

# Return test results
test_results = {{
    'tests_run': result.testsRun,
    'failures': len(result.failures),
    'errors': len(result.errors),
    'skipped': len(result.skipped),
    'success': result.wasSuccessful()
}}
";

                    Console.WriteLine("");
                    Console.WriteLine("Running tests...");
                    Console.WriteLine("─────────────────────────────────────");

                    var locals = new PyDict();
                    PythonEngine.Exec(testCode, locals: locals);

                    // Get test results
                    dynamic testResults = locals["test_results"];
                    var testsRun = (int)testResults["tests_run"];
                    var failures = (int)testResults["failures"];
                    var errors = (int)testResults["errors"];
                    var skipped = (int)testResults["skipped"];
                    var success = (bool)testResults["success"];

                    Console.WriteLine("─────────────────────────────────────");
                    Console.WriteLine("");
                    Console.WriteLine($"Tests run: {testsRun}");
                    Console.WriteLine($"Failures: {failures}");
                    Console.WriteLine($"Errors: {errors}");
                    Console.WriteLine($"Skipped: {skipped}");
                    Console.WriteLine("");

                    if (success)
                    {
                        Console.WriteLine("✅ All tests passed!");
                        return 0;
                    }
                    else
                    {
                        Console.WriteLine("❌ Some tests failed!");
                        return 1;
                    }
                }
            }
            catch (PythonException ex)
            {
                Console.WriteLine("");
                Console.WriteLine("❌ Python error:");
                Console.WriteLine(ex.Message);
                Console.WriteLine("");
                Console.WriteLine("Stack trace:");
                Console.WriteLine(ex.StackTrace);
                return 1;
            }
            catch (Exception ex)
            {
                Console.WriteLine("");
                Console.WriteLine("❌ Error:");
                Console.WriteLine(ex.Message);
                Console.WriteLine("");
                Console.WriteLine("Stack trace:");
                Console.WriteLine(ex.StackTrace);
                return 1;
            }
            finally
            {
                // Note: We don't call PythonEngine.Shutdown() because it can't be restarted
            }
        }
    }
}
