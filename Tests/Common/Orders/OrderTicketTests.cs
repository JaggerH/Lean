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
using NUnit.Framework;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;

namespace QuantConnect.Tests.Common.Orders
{
    [TestFixture]
    public class OrderTicketTests
    {
        private DateTime _requestTime = new DateTime(2022, 08, 25, 15, 0, 0);

        [Test]
        public void TestInvalidUpdateOrderId()
        {
            var updateFields = new UpdateOrderFields { Quantity = 99, Tag = "Pepe", StopPrice = 77 , LimitPrice = 55 };
            var updateRequest = new UpdateOrderRequest(_requestTime, 11, updateFields);
            var ticket = OrderTicket.InvalidUpdateOrderId(null, updateRequest);
            Assert.AreEqual(11, ticket.OrderId);
            Assert.AreEqual(0, ticket.Quantity);
            Assert.AreEqual("Pepe", ticket.Tag);
            Assert.AreEqual(OrderStatus.Invalid, ticket.Status);
            Assert.AreEqual(1, ticket.UpdateRequests.Count);
            Assert.AreEqual(OrderRequestStatus.Error, ticket.UpdateRequests[0].Status);
            Assert.AreEqual(OrderResponseErrorCode.UnableToFindOrder, ticket.UpdateRequests[0].Response.ErrorCode);
            Assert.AreEqual(11, ticket.UpdateRequests[0].OrderId);
            Assert.AreEqual(99, ticket.UpdateRequests[0].Quantity);
            Assert.AreEqual("Pepe", ticket.UpdateRequests[0].Tag);
            Assert.AreEqual(77, ticket.UpdateRequests[0].StopPrice);
            Assert.AreEqual(55, ticket.UpdateRequests[0].LimitPrice);
        }
        [Test]
        public void TestInvalidCancelOrderId()
        {
            var cancelRequest = new CancelOrderRequest(_requestTime, 11, "Pepe");
            var ticket = OrderTicket.InvalidCancelOrderId(null, cancelRequest);
            Assert.AreEqual(11, ticket.OrderId);
            Assert.AreEqual(0, ticket.Quantity);
            Assert.AreEqual("Pepe", ticket.Tag);
            Assert.AreEqual(OrderStatus.Invalid, ticket.Status);
            Assert.AreEqual(cancelRequest, ticket.CancelRequest);
            Assert.AreEqual(OrderRequestStatus.Error, ticket.CancelRequest.Status);
            Assert.AreEqual(OrderResponseErrorCode.UnableToFindOrder, ticket.CancelRequest.Response.ErrorCode);
            Assert.AreEqual(11, ticket.CancelRequest.OrderId);
            Assert.AreEqual("Pepe", ticket.CancelRequest.Tag);
        }
        [Test]
        public void TestInvalidSubmitRequest()
        {
            var orderRequest = new SubmitOrderRequest(OrderType.Limit, SecurityType.Equity, Symbols.AAPL, 1000, 0, 1.11m, _requestTime, "Pepe");
            var order = Order.CreateOrder(orderRequest);
            orderRequest.SetOrderId(orderRequest.OrderId);
            var orderResponse = OrderResponse.InvalidStatus(orderRequest, order);
            var ticket = OrderTicket.InvalidSubmitRequest(null, orderRequest, orderResponse);
            Assert.AreEqual(orderRequest.OrderId, ticket.OrderId);
            Assert.AreEqual(1000, ticket.Quantity);
            Assert.AreEqual("Pepe", ticket.Tag);
            Assert.AreEqual(OrderStatus.Invalid, ticket.Status);
            Assert.AreEqual(OrderType.Limit, ticket.OrderType);
            Assert.AreEqual(SecurityType.Equity, ticket.SecurityType);
            Assert.AreEqual(Symbols.AAPL, ticket.Symbol);
            Assert.AreEqual(orderRequest, ticket.SubmitRequest);
            Assert.AreEqual(OrderRequestStatus.Error, ticket.SubmitRequest.Status);
            Assert.AreEqual(orderRequest.OrderId, ticket.SubmitRequest.OrderId);
            Assert.AreEqual(1000, ticket.SubmitRequest.Quantity);
            Assert.AreEqual("Pepe", ticket.SubmitRequest.Tag);
        }
        [Test]
        public void TestInvalidWarmingUp()
        {
            var orderRequest = new SubmitOrderRequest(OrderType.Limit, SecurityType.Equity, Symbols.AAPL, 1000, 0, 1.11m, _requestTime, "Pepe");
            orderRequest.SetOrderId(orderRequest.OrderId);
            var algorithmSub = new AlgorithmStub();
            var ticket = algorithmSub.SubmitOrderRequest(orderRequest);
            Assert.AreEqual(orderRequest.OrderId, ticket.OrderId);
            Assert.AreEqual(1000, ticket.Quantity);
            Assert.AreEqual("Pepe", ticket.Tag);
            Assert.AreEqual(OrderStatus.Invalid, ticket.Status);
            Assert.AreEqual(OrderType.Limit, ticket.OrderType);
            Assert.AreEqual(SecurityType.Equity, ticket.SecurityType);
            Assert.AreEqual(Symbols.AAPL, ticket.Symbol);
            Assert.AreEqual(orderRequest, ticket.SubmitRequest);
            Assert.AreEqual(OrderRequestStatus.Error, ticket.SubmitRequest.Status);
            Assert.AreEqual(orderRequest.OrderId, ticket.SubmitRequest.OrderId);
            Assert.AreEqual(1000, ticket.SubmitRequest.Quantity);
            Assert.AreEqual("Pepe", ticket.SubmitRequest.Tag);
            Assert.AreEqual("This operation is not allowed in Initialize or during warm up: OrderRequest.Submit. Please move this code to the OnWarmupFinished() method.", ticket.SubmitRequest.Response.ErrorMessage);
        }

        [TestCase(8, 0, true, Description = "8 AM - valid submission")]
        [TestCase(12, 0, false, Description = "12 PM - invalid submission")]
        [TestCase(15, 30, false, Description = "3:30 PM - invalid submission")]
        [TestCase(15, 59, false, Description = "15:59 PM - invalid submission")]
        [TestCase(17, 0, true, Description = "5 PM - valid submission")]
        [TestCase(21, 0, true, Description = "9 PM - valid submission")]
        public void MarketOnOpenOrderSubmissionRespectsAllowedTimeRange(int hourOfDay, int minuteOfDay, bool shouldBeValid)
        {
            var symbol = Symbols.SPY;
            var algorithm = new AlgorithmStub();
            algorithm.SetStartDate(2025, 04, 30);

            var security = algorithm.AddSecurity(symbol.ID.SecurityType, symbol.ID.Symbol);
            algorithm.SetFinishedWarmingUp();
            security.Update([new Tick(algorithm.Time, symbol, string.Empty, string.Empty, 10m, 550m)], typeof(TradeBar));

            // Set algorithm time to the given hour
            var targetTime = algorithm.Time.Date.AddHours(hourOfDay).AddMinutes(minuteOfDay);
            algorithm.SetDateTime(targetTime.ConvertToUtc(algorithm.TimeZone));

            var order = new MarketOnOpenOrder(security.Symbol, 1, DateTime.UtcNow);

            var request = algorithm.SubmitOrderRequest(new SubmitOrderRequest(
                order.Type,
                security.Type,
                security.Symbol,
                order.Quantity,
                0m,
                0m,
                order.Time,
                string.Empty));

            if (shouldBeValid)
            {
                Assert.AreEqual(OrderStatus.New, request.Status, $"Expected order at {hourOfDay}:00 to be valid.");
                Assert.AreEqual(1, request.OrderId);
            }
            else
            {
                Assert.AreEqual(OrderStatus.Invalid, request.Status, $"Expected order at {hourOfDay}:00 to be invalid.");
                Assert.AreEqual(-10, request.OrderId);
            }
        }

        [Test]
        public void TestOrderTicketSerialization()
        {
            // Arrange: Create a completed order ticket
            var algorithm = new AlgorithmStub();
            algorithm.SetStartDate(2025, 01, 15);
            algorithm.SetFinishedWarmingUp();

            var symbol = Symbols.BTCUSD;
            var security = algorithm.AddSecurity(symbol.ID.SecurityType, symbol.ID.Symbol);

            // Submit a market order
            var submitRequest = new SubmitOrderRequest(
                OrderType.Market,
                SecurityType.Crypto,
                symbol,
                0.5m,  // quantity
                0, 0,
                algorithm.UtcTime,
                "test-order"
            );
            submitRequest.SetOrderId(123);

            var ticket = new OrderTicket(algorithm.Transactions, submitRequest);

            // Create and set order
            var order = Order.CreateOrder(submitRequest);
            order.Status = OrderStatus.Filled;
            order.BrokerId.Add("BROKER-456");
            order.LastFillTime = algorithm.UtcTime.AddSeconds(5);
            order.LastUpdateTime = algorithm.UtcTime.AddSeconds(5);

            ticket.SetOrder(order);

            // Simulate fill
            var orderEvent = new OrderEvent(
                123,
                symbol,
                algorithm.UtcTime,
                OrderStatus.Filled,
                OrderDirection.Buy,
                50000m,  // fill price
                0.5m,    // fill quantity
                new OrderFee(new CashAmount(25m, "USD")),
                "Filled"
            );
            ticket.AddOrderEvent(orderEvent);

            // Act: Serialize to JSON
            string json = ticket.ToJson();

            Assert.IsNotNull(json, "Serialized JSON should not be null");
            Assert.IsTrue(json.Length > 0, "Serialized JSON should not be empty");

            // Deserialize from JSON
            var restoredTicket = OrderTicket.FromJson(json, algorithm.Transactions);

            // Assert: Verify all fields match
            Assert.AreEqual(ticket.OrderId, restoredTicket.OrderId, "OrderId should match");
            Assert.AreEqual("BROKER-456", restoredTicket.BrokerId[0], "BrokerId should match");
            Assert.AreEqual(ticket.Symbol.Value, restoredTicket.Symbol.Value, "Symbol should match");
            Assert.AreEqual(ticket.Quantity, restoredTicket.Quantity, "Quantity should match");
            Assert.AreEqual(ticket.QuantityFilled, restoredTicket.QuantityFilled, "QuantityFilled should match");
            Assert.AreEqual(ticket.AverageFillPrice, restoredTicket.AverageFillPrice, "AverageFillPrice should match");
            Assert.AreEqual(OrderStatus.Filled, restoredTicket.Status, "Status should be Filled");
            Assert.AreEqual("test-order", restoredTicket.Tag, "Tag should match");
        }

        [Test]
        public void TestOrderTicketSerializationWithMultipleFills()
        {
            // Arrange: Create a partially filled order ticket with multiple fills
            var algorithm = new AlgorithmStub();
            algorithm.SetStartDate(2025, 01, 15);
            algorithm.SetFinishedWarmingUp();

            var symbol = Symbols.SPY;
            var security = algorithm.AddSecurity(symbol.ID.SecurityType, symbol.ID.Symbol);

            // Submit a limit order
            var submitRequest = new SubmitOrderRequest(
                OrderType.Limit,
                SecurityType.Equity,
                symbol,
                100m,  // quantity
                0,
                500m,  // limit price
                algorithm.UtcTime,
                "multi-fill-test"
            );
            submitRequest.SetOrderId(456);

            var ticket = new OrderTicket(algorithm.Transactions, submitRequest);

            // Create and set order
            var order = new LimitOrder(symbol, 100m, 500m, algorithm.UtcTime, "multi-fill-test");
            order.Status = OrderStatus.PartiallyFilled;
            order.BrokerId.Add("BROKER-789");
            order.LastUpdateTime = algorithm.UtcTime.AddSeconds(10);

            ticket.SetOrder(order);

            // Simulate multiple fills
            var fill1 = new OrderEvent(
                456, symbol, algorithm.UtcTime.AddSeconds(1),
                OrderStatus.PartiallyFilled, OrderDirection.Buy,
                500.5m, 30m,  // First fill: 30 shares at $500.50
                new OrderFee(new CashAmount(1.5m, "USD")),
                "Partial Fill 1"
            );
            ticket.AddOrderEvent(fill1);

            var fill2 = new OrderEvent(
                456, symbol, algorithm.UtcTime.AddSeconds(5),
                OrderStatus.PartiallyFilled, OrderDirection.Buy,
                499.8m, 50m,  // Second fill: 50 shares at $499.80
                new OrderFee(new CashAmount(2.5m, "USD")),
                "Partial Fill 2"
            );
            ticket.AddOrderEvent(fill2);

            order.Status = OrderStatus.PartiallyFilled;

            // Act: Serialize to JSON
            string json = ticket.ToJson();
            var restoredTicket = OrderTicket.FromJson(json, algorithm.Transactions);

            // Assert: Verify multi-fill calculations
            Assert.AreEqual(80m, restoredTicket.QuantityFilled, "QuantityFilled should be sum of fills (30 + 50)");

            // Calculate expected average fill price: (30 * 500.5 + 50 * 499.8) / 80 = 500.0625
            var expectedAvgPrice = (30m * 500.5m + 50m * 499.8m) / 80m;
            Assert.AreEqual(expectedAvgPrice, restoredTicket.AverageFillPrice, "AverageFillPrice should be weighted average");

            Assert.AreEqual(OrderStatus.PartiallyFilled, restoredTicket.Status, "Status should be PartiallyFilled");
            Assert.AreEqual(20m, restoredTicket.QuantityRemaining, "QuantityRemaining should be 20 (100 - 80)");
        }

        [Test]
        public void TestOrderTicketSerializationFailsWithoutOrder()
        {
            // Arrange: Create an order ticket without setting the order
            var algorithm = new AlgorithmStub();
            algorithm.SetStartDate(2025, 01, 15);

            var submitRequest = new SubmitOrderRequest(
                OrderType.Market,
                SecurityType.Equity,
                Symbols.AAPL,
                10m,
                0, 0,
                algorithm.UtcTime,
                "test"
            );
            submitRequest.SetOrderId(789);

            var ticket = new OrderTicket(algorithm.Transactions, submitRequest);

            // Act & Assert: Should throw exception because order hasn't been set
            Assert.Throws<InvalidOperationException>(() => ticket.ToJson(),
                "ToJson should throw InvalidOperationException when order is not set");
        }
    }
}
