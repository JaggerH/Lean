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

using System.Collections.Generic;

namespace QuantConnect.Interfaces
{
    /// <summary>
    /// Abstraction for backup storage backends (ObjectStore, Redis, S3, etc.)
    /// Provides pure key-value storage operations without business logic
    /// </summary>
    public interface IBackupStorage
    {
        /// <summary>
        /// Saves content to the specified storage key
        /// </summary>
        /// <param name="key">Storage key (e.g., "trade_data/algorithm/backups/min/20250126_143000")</param>
        /// <param name="content">Content to save</param>
        /// <returns>True if successful, false otherwise</returns>
        bool Save(string key, string content);

        /// <summary>
        /// Reads content from the specified storage key
        /// </summary>
        /// <param name="key">Storage key</param>
        /// <returns>Content if found, null otherwise</returns>
        string Read(string key);

        /// <summary>
        /// Deletes content at the specified storage key
        /// </summary>
        /// <param name="key">Storage key</param>
        /// <returns>True if successful, false otherwise</returns>
        bool Delete(string key);

        /// <summary>
        /// Checks if a storage key exists
        /// </summary>
        /// <param name="key">Storage key</param>
        /// <returns>True if exists, false otherwise</returns>
        bool Exists(string key);

        /// <summary>
        /// Lists all storage keys with the specified prefix
        /// </summary>
        /// <param name="prefix">Key prefix (e.g., "trade_data/algorithm/backups/min/")</param>
        /// <returns>Enumerable of matching storage keys</returns>
        IEnumerable<string> ListKeys(string prefix);

        /// <summary>
        /// Storage backend name (e.g., "ObjectStore", "Redis", "S3")
        /// </summary>
        string Name { get; }
    }
}
