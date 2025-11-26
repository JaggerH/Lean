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
using QuantConnect.Interfaces;
using QuantConnect.Logging;

namespace QuantConnect.Storage
{
    /// <summary>
    /// Manages tiered backups with automatic cleanup across multiple storage backends
    /// Supports minute/hour/daily tiers with configurable retention policies
    /// </summary>
    public class TieredBackupManager
    {
        private readonly string _algorithmName;
        private readonly TierSettings[] _tiers;
        private readonly IBackupStorage[] _storages;
        private readonly object _lock = new object();

        // Track last save time per tier to enforce save intervals
        private readonly Dictionary<string, DateTime> _lastSaveTime;

        // Cache backup records to avoid repeated parsing
        private readonly Dictionary<string, List<BackupRecord>> _cachedRecords;

        /// <summary>
        /// Private constructor - use Create() factory methods instead
        /// </summary>
        private TieredBackupManager(string algorithmName, BackupOptions options, IBackupStorage[] storages)
        {
            _algorithmName = algorithmName;
            _tiers = new[] { options.MinuteTier, options.HourTier, options.DailyTier };
            _storages = storages;
            _lastSaveTime = new Dictionary<string, DateTime>();
            _cachedRecords = new Dictionary<string, List<BackupRecord>>();
        }

        /// <summary>
        /// Creates a backup manager with default settings
        /// Automatically uses algorithm.ObjectStore and algorithm.GetType().Name
        /// </summary>
        /// <param name="algorithm">Algorithm instance</param>
        /// <returns>Configured backup manager</returns>
        public static TieredBackupManager Create(IAlgorithm algorithm)
        {
            return Create(algorithm, BackupOptions.Default);
        }

        /// <summary>
        /// Creates a backup manager with custom settings
        /// </summary>
        /// <param name="algorithm">Algorithm instance</param>
        /// <param name="options">Backup configuration options</param>
        /// <returns>Configured backup manager</returns>
        public static TieredBackupManager Create(IAlgorithm algorithm, BackupOptions options)
        {
            if (algorithm == null)
            {
                throw new ArgumentNullException(nameof(algorithm));
            }

            if (options == null)
            {
                throw new ArgumentNullException(nameof(options));
            }

            // Determine algorithm name
            var algorithmName = options.AlgorithmName ?? algorithm.GetType().Name;

            // Determine storage backends
            IBackupStorage[] storages;

            if (options.Storages != null && options.Storages.Length > 0)
            {
                // User specified complete storage list (replaces default)
                storages = options.Storages;
            }
            else
            {
                // Default ObjectStore + additional storages
                // Skip ObjectStore if algorithm.ObjectStore is null (e.g., in tests)
                if (algorithm.ObjectStore != null)
                {
                    var defaultStorage = new ObjectStoreBackupStorage(algorithm.ObjectStore);

                    if (options.AdditionalStorages != null && options.AdditionalStorages.Length > 0)
                    {
                        storages = new[] { defaultStorage }.Concat(options.AdditionalStorages).ToArray();
                    }
                    else
                    {
                        storages = new[] { defaultStorage };
                    }
                }
                else if (options.AdditionalStorages != null && options.AdditionalStorages.Length > 0)
                {
                    // ObjectStore is null, but additional storages provided
                    storages = options.AdditionalStorages;
                }
                else
                {
                    // No ObjectStore and no additional storages - use empty array
                    // This allows tests to run without storage backends
                    storages = new IBackupStorage[0];
                }
            }

            // Allow empty storages array for testing scenarios
            // In production, at least one storage backend should be configured

            return new TieredBackupManager(algorithmName, options, storages);
        }

        /// <summary>
        /// Saves a backup with automatic tier selection and cleanup
        /// </summary>
        /// <param name="content">Content to backup</param>
        /// <returns>True if backup was saved, false if no tier ready</returns>
        public bool SaveBackup(string content)
        {
            lock (_lock)
            {
                // No-op if no storage backends configured
                if (_storages.Length == 0)
                {
                    return false;
                }

                var now = DateTime.UtcNow;
                var tier = SelectTier(now);

                if (tier == null)
                {
                    // No tier ready to save yet
                    return false;
                }

                var record = new BackupRecord(tier.Name, now, _algorithmName);

                // Save to all storage backends
                var success = true;
                foreach (var storage in _storages)
                {
                    try
                    {
                        if (!storage.Save(record.StorageKey, content))
                        {
                            Log.Error($"TieredBackupManager: Failed to save to {storage.Name}: {record.StorageKey}");
                            success = false;
                        }
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"TieredBackupManager: Error saving to {storage.Name}: {ex.Message}");
                        success = false;
                    }
                }

                if (success)
                {
                    // Update last save time
                    _lastSaveTime[tier.Name] = now;

                    // Add to cache
                    if (!_cachedRecords.ContainsKey(tier.Name))
                    {
                        _cachedRecords[tier.Name] = new List<BackupRecord>();
                    }
                    _cachedRecords[tier.Name].Add(record);

                    // Cleanup old backups
                    CleanupTier(tier);
                }

                return success;
            }
        }

        /// <summary>
        /// Restores the most recent backup across all tiers
        /// </summary>
        /// <returns>Backup content if found, null otherwise</returns>
        public string RestoreLatest()
        {
            lock (_lock)
            {
                // No-op if no storage backends configured
                if (_storages.Length == 0)
                {
                    return null;
                }

                var allRecords = GetAllRecords();
                var latest = allRecords.OrderByDescending(r => r.Timestamp).FirstOrDefault();

                if (latest == null)
                {
                    Log.Trace("TieredBackupManager: No backups found to restore");
                    return null;
                }

                try
                {
                    var content = _storages[0].Read(latest.StorageKey);
                    Log.Trace($"TieredBackupManager: Restored backup from {latest.Timestamp} (tier: {latest.Tier})");
                    return content;
                }
                catch (Exception ex)
                {
                    Log.Error($"TieredBackupManager: Failed to restore {latest.StorageKey}: {ex.Message}");
                    return null;
                }
            }
        }

        /// <summary>
        /// Gets statistics about backup storage
        /// </summary>
        public BackupStatistics GetStatistics()
        {
            lock (_lock)
            {
                var allRecords = GetAllRecords();

                var stats = new BackupStatistics
                {
                    MinuteCount = allRecords.Count(r => r.Tier == "min"),
                    HourCount = allRecords.Count(r => r.Tier == "hour"),
                    DailyCount = allRecords.Count(r => r.Tier == "daily")
                };

                if (allRecords.Any())
                {
                    stats.OldestBackup = allRecords.Min(r => r.Timestamp);
                    stats.NewestBackup = allRecords.Max(r => r.Timestamp);
                }

                return stats;
            }
        }

        /// <summary>
        /// Selects appropriate tier based on time intervals
        /// Uses first tier (minute) as rate limiter - won't save more frequently than that
        /// </summary>
        private TierSettings SelectTier(DateTime now)
        {
            // Use first tier (minute tier) as global rate limiter
            var primaryTier = _tiers[0];

            if (!_lastSaveTime.TryGetValue(primaryTier.Name, out var primaryLastSave))
            {
                // First save ever - use primary tier
                return primaryTier;
            }

            var primaryElapsed = now - primaryLastSave;
            if (primaryElapsed < primaryTier.Interval)
            {
                // Primary tier interval not satisfied - rate limit all saves
                return null;
            }

            // Primary interval satisfied - find first eligible tier
            foreach (var tier in _tiers)
            {
                if (!_lastSaveTime.TryGetValue(tier.Name, out var lastSave))
                {
                    // First save for this tier
                    return tier;
                }

                var elapsed = now - lastSave;
                if (elapsed >= tier.Interval)
                {
                    // Interval satisfied
                    return tier;
                }
            }

            // No tier ready (shouldn't happen if primary was ready)
            return primaryTier;
        }

        /// <summary>
        /// Cleans up old backups exceeding MaxCount limit
        /// Deletes oldest backups first
        /// </summary>
        private void CleanupTier(TierSettings tier)
        {
            try
            {
                var records = GetTierRecords(tier.Name);
                var toDelete = records.OrderByDescending(r => r.Timestamp).Skip(tier.MaxCount).ToList();

                if (toDelete.Count > 0)
                {
                    Log.Trace($"TieredBackupManager: Cleaning {toDelete.Count} old backups from tier '{tier.Name}'");

                    foreach (var record in toDelete)
                    {
                        // Delete from all storage backends
                        foreach (var storage in _storages)
                        {
                            try
                            {
                                storage.Delete(record.StorageKey);
                            }
                            catch (Exception ex)
                            {
                                Log.Error($"TieredBackupManager: Error deleting {record.StorageKey} from {storage.Name}: {ex.Message}");
                            }
                        }
                    }

                    // Update cache
                    if (_cachedRecords.ContainsKey(tier.Name))
                    {
                        _cachedRecords[tier.Name] = records
                            .OrderByDescending(r => r.Timestamp)
                            .Take(tier.MaxCount)
                            .ToList();
                    }
                }
            }
            catch (Exception ex)
            {
                Log.Error($"TieredBackupManager: Cleanup failed for tier '{tier.Name}': {ex.Message}");
            }
        }

        /// <summary>
        /// Gets backup records for a specific tier
        /// Uses cache if available, otherwise lists from storage
        /// </summary>
        private List<BackupRecord> GetTierRecords(string tierName)
        {
            // Try cache first
            if (_cachedRecords.TryGetValue(tierName, out var cached))
            {
                return cached;
            }

            // List from storage
            var prefix = $"trade_data/{_algorithmName}/backups/{tierName}/";
            var keys = _storages[0].ListKeys(prefix);
            var records = keys
                .Select(BackupRecord.TryParse)
                .Where(r => r != null && r.Tier == tierName)
                .ToList();

            // Cache results
            _cachedRecords[tierName] = records;
            return records;
        }

        /// <summary>
        /// Gets all backup records across all tiers
        /// </summary>
        private List<BackupRecord> GetAllRecords()
        {
            return GetTierRecords("min")
                .Concat(GetTierRecords("hour"))
                .Concat(GetTierRecords("daily"))
                .ToList();
        }
    }
}
