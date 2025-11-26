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
using QuantConnect.Interfaces;
using QuantConnect.Storage;

namespace QuantConnect.Tests.Common.Storage
{
    [TestFixture]
    public class TieredBackupManagerTests
    {
        private MockBackupStorage _mockStorage;
        private AQCAlgorithm _algorithm;

        [SetUp]
        public void SetUp()
        {
            _mockStorage = new MockBackupStorage();
            _algorithm = new AQCAlgorithm();
        }

        [Test]
        public void Create_WithDefaultSettings_InitializesSuccessfully()
        {
            // Arrange & Act
            var manager = TieredBackupManager.Create(_algorithm);

            // Assert
            Assert.IsNotNull(manager);
        }

        [Test]
        public void SaveBackup_FirstCall_CreatesBackupInMinuteTier()
        {
            // Arrange
            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromMinutes(5), 50),
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new[] { _mockStorage },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act
            var result = manager.SaveBackup("test content 1");

            // Assert
            Assert.IsTrue(result);
            Assert.AreEqual(1, _mockStorage.SavedData.Count);
            Assert.IsTrue(_mockStorage.SavedData.Keys.First().Contains("/min/"));
            Assert.AreEqual("test content 1", _mockStorage.SavedData.Values.First());
        }

        [Test]
        public void SaveBackup_WithinInterval_ReturnsFalse()
        {
            // Arrange
            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromMinutes(5), 50),
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new[] { _mockStorage },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act
            manager.SaveBackup("backup 1");
            var result = manager.SaveBackup("backup 2"); // Immediate second call

            // Assert
            Assert.IsFalse(result); // Should reject because interval not met
            Assert.AreEqual(1, _mockStorage.SavedData.Count); // Only first backup saved
        }

        [Test]
        public void SaveBackup_ExceedsMaxBackups_DeletesOldest()
        {
            // Arrange
            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromSeconds(1), 3), // Max 3 backups
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new[] { _mockStorage },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act - Save 5 backups with delays
            for (int i = 0; i < 5; i++)
            {
                manager.SaveBackup($"backup {i}");
                System.Threading.Thread.Sleep(1100); // Wait for interval
            }

            // Assert
            Assert.AreEqual(3, _mockStorage.SavedData.Count); // Only 3 most recent kept
            Assert.IsTrue(_mockStorage.DeletedKeys.Count > 0); // Old backups deleted
        }

        [Test]
        public void SaveBackup_MultipleStorages_WritesToAll()
        {
            // Arrange
            var storage1 = new MockBackupStorage { Name = "Storage1" };
            var storage2 = new MockBackupStorage { Name = "Storage2" };

            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromMinutes(5), 50),
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new IBackupStorage[] { storage1, storage2 },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act
            manager.SaveBackup("test content");

            // Assert
            Assert.AreEqual(1, storage1.SavedData.Count);
            Assert.AreEqual(1, storage2.SavedData.Count);
            Assert.AreEqual("test content", storage1.SavedData.Values.First());
            Assert.AreEqual("test content", storage2.SavedData.Values.First());
        }

        [Test]
        public void RestoreLatest_NoBackups_ReturnsNull()
        {
            // Arrange
            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromMinutes(5), 50),
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new[] { _mockStorage },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act
            var result = manager.RestoreLatest();

            // Assert
            Assert.IsNull(result);
        }

        [Test]
        public void RestoreLatest_MultipleBackups_ReturnsNewest()
        {
            // Arrange
            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromSeconds(1), 50),
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new[] { _mockStorage },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act
            manager.SaveBackup("backup 1");
            System.Threading.Thread.Sleep(1100);
            manager.SaveBackup("backup 2");
            System.Threading.Thread.Sleep(1100);
            manager.SaveBackup("backup 3");

            var result = manager.RestoreLatest();

            // Assert
            Assert.AreEqual("backup 3", result);
        }

        [Test]
        public void GetStatistics_WithBackups_ReturnsCorrectCounts()
        {
            // Arrange
            var options = new BackupOptions
            {
                MinuteTier = new TierSettings("min", TimeSpan.FromSeconds(1), 50),
                HourTier = new TierSettings("hour", TimeSpan.FromHours(1), 24),
                DailyTier = new TierSettings("daily", TimeSpan.FromDays(1), 7),
                Storages = new[] { _mockStorage },
                AlgorithmName = "TestAlgo"
            };

            var manager = TieredBackupManager.Create(_algorithm, options);

            // Act - Create 3 backups
            for (int i = 0; i < 3; i++)
            {
                manager.SaveBackup($"backup {i}");
                System.Threading.Thread.Sleep(1100);
            }

            var stats = manager.GetStatistics();

            // Assert
            Assert.AreEqual(3, stats.MinuteCount);
            Assert.AreEqual(0, stats.HourCount);
            Assert.AreEqual(0, stats.DailyCount);
            Assert.AreEqual(3, stats.TotalCount);
            Assert.IsNotNull(stats.OldestBackup);
            Assert.IsNotNull(stats.NewestBackup);
        }

        [Test]
        public void TierSettings_InvalidParameters_ThrowsException()
        {
            // Assert - Empty name
            Assert.Throws<ArgumentException>(() =>
                new TierSettings("", TimeSpan.FromMinutes(5), 50));

            // Assert - Zero interval
            Assert.Throws<ArgumentException>(() =>
                new TierSettings("min", TimeSpan.Zero, 50));

            // Assert - Negative max count
            Assert.Throws<ArgumentException>(() =>
                new TierSettings("min", TimeSpan.FromMinutes(5), -1));
        }
    }

    /// <summary>
    /// Mock backup storage for testing
    /// </summary>
    internal class MockBackupStorage : IBackupStorage
    {
        public string Name { get; set; } = "MockStorage";
        public Dictionary<string, string> SavedData { get; } = new Dictionary<string, string>();
        public List<string> DeletedKeys { get; } = new List<string>();

        public bool Save(string key, string content)
        {
            SavedData[key] = content;
            return true;
        }

        public string Read(string key)
        {
            return SavedData.TryGetValue(key, out var content) ? content : null;
        }

        public bool Delete(string key)
        {
            DeletedKeys.Add(key);
            return SavedData.Remove(key);
        }

        public bool Exists(string key)
        {
            return SavedData.ContainsKey(key);
        }

        public IEnumerable<string> ListKeys(string prefix)
        {
            return SavedData.Keys.Where(k => k.StartsWith(prefix));
        }
    }
}
