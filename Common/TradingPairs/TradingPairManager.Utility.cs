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
using System.Globalization;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Utility methods for TradingPairManager
    /// </summary>
    public partial class TradingPairManager
    {
        #region Tag Encoding/Decoding

        /// <summary>
        /// Encodes grid position identifiers and configuration into an order tag.
        /// Format: "{Symbol1.ID}|{Symbol2.ID}|{EntrySpread}|{ExitSpread}|{Direction}|{PositionSize}"
        /// Example: "SPY 2T|QQQ 2T|-0.0200|0.0050|LONG_SPREAD|0.2500"
        /// </summary>
        /// <param name="symbol1">First symbol in the trading pair</param>
        /// <param name="symbol2">Second symbol in the trading pair</param>
        /// <param name="levelPair">Grid level pair configuration</param>
        /// <returns>Encoded tag string</returns>
        public static string EncodeGridTag(Symbol symbol1, Symbol symbol2, GridLevelPair levelPair)
        {
            if (symbol1 == null) throw new ArgumentNullException(nameof(symbol1));
            if (symbol2 == null) throw new ArgumentNullException(nameof(symbol2));
            if (levelPair == null) throw new ArgumentNullException(nameof(levelPair));

            // Use SecurityIdentifier.ToString() for robust serialization
            // Format: "SID1|SID2|EntrySpread|ExitSpread|Direction|PositionSize"
            return string.Format(CultureInfo.InvariantCulture,
                "{0}|{1}|{2:F4}|{3:F4}|{4}|{5:F4}",
                symbol1.ID,
                symbol2.ID,
                levelPair.Entry.SpreadPct,
                levelPair.Exit.SpreadPct,
                levelPair.Entry.Direction,
                levelPair.Entry.PositionSizePct);
        }

        /// <summary>
        /// Decodes grid position identifiers and configuration from an order tag.
        /// </summary>
        /// <param name="tag">The order tag to decode</param>
        /// <param name="leg1Symbol">Output: First symbol</param>
        /// <param name="leg2Symbol">Output: Second symbol</param>
        /// <param name="levelPair">Output: Reconstructed grid level pair</param>
        /// <returns>True if successfully decoded, false otherwise</returns>
        public static bool TryDecodeGridTag(
            string tag,
            out Symbol leg1Symbol,
            out Symbol leg2Symbol,
            out GridLevelPair levelPair)
        {
            leg1Symbol = null;
            leg2Symbol = null;
            levelPair = null;

            if (string.IsNullOrEmpty(tag))
                return false;

            var parts = tag.Split('|');
            if (parts.Length != 6)
                return false;

            try
            {
                // Parse SecurityIdentifiers
                if (!SecurityIdentifier.TryParse(parts[0], out var sid1))
                    return false;

                if (!SecurityIdentifier.TryParse(parts[1], out var sid2))
                    return false;

                // Parse GridLevelPair configuration
                decimal entrySpread = decimal.Parse(parts[2], CultureInfo.InvariantCulture);
                decimal exitSpread = decimal.Parse(parts[3], CultureInfo.InvariantCulture);
                string direction = parts[4];
                decimal positionSize = decimal.Parse(parts[5], CultureInfo.InvariantCulture);

                // Reconstruct symbols from SecurityIdentifiers
                leg1Symbol = new Symbol(sid1, sid1.Symbol);
                leg2Symbol = new Symbol(sid2, sid2.Symbol);

                // Reconstruct GridLevelPair
                levelPair = new GridLevelPair(
                    entrySpreadPct: entrySpread,
                    exitSpreadPct: exitSpread,
                    direction: direction,
                    positionSizePct: positionSize);

                return true;
            }
            catch
            {
                return false;
            }
        }

        #endregion
    }
}
