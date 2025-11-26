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
using System.Text;
using QuantConnect.Interfaces;

namespace QuantConnect.Storage
{
    /// <summary>
    /// ObjectStore implementation of IBackupStorage
    /// Provides backup storage using LEAN's built-in ObjectStore
    /// </summary>
    public class ObjectStoreBackupStorage : IBackupStorage
    {
        private readonly IObjectStore _objectStore;
        private static readonly Encoding DefaultEncoding = Encoding.UTF8;

        /// <summary>
        /// Storage backend name
        /// </summary>
        public string Name => "ObjectStore";

        /// <summary>
        /// Creates an ObjectStore backup storage
        /// </summary>
        /// <param name="objectStore">ObjectStore instance</param>
        public ObjectStoreBackupStorage(IObjectStore objectStore)
        {
            _objectStore = objectStore ?? throw new ArgumentNullException(nameof(objectStore));
        }

        /// <summary>
        /// Saves content to the specified key
        /// </summary>
        public bool Save(string key, string content)
        {
            var bytes = DefaultEncoding.GetBytes(content);
            return _objectStore.SaveBytes(key, bytes);
        }

        /// <summary>
        /// Reads content from the specified key
        /// </summary>
        public string Read(string key)
        {
            if (!_objectStore.ContainsKey(key))
            {
                return null;
            }

            var bytes = _objectStore.ReadBytes(key);
            return bytes != null ? DefaultEncoding.GetString(bytes) : null;
        }

        /// <summary>
        /// Deletes content at the specified key
        /// </summary>
        public bool Delete(string key)
        {
            return _objectStore.Delete(key);
        }

        /// <summary>
        /// Checks if a key exists
        /// </summary>
        public bool Exists(string key)
        {
            return _objectStore.ContainsKey(key);
        }

        /// <summary>
        /// Lists all keys with the specified prefix
        /// </summary>
        public IEnumerable<string> ListKeys(string prefix)
        {
            // Simple prefix matching
            return _objectStore.Keys.Where(k => k.StartsWith(prefix));
        }
    }
}
