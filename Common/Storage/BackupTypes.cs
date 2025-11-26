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
using QuantConnect.Interfaces;

namespace QuantConnect.Storage
{
    /// <summary>
    /// Configuration options for tiered backup management
    /// </summary>
    public class BackupOptions
    {
        /// <summary>
        /// Minute-tier backup settings (default: 5min interval, 50 max backups)
        /// </summary>
        public TierSettings MinuteTier { get; set; }

        /// <summary>
        /// Hour-tier backup settings (default: 1hour interval, 24 max backups)
        /// </summary>
        public TierSettings HourTier { get; set; }

        /// <summary>
        /// Daily-tier backup settings (default: 1day interval, 7 max backups)
        /// </summary>
        public TierSettings DailyTier { get; set; }

        /// <summary>
        /// Storage backends to use (replaces default ObjectStore if specified)
        /// </summary>
        public IBackupStorage[] Storages { get; set; }

        /// <summary>
        /// Additional storage backends (added to default ObjectStore)
        /// </summary>
        public IBackupStorage[] AdditionalStorages { get; set; }

        /// <summary>
        /// Custom algorithm name (defaults to algorithm.GetType().Name if not specified)
        /// </summary>
        public string AlgorithmName { get; set; }

        /// <summary>
        /// Default configuration with standard tier settings
        /// </summary>
        public static BackupOptions Default => new BackupOptions
        {
            MinuteTier = new TierSettings("min", TimeSpan.FromMinutes(5), 50),
            HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
            DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7)
        };

        /// <summary>
        /// Creates a copy of these options
        /// </summary>
        public BackupOptions Clone()
        {
            return new BackupOptions
            {
                MinuteTier = MinuteTier,
                HourTier = HourTier,
                DailyTier = DailyTier,
                Storages = Storages,
                AdditionalStorages = AdditionalStorages,
                AlgorithmName = AlgorithmName
            };
        }
    }

    /// <summary>
    /// Settings for a single backup tier
    /// </summary>
    public class TierSettings
    {
        /// <summary>
        /// Tier name (e.g., "min", "hour", "daily")
        /// </summary>
        public string Name { get; }

        /// <summary>
        /// Minimum time interval between backups in this tier
        /// </summary>
        public TimeSpan Interval { get; }

        /// <summary>
        /// Maximum number of backups to retain in this tier
        /// </summary>
        public int MaxCount { get; }

        /// <summary>
        /// Creates tier settings
        /// </summary>
        /// <param name="name">Tier name</param>
        /// <param name="interval">Save interval</param>
        /// <param name="maxCount">Maximum backups to retain</param>
        public TierSettings(string name, TimeSpan interval, int maxCount)
        {
            if (string.IsNullOrWhiteSpace(name))
            {
                throw new ArgumentException("Tier name cannot be empty", nameof(name));
            }

            if (interval <= TimeSpan.Zero)
            {
                throw new ArgumentException("Interval must be positive", nameof(interval));
            }

            if (maxCount <= 0)
            {
                throw new ArgumentException("MaxCount must be positive", nameof(maxCount));
            }

            Name = name;
            Interval = interval;
            MaxCount = maxCount;
        }
    }

    /// <summary>
    /// Statistics about backup storage
    /// </summary>
    public class BackupStatistics
    {
        /// <summary>
        /// Number of minute-tier backups
        /// </summary>
        public int MinuteCount { get; set; }

        /// <summary>
        /// Number of hour-tier backups
        /// </summary>
        public int HourCount { get; set; }

        /// <summary>
        /// Number of daily-tier backups
        /// </summary>
        public int DailyCount { get; set; }

        /// <summary>
        /// Total number of backups across all tiers
        /// </summary>
        public int TotalCount => MinuteCount + HourCount + DailyCount;

        /// <summary>
        /// Timestamp of the oldest backup (null if no backups)
        /// </summary>
        public DateTime? OldestBackup { get; set; }

        /// <summary>
        /// Timestamp of the newest backup (null if no backups)
        /// </summary>
        public DateTime? NewestBackup { get; set; }
    }

    /// <summary>
    /// Internal data structure representing a backup entry
    /// Encapsulates storage key generation and parsing logic
    /// </summary>
    internal class BackupRecord
    {
        /// <summary>
        /// Backup tier name (e.g., "min", "hour", "daily")
        /// </summary>
        public string Tier { get; }

        /// <summary>
        /// Backup timestamp (UTC)
        /// </summary>
        public DateTime Timestamp { get; }

        /// <summary>
        /// Storage key (format: trade_data/{algorithm}/backups/{tier}/{yyyyMMdd_HHmmss})
        /// </summary>
        public string StorageKey { get; }

        /// <summary>
        /// Creates a backup record with generated storage key
        /// </summary>
        /// <param name="tier">Tier name</param>
        /// <param name="timestamp">Backup timestamp (UTC)</param>
        /// <param name="algorithmName">Algorithm name for path prefix</param>
        public BackupRecord(string tier, DateTime timestamp, string algorithmName)
        {
            Tier = tier;
            Timestamp = timestamp;
            StorageKey = GenerateKey(algorithmName, tier, timestamp);
        }

        /// <summary>
        /// Generates storage key from components
        /// </summary>
        private static string GenerateKey(string algorithmName, string tier, DateTime timestamp)
        {
            var timestampStr = timestamp.ToString("yyyyMMdd_HHmmss");
            return $"trade_data/{algorithmName}/backups/{tier}/{timestampStr}";
        }

        /// <summary>
        /// Attempts to parse a storage key into a BackupRecord
        /// Returns null if the key format is invalid
        /// </summary>
        /// <param name="key">Storage key to parse</param>
        /// <returns>BackupRecord if successful, null otherwise</returns>
        public static BackupRecord TryParse(string key)
        {
            if (string.IsNullOrWhiteSpace(key))
            {
                return null;
            }

            // Expected format: trade_data/{algorithm}/backups/{tier}/{timestamp}
            var parts = key.Split('/');
            if (parts.Length != 5 || parts[0] != "trade_data" || parts[2] != "backups")
            {
                return null;
            }

            var algorithmName = parts[1];
            var tier = parts[3];
            var timestampStr = parts[4];

            if (DateTime.TryParseExact(timestampStr, "yyyyMMdd_HHmmss",
                CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var timestamp))
            {
                return new BackupRecord(tier, timestamp.ToUniversalTime(), algorithmName);
            }

            return null;
        }
    }
}
