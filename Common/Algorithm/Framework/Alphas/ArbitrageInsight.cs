using System;
using QuantConnect.Securities;
using QuantConnect.Data.Market;

namespace QuantConnect.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Represents a trading signal for arbitrage opportunities on a TradingPair at a specific grid level
    /// </summary>
    public class ArbitrageInsight
    {
        /// <summary>
        /// Unique identifier for this insight (used for logging, tracking, serialization)
        /// </summary>
        public Guid Id { get; }

        /// <summary>
        /// Reference to the TradingPair this insight is for
        /// </summary>
        public TradingPairs.TradingPair TradingPair { get; }

        /// <summary>
        /// Reference to the specific grid level that triggered this insight
        /// </summary>
        public TradingPairs.Grid.GridLevelPair LevelPair { get; }

        /// <summary>
        /// Type of signal: Entry (open position) or Exit (close position)
        /// </summary>
        public SignalType Type { get; }

        /// <summary>
        /// Direction of the spread trade (determined at construction time, immutable)
        /// </summary>
        public SpreadDirection Direction { get; }

        /// <summary>
        /// Snapshot of the spread at the moment this insight was triggered (in percentage, e.g. 0.025 = 2.5%)
        /// </summary>
        public decimal SnapshotSpread { get; }

        /// <summary>
        /// Timestamp when this insight was triggered
        /// </summary>
        public DateTime SnapshotTime { get; }

        /// <summary>
        /// UTC time when this insight was generated (set by framework)
        /// </summary>
        public DateTime GeneratedTimeUtc { get; internal set; }

        /// <summary>
        /// UTC time when this insight expires (set by framework based on Period)
        /// </summary>
        public DateTime CloseTimeUtc { get; internal set; }

        /// <summary>
        /// How long this insight is valid for
        /// </summary>
        public TimeSpan Period { get; }

        /// <summary>
        /// Name of the alpha model that generated this insight
        /// </summary>
        public string SourceModel { get; set; }

        /// <summary>
        /// Confidence level for this insight (0-1 scale)
        /// </summary>
        public double Confidence { get; }

        /// <summary>
        /// Expected profit from this trade (calculated from grid level's entry-exit spread difference)
        /// </summary>
        public decimal ExpectedProfit => Math.Abs(LevelPair.Entry.SpreadPct - LevelPair.Exit.SpreadPct);

        /// <summary>
        /// Creates a new ArbitrageInsight
        /// </summary>
        /// <param name="tradingPair">The trading pair for this insight</param>
        /// <param name="levelPair">The grid level that triggered this insight</param>
        /// <param name="type">Signal type (Entry or Exit)</param>
        /// <param name="direction">Spread direction (LongSpread, ShortSpread, or FlatSpread)</param>
        /// <param name="snapshotSpread">Current spread value in percentage (e.g., 0.025 for 2.5%)</param>
        /// <param name="period">How long this insight should remain valid</param>
        /// <param name="confidence">Confidence level (0-1), defaults to 1.0</param>
        public ArbitrageInsight(
            TradingPairs.TradingPair tradingPair,
            TradingPairs.Grid.GridLevelPair levelPair,
            SignalType type,
            SpreadDirection direction,
            decimal snapshotSpread,
            TimeSpan period,
            double confidence = 1.0)
        {
            if (confidence < 0 || confidence > 1)
            {
                throw new ArgumentOutOfRangeException(nameof(confidence), "Confidence must be between 0 and 1");
            }

            Id = Guid.NewGuid();
            TradingPair = tradingPair ?? throw new ArgumentNullException(nameof(tradingPair));
            LevelPair = levelPair ?? throw new ArgumentNullException(nameof(levelPair));
            Type = type;
            Direction = direction;
            SnapshotSpread = snapshotSpread;
            SnapshotTime = DateTime.UtcNow;
            Period = period;
            Confidence = confidence;
        }

        /// <summary>
        /// Checks if this insight is still active (not expired)
        /// </summary>
        /// <param name="utcTime">Current UTC time</param>
        /// <returns>True if the insight has not expired yet</returns>
        public bool IsActive(DateTime utcTime)
        {
            return CloseTimeUtc >= utcTime;
        }

        /// <summary>
        /// Cancels this insight by setting its expiration time to just before the current time
        /// </summary>
        /// <param name="utcTime">Current UTC time</param>
        public void Cancel(DateTime utcTime)
        {
            if (IsActive(utcTime))
            {
                CloseTimeUtc = utcTime.AddSeconds(-1);
            }
        }

        /// <summary>
        /// Returns a string representation of this insight for debugging
        /// </summary>
        public override string ToString()
        {
            return $"ArbitrageInsight[{Type}] {TradingPair.Leg1Symbol.Value}/{TradingPair.Leg2Symbol.Value} @ {LevelPair.Entry.NaturalKey} " +
                   $"Dir={Direction}, Spread={SnapshotSpread:P2}, Time={SnapshotTime:HH:mm:ss.fff}";
        }
    }

    /// <summary>
    /// Type of arbitrage signal
    /// </summary>
    public enum SignalType
    {
        /// <summary>
        /// Signal to open a new position
        /// </summary>
        Entry,

        /// <summary>
        /// Signal to close an existing position
        /// </summary>
        Exit
    }

    /// <summary>
    /// Direction of the spread trade
    /// </summary>
    public enum SpreadDirection
    {
        /// <summary>
        /// Long the spread: short crypto, long stock (when crypto is overpriced)
        /// </summary>
        LongSpread,

        /// <summary>
        /// Short the spread: long crypto, short stock (when stock is overpriced)
        /// </summary>
        ShortSpread,

        /// <summary>
        /// Flat/close the spread position
        /// </summary>
        FlatSpread
    }
}
