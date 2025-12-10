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
 *
*/

using System;
using QuantConnect.Data.Market;
using QuantConnect.Logging;

namespace QuantConnect.Securities.CryptoFuture
{
    /// <summary>
    /// The responsibility of this model is to apply Gate.io future funding rate cash flows to the portfolio based on open positions
    /// </summary>
    /// <remarks>
    /// Gate.io funding rate settlement times (UTC):
    /// - 00:00
    /// - 08:00
    /// - 16:00
    ///
    /// Funding rate logic:
    /// - Positive rate: Longs pay shorts (perpetual price > spot price)
    /// - Negative rate: Shorts pay longs (perpetual price < spot price)
    ///
    /// Only positions held at the exact settlement time receive/pay the funding rate.
    /// </remarks>
    public class GateFutureMarginInterestRateModel : IMarginInterestRateModel
    {
        private DateTime _nextFundingRateApplication = DateTime.MaxValue;
        private bool _loggedFundingEvent = false;

        /// <summary>
        /// Apply margin interest rates to the portfolio
        /// </summary>
        /// <param name="marginInterestRateParameters">The parameters to use</param>
        public void ApplyMarginInterestRate(MarginInterestRateParameters marginInterestRateParameters)
        {
            var security = marginInterestRateParameters.Security;
            var time = marginInterestRateParameters.Time;
            var cryptoFuture = (CryptoFuture)security;

            // If no position, reset state
            if (!cryptoFuture.Invested)
            {
                _nextFundingRateApplication = DateTime.MaxValue;
                _loggedFundingEvent = false;
                return;
            }

            // First time with a position, calculate next funding rate application time
            if (_nextFundingRateApplication == DateTime.MaxValue)
            {
                _nextFundingRateApplication = GetNextFundingRateApplication(time);
            }

            // Get the current funding rate from data feed
            var marginInterest = cryptoFuture.Cache.GetData<MarginInterestRate>();
            if (marginInterest == null)
            {
                return;
            }

            // Apply funding rate if we've reached the settlement time
            while (time >= _nextFundingRateApplication)
            {
                // Funding Rate Calculation:
                // Funding Amount = Nominal Value of Position × Funding Rate
                //
                // Sign convention:
                // - Positive rate + Long position = Pay (negative cash flow)
                // - Positive rate + Short position = Receive (positive cash flow)
                // - Negative rate + Long position = Receive (positive cash flow)
                // - Negative rate + Short position = Pay (negative cash flow)

                var holdings = cryptoFuture.Holdings;
                var positionValue = holdings.GetQuantityValue(holdings.Quantity);

                // Calculate funding amount
                var funding = marginInterest.InterestRate * positionValue.Amount;

                // Multiply by -1 because:
                // - We pay when 'funding' is positive:
                //   * Long position (positionValue > 0) & positive rate
                //   * Short position (positionValue < 0) & negative rate
                // - We earn when 'funding' is negative:
                //   * Long position (positionValue > 0) & negative rate
                //   * Short position (positionValue < 0) & positive rate
                funding *= -1;

                // Apply funding to cash balance
                positionValue.Cash.AddAmount(funding);

                // Log funding event for debugging
                if (!_loggedFundingEvent)
                {
                    Log.Trace($"GateFutureMarginInterestRateModel.ApplyMarginInterestRate(): " +
                             $"Symbol: {cryptoFuture.Symbol}, " +
                             $"Time: {_nextFundingRateApplication}, " +
                             $"Rate: {marginInterest.InterestRate:P4}, " +
                             $"Position: {holdings.Quantity}, " +
                             $"Position Value: {positionValue.Amount:F2} {positionValue.Cash.Symbol}, " +
                             $"Funding: {funding:F4} {positionValue.Cash.Symbol}");
                    _loggedFundingEvent = true;
                }

                // Calculate next funding rate application time
                _nextFundingRateApplication = GetNextFundingRateApplication(_nextFundingRateApplication);
            }
        }

        /// <summary>
        /// Get the next funding rate application time based on Gate.io's 8-hour funding schedule (00:00, 08:00, 16:00 UTC)
        /// </summary>
        /// <param name="currentTime">Current time</param>
        /// <returns>Next funding rate settlement time</returns>
        private static DateTime GetNextFundingRateApplication(DateTime currentTime)
        {
            // Gate.io funding times: 00:00, 08:00, 16:00 UTC
            if (currentTime.Hour >= 16)
            {
                // Next funding: tomorrow 00:00
                return currentTime.Date.AddDays(1);
            }
            else if (currentTime.Hour >= 8)
            {
                // Next funding: today 16:00
                return currentTime.Date.AddHours(16);
            }
            else
            {
                // Next funding: today 08:00
                return currentTime.Date.AddHours(8);
            }
        }
    }
}
