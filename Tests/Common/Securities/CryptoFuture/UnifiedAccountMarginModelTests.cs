/*
 * QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
 * Lean Algorithmic Trading Engine v2.0. Copyright 2014 QuantConnect Corporation.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
*/

using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Brokerages;
using QuantConnect.Data.Market;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.Securities.Crypto;
using QuantConnect.Securities.CryptoFuture;
using QuantConnect.Tests.Engine.DataFeeds;

namespace QuantConnect.Tests.Common.Securities.CryptoFuture
{
    [TestFixture]
    public class UnifiedAccountMarginModelTests
    {
        /// <summary>
        /// Test that spot crypto assets contribute to futures margin with correct discount rates
        /// </summary>
        [Test]
        public void SpotAssetsContributeToFuturesMargin()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);

            // Add USDT cash (base collateral)
            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);

            // Add spot BTC (should contribute with 95% discount)
            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);
            btcSpot.Holdings.SetHoldings(50000m, 1m); // 1 BTC at $50,000

            // Add futures
            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);
            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            // Calculate expected collateral
            // = 10,000 USDT + (1 BTC * 50,000 * 0.95 discount)
            // = 10,000 + 47,500 = 57,500 USDT
            var expectedCollateral = 10000m + (1m * 50000m * 0.95m);

            // Available margin for futures = collateral (no existing positions)
            var marginRemaining = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Buy));

            // With 5x leverage, buying power = collateral * leverage
            var expectedBuyingPower = expectedCollateral * 5m;

            Assert.AreEqual((double)expectedBuyingPower, (double)marginRemaining.Value, 0.01,
                "Spot BTC should contribute to futures margin with 95% discount");
        }

        /// <summary>
        /// Test that currency discount rates are applied correctly
        /// </summary>
        [TestCase("BTC", 0.95)]
        [TestCase("ETH", 0.95)]
        public void CurrencyDiscountsAppliedCorrectly(string baseCurrency, decimal expectedDiscount)
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);

            // Add spot crypto
            var spot = algo.AddCrypto($"{baseCurrency}USDT");
            SetPrice(spot, 1000m);
            spot.Holdings.SetHoldings(1000m, 10m); // 10 units at $1,000 each = $10,000

            // Add futures
            var future = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(future, 50000m);
            future.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            // Calculate expected collateral
            var spotValue = 10m * 1000m; // $10,000
            var expectedCollateral = 10000m + (spotValue * expectedDiscount);

            var marginRemaining = future.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, future, OrderDirection.Buy));

            var expectedBuyingPower = expectedCollateral * 5m;

            Assert.AreEqual((double)expectedBuyingPower, (double)marginRemaining.Value, 0.01,
                $"{baseCurrency} should have {expectedDiscount * 100}% discount rate");
        }

        /// <summary>
        /// Test that tiered maintenance margin rates are calculated correctly
        /// </summary>
        [TestCase(40000, 0.005)]   // Tier 1: < $50k → 0.5%
        [TestCase(100000, 0.02)]   // Tier 2: < $500k → 2%
        [TestCase(600000, 0.05)]   // Tier 3: >= $500k → 5%
        public void TieredMaintenanceMarginCalculation(decimal positionValueUSD, decimal expectedRate)
        {
            var algo = GetAlgorithm();
            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            var model = new UnifiedAccountMarginModel(leverage: 5);
            btcFuture.BuyingPowerModel = model;

            // Calculate quantity needed for target position value
            var quantity = positionValueUSD / (50000m * btcFuture.SymbolProperties.ContractMultiplier);
            btcFuture.Holdings.SetHoldings(50000m, quantity);

            var maintenanceMargin = model.GetMaintenanceMargin(
                MaintenanceMarginParameters.ForCurrentHoldings(btcFuture));

            var expectedMargin = positionValueUSD * expectedRate;

            Assert.AreEqual((double)expectedMargin, (double)maintenanceMargin.Value, 0.01,
                $"Position value ${positionValueUSD} should use {expectedRate * 100}% maintenance rate");
        }

        /// <summary>
        /// Test that multiple futures share margin correctly
        /// </summary>
        [Test]
        public void MultipleFuturesShareMarginCorrectly()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 50000m, 1.0m);

            // Add BTC futures with position
            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);
            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);
            btcFuture.Holdings.SetHoldings(50000m, 2m); // 2 BTC = $100,000 position

            // Add ETH futures
            var ethFuture = algo.AddCryptoFuture("ETHUSDT");
            SetPrice(ethFuture, 2000m);
            ethFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            // BTC initial margin = 100,000 / 5 = 20,000
            var btcInitialMargin = 100000m / 5m; // $20,000

            // Available margin for ETH = Total collateral - BTC initial margin
            var availableForETH = 50000m - btcInitialMargin; // $30,000

            var marginRemaining = ethFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, ethFuture, OrderDirection.Buy));

            var expectedBuyingPower = availableForETH * 5m; // $150,000

            Assert.AreEqual((double)expectedBuyingPower, (double)marginRemaining.Value, 1.0,
                "Multiple futures should share collateral correctly");
        }

        /// <summary>
        /// Test backward compatibility: Without spot holdings, should behave like CryptoFutureMarginModel
        /// </summary>
        [Test]
        public void BackwardCompatibility_NoSpotHoldings()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            // Use unified model
            var unifiedModel = new UnifiedAccountMarginModel(leverage: 5, defaultMaintenanceRate: 0.05m);
            btcFuture.BuyingPowerModel = unifiedModel;

            var unifiedMargin = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Buy));

            // Expected: $10,000 * 5 = $50,000 buying power (no spot assets)
            var expectedBuyingPower = 10000m * 5m;

            Assert.AreEqual((double)expectedBuyingPower, (double)unifiedMargin.Value, 0.01,
                "Without spot holdings, should behave like standard margin model");
        }

        /// <summary>
        /// Test that spot with different quote currency doesn't participate
        /// </summary>
        [Test]
        public void DifferentQuoteCurrencySpotDoesNotParticipate()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);
            algo.Portfolio.SetCash("BTC", 0m, 50000m); // BTC cash, not spot

            // Add BTCUSD spot (quote currency is USD, not USDT)
            var btcUsdSpot = algo.AddCrypto("BTCUSD");
            SetPrice(btcUsdSpot, 50000m);
            btcUsdSpot.Holdings.SetHoldings(50000m, 1m); // 1 BTC

            // Add BTCUSDT futures (quote currency is USDT)
            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);
            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            var marginRemaining = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Buy));

            // In unified account, all crypto holdings contribute regardless of quote currency
            // Total margin balance = USDT (10,000) + BTC spot (50,000 * 0.95 discount) = 57,500
            // Buying power = 57,500 * 5 = 287,500
            var expectedBuyingPower = (10000m + (50000m * 0.95m)) * 5m;

            Assert.AreEqual((double)expectedBuyingPower, (double)marginRemaining.Value, 0.01,
                "In unified account, all crypto holdings contribute to margin");
        }

        /// <summary>
        /// Test that closing a position increases available margin correctly
        /// </summary>
        [Test]
        public void ClosingPositionReleasesMarginCorrectly()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 50000m, 1.0m);

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);
            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            // Open long position: 2 BTC
            btcFuture.Holdings.SetHoldings(50000m, 2m); // $100,000 position

            // Calculate margin available for CLOSING (selling)
            var marginForClosing = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Sell));

            // When closing, we release margin:
            // Current available = Total margin - Initial margin = $50,000 - $20,000 = $30,000
            // Released: Maintenance margin ($100k * 2% = $2,000) + Initial margin ($20,000)
            // Available after = $30,000 + $2,000 + $20,000 = $52,000
            // Buying power = $52,000 * 5 = $260,000

            var currentAvailable = 50000m - 20000m; // $30,000
            var expectedReleasedMargin = 2000m + 20000m; // Maintenance + Initial
            var expectedBuyingPower = (currentAvailable + expectedReleasedMargin) * 5m;

            Assert.Greater((double)marginForClosing.Value, (double)(50000m * 5m),
                "Closing position should have more buying power than opening");
            Assert.AreEqual((double)expectedBuyingPower, (double)marginForClosing.Value, 1.0,
                "Should release both maintenance and initial margin when closing");
        }

        /// <summary>
        /// Test custom currency discounts
        /// </summary>
        [Test]
        public void CustomCurrencyDiscounts()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);

            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);
            btcSpot.Holdings.SetHoldings(50000m, 1m); // $50,000

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            // Custom discounts: BTC at 90% instead of default 95%
            var customDiscounts = new Dictionary<string, decimal>
            {
                { "USDT", 1.0m },  // Must include USDT to avoid default 85% haircut
                { "BTC", 0.90m }
            };

            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(
                leverage: 5,
                currencyDiscounts: customDiscounts
            );

            var marginRemaining = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Buy));

            // Expected: 10,000 (USDT at 100%) + (50,000 * 0.90) = 55,000 USDT
            var expectedCollateral = 10000m + (50000m * 0.90m);
            var expectedBuyingPower = expectedCollateral * 5m;

            Assert.AreEqual((double)expectedBuyingPower, (double)marginRemaining.Value, 0.01,
                "Should use custom currency discount rate");
        }

        /// <summary>
        /// Test custom tiered maintenance rates
        /// </summary>
        [Test]
        public void CustomTieredMaintenanceRates()
        {
            var algo = GetAlgorithm();
            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            // Custom tiers: 2-tier system instead of 3-tier
            var customTiers = new Dictionary<decimal, decimal>
            {
                { 100000m, 0.01m },        // < $100k → 1%
                { decimal.MaxValue, 0.03m } // >= $100k → 3%
            };

            var model = new UnifiedAccountMarginModel(
                leverage: 5,
                tierMaintenanceRates: customTiers
            );
            btcFuture.BuyingPowerModel = model;

            // Test tier 1: $50k position
            btcFuture.Holdings.SetHoldings(50000m, 1m); // $50,000
            var margin1 = model.GetMaintenanceMargin(
                MaintenanceMarginParameters.ForCurrentHoldings(btcFuture));
            Assert.AreEqual((double)(50000m * 0.01m), (double)margin1.Value, 0.01, "Should use 1% for <$100k");

            // Test tier 2: $200k position
            btcFuture.Holdings.SetHoldings(50000m, 4m); // $200,000
            var margin2 = model.GetMaintenanceMargin(
                MaintenanceMarginParameters.ForCurrentHoldings(btcFuture));
            Assert.AreEqual((double)(200000m * 0.03m), (double)margin2.Value, 0.01, "Should use 3% for >=$100k");
        }

        /// <summary>
        /// Test complex scenario: Multiple spot assets + multiple futures
        /// </summary>
        [Test]
        public void ComplexScenario_MultipleAssetsAndFutures()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 20000m, 1.0m);

            // Add multiple spot holdings
            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);
            btcSpot.Holdings.SetHoldings(50000m, 0.5m); // 0.5 BTC = $25,000

            var ethSpot = algo.AddCrypto("ETHUSDT");
            SetPrice(ethSpot, 2000m);
            ethSpot.Holdings.SetHoldings(2000m, 5m); // 5 ETH = $10,000

            // Add BTC futures with existing position
            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);
            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);
            btcFuture.Holdings.SetHoldings(50000m, 1m); // $50,000 position

            // Add ETH futures
            var ethFuture = algo.AddCryptoFuture("ETHUSDT");
            SetPrice(ethFuture, 2000m);
            ethFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            // Calculate expected collateral
            // = 20,000 USDT
            // + (0.5 BTC * 50,000 * 0.95) = 23,750
            // + (5 ETH * 2,000 * 0.95) = 9,500
            // Total = 53,250 USDT
            var expectedCollateral = 20000m + (0.5m * 50000m * 0.95m) + (5m * 2000m * 0.95m);

            // BTC position initial margin = $50,000 / 5 = $10,000
            var btcInitialMargin = 50000m / 5m; // $10,000

            // Available for ETH = Total margin balance - BTC initial margin
            var availableForETH = expectedCollateral - btcInitialMargin;

            var ethMargin = ethFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, ethFuture, OrderDirection.Buy));

            var expectedBuyingPower = availableForETH * 5m;

            Assert.AreEqual((double)expectedBuyingPower, (double)ethMargin.Value, 1.0,
                "Complex scenario with multiple assets should calculate correctly");
        }

        /// <summary>
        /// Test USDT borrowing (negative cash balance) reduces available margin
        /// </summary>
        [Test]
        public void NegativeUSDTBalanceRepresentsBorrowing()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);

            // Start with 10,000 USDT, then "borrow" 5,000 (set to -5000)
            algo.Portfolio.SetCash("USDT", -5000m, 1.0m);

            // Add BTC spot as collateral
            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);
            btcSpot.Holdings.SetHoldings(50000m, 1m); // 1 BTC = $50,000

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);
            btcFuture.BuyingPowerModel = new UnifiedAccountMarginModel(leverage: 5);

            // Total margin balance = BTC value * discount - USDT borrowing
            // = (50,000 * 0.95) - 5,000 = 47,500 - 5,000 = 42,500
            // Borrowing initial margin = 5,000 * 0.25 = 1,250 (using default 25% rate)
            // Available margin = 42,500 - 1,250 = 41,250
            // Buying power = 41,250 * 5 = 206,250

            var marginRemaining = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Buy));

            var btcCollateral = 50000m * 0.95m; // 47,500
            var totalMarginBalance = btcCollateral + (-5000m); // 42,500 (negative USDT reduces balance)
            var borrowingInitialMargin = 5000m * 0.25m; // 1,250
            var availableMargin = totalMarginBalance - borrowingInitialMargin; // 41,250
            var expectedBuyingPower = availableMargin * 5m; // 206,250

            Assert.AreEqual((double)expectedBuyingPower, (double)marginRemaining.Value, 100.0,
                "Negative USDT should reduce available margin as borrowing");
        }

        /// <summary>
        /// Test borrowing initial margin calculation
        /// </summary>
        [Test]
        public void BorrowingInitialMarginCalculation()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);

            // Borrow 10,000 USDT (negative balance)
            algo.Portfolio.SetCash("USDT", -10000m, 1.0m);

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            var model = new UnifiedAccountMarginModel(
                leverage: 5,
                borrowingMarginRates: new Dictionary<string, decimal> { { "USDT", 0.30m } } // 30% custom rate
            );
            btcFuture.BuyingPowerModel = model;

            // Borrowing initial margin = 10,000 * 0.30 = 3,000
            var expectedBorrowingMargin = 10000m * 0.30m;

            // Since we have no collateral and 10k borrowed, total margin balance = -10,000
            // Available margin = -10,000 - 3,000 = -13,000
            // Buying power should be 0 (can't trade with negative available margin)

            var marginRemaining = btcFuture.BuyingPowerModel.GetBuyingPower(
                new BuyingPowerParameters(algo.Portfolio, btcFuture, OrderDirection.Buy));

            Assert.AreEqual(0, (double)marginRemaining.Value, 0.01,
                "Should have zero buying power with only borrowing and no collateral");
        }

        /// <summary>
        /// Test GetAccountRiskRatio method
        /// </summary>
        [Test]
        public void GetAccountRiskRatioCalculation()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 50000m, 1.0m);

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            var model = new UnifiedAccountMarginModel(leverage: 5, defaultMaintenanceRate: 0.02m);
            btcFuture.BuyingPowerModel = model;

            // Open a position: 2 BTC = $100,000
            btcFuture.Holdings.SetHoldings(50000m, 2m);

            // Total margin balance = 50,000 USDT
            // Total maintenance margin = 100,000 * 0.02 = 2,000
            // Risk ratio = (50,000 / 2,000) * 100 = 2,500%

            var riskRatio = model.GetAccountRiskRatio(algo.Portfolio);
            var expectedRatio = (50000m / 2000m) * 100m;

            Assert.AreEqual((double)expectedRatio, (double)riskRatio, 0.01,
                "Account risk ratio should be calculated correctly");
        }

        /// <summary>
        /// Test GetAvailableMargin method
        /// </summary>
        [Test]
        public void GetAvailableMarginCalculation()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.Portfolio.SetCash("USDT", 50000m, 1.0m);

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            var model = new UnifiedAccountMarginModel(leverage: 5);
            btcFuture.BuyingPowerModel = model;

            // Open a position: 1 BTC = $50,000
            btcFuture.Holdings.SetHoldings(50000m, 1m);

            // Total margin balance = 50,000 USDT
            // Futures initial margin = 50,000 / 5 = 10,000
            // Available margin = 50,000 - 10,000 = 40,000

            var availableMargin = model.GetAvailableMargin(algo.Portfolio);
            var expectedAvailable = 50000m - 10000m;

            Assert.AreEqual((double)expectedAvailable, (double)availableMargin, 0.01,
                "Available margin should be total balance minus initial margin");
        }

        /// <summary>
        /// Test risk ratio with borrowing
        /// </summary>
        [Test]
        public void RiskRatioWithBorrowing()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);

            // Start with borrowed 5,000 USDT
            algo.Portfolio.SetCash("USDT", -5000m, 1.0m);

            // Add BTC spot as collateral: 1 BTC = $50,000
            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);
            btcSpot.Holdings.SetHoldings(50000m, 1m);

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            var model = new UnifiedAccountMarginModel(
                leverage: 5,
                defaultMaintenanceRate: 0.02m,
                borrowingMarginRates: new Dictionary<string, decimal> { { "USDT", 0.25m } }
            );
            btcFuture.BuyingPowerModel = model;

            // Open futures position: 1 BTC = $50,000
            btcFuture.Holdings.SetHoldings(50000m, 1m);

            // Total margin balance:
            // = (BTC * price * discount) + (USDT balance)
            // = (1 * 50,000 * 0.95) + (-5,000)
            // = 47,500 - 5,000 = 42,500

            // Total maintenance margin:
            // = Futures maintenance + Borrowing maintenance (tiered)
            // = (50,000 * 0.02) + (5,000 * 1% tiered rate)
            // = 1,000 + 50 = 1,050

            // Risk ratio = (42,500 / 1,050) * 100 = 4,047.62%

            var riskRatio = model.GetAccountRiskRatio(algo.Portfolio);
            var expectedRatio = (42500m / 1050m) * 100m;

            Assert.AreEqual((double)expectedRatio, (double)riskRatio, 1.0,
                "Risk ratio should account for borrowing reducing margin balance");
        }

        /// <summary>
        /// Test that borrowing margin rates are validated
        /// </summary>
        [Test]
        public void BorrowingMarginRateValidation()
        {
            Assert.Throws<ArgumentException>(() =>
            {
                new UnifiedAccountMarginModel(
                    borrowingMarginRates: new Dictionary<string, decimal> { { "USDT", 1.5m } } // Invalid: > 1
                );
            }, "Should reject borrowing margin rate > 1");

            Assert.Throws<ArgumentException>(() =>
            {
                new UnifiedAccountMarginModel(
                    borrowingMarginRates: new Dictionary<string, decimal> { { "USDT", -0.1m } } // Invalid: < 0
                );
            }, "Should reject negative borrowing margin rate");
        }

        /// <summary>
        /// Test scenario: Large collateral, small borrowing should have high risk ratio
        /// </summary>
        [Test]
        public void LargeCollateralSmallBorrowingHighRiskRatio()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);

            // 100,000 USDT collateral, 5,000 borrowed
            algo.Portfolio.SetCash("USDT", 95000m, 1.0m); // Net: 95k in account

            var btcFuture = algo.AddCryptoFuture("BTCUSDT");
            SetPrice(btcFuture, 50000m);

            var model = new UnifiedAccountMarginModel(leverage: 5, defaultMaintenanceRate: 0.02m);
            btcFuture.BuyingPowerModel = model;

            // Small position: 0.5 BTC = $25,000
            btcFuture.Holdings.SetHoldings(50000m, 0.5m);

            // Total margin balance = 95,000
            // Maintenance margin = 25,000 * 0.02 = 500
            // Risk ratio = (95,000 / 500) * 100 = 19,000%

            var riskRatio = model.GetAccountRiskRatio(algo.Portfolio);

            Assert.Greater((double)riskRatio, 10000.0, "Should have very high risk ratio with large collateral");
        }

        /// <summary>
        /// Test that Crypto naked short is prohibited through GateUnifiedBrokerageModel
        /// </summary>
        [Test]
        public void CryptoNakedShortIsProhibited()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.SetBrokerageModel(new GateUnifiedBrokerageModel());

            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);

            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);

            // Try to place a sell order without holding any BTC (naked short)
            var order = new MarketOrder(btcSpot.Symbol, -0.1m, DateTime.UtcNow);

            var canSubmit = algo.BrokerageModel.CanSubmitOrder(btcSpot, order, out var message);

            Assert.IsFalse(canSubmit, "Naked short should be prohibited");
            Assert.IsNotNull(message, "Should have error message");
            Assert.AreEqual("NakedShortNotAllowed", message.Code, "Should have correct error code");
        }

        /// <summary>
        /// Test that Crypto can sell to close existing long position
        /// </summary>
        [Test]
        public void CryptoCanSellToCloseLongPosition()
        {
            var algo = GetAlgorithm();
            ClearAllCash(algo);
            algo.SetBrokerageModel(new GateUnifiedBrokerageModel());

            algo.Portfolio.SetCash("USDT", 10000m, 1.0m);

            var btcSpot = algo.AddCrypto("BTCUSDT");
            SetPrice(btcSpot, 50000m);

            // Hold 1 BTC
            btcSpot.Holdings.SetHoldings(50000m, 1m);

            // Try to sell 0.5 BTC (closing half of long position)
            var order = new MarketOrder(btcSpot.Symbol, -0.5m, DateTime.UtcNow);

            var canSubmit = algo.BrokerageModel.CanSubmitOrder(btcSpot, order, out var message);

            Assert.IsTrue(canSubmit, "Selling to close long position should be allowed");
            Assert.IsNull(message, "Should not have error message");
        }

        private static QCAlgorithm GetAlgorithm()
        {
            var algo = new AlgorithmStub();
            algo.SetFinishedWarmingUp();
            return algo;
        }

        /// <summary>
        /// Clears all cash from the portfolio to start with a clean slate
        /// </summary>
        private static void ClearAllCash(QCAlgorithm algo)
        {
            var cashesToClear = algo.Portfolio.CashBook.Keys.ToList();
            foreach (var currency in cashesToClear)
            {
                algo.Portfolio.SetCash(currency, 0m, 1.0m);
            }
        }

        private static void SetPrice(Security security, decimal price)
        {
            // Set conversion rates for crypto
            if (security.Type == SecurityType.Crypto)
            {
                var crypto = (Crypto)security;
                crypto.BaseCurrency.ConversionRate = price;
                crypto.QuoteCurrency.ConversionRate = 1;
            }
            else if (security.Type == SecurityType.CryptoFuture)
            {
                var cryptoFuture = (QuantConnect.Securities.CryptoFuture.CryptoFuture)security;
                cryptoFuture.BaseCurrency.ConversionRate = price;
                cryptoFuture.QuoteCurrency.ConversionRate = 1;
            }

            security.SetMarketPrice(new TradeBar
            {
                Time = new DateTime(2024, 1, 15),
                Symbol = security.Symbol,
                Open = price,
                High = price,
                Low = price,
                Close = price
            });
        }
    }
}
