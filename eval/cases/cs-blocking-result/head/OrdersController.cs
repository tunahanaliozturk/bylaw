using Microsoft.AspNetCore.Mvc;

namespace Orders;

[ApiController]
[Route("orders")]
public sealed class OrdersController(OrderService orders) : ControllerBase
{
    [HttpGet("{id:int}")]
    public async Task<ActionResult<Order>> Get(int id, CancellationToken cancellationToken)
    {
        var order = await orders.FindAsync(id, cancellationToken);
        return order is null ? NotFound() : order;
    }

    [HttpGet("{id:int}/total")]
    public ActionResult<decimal> Total(int id)
    {
        var order = orders.FindAsync(id, CancellationToken.None).Result;
        return order is null ? NotFound() : order.Total;
    }

    public sealed record PlaceOrder(string Customer, decimal Total);

    [HttpPost]
    public async Task<ActionResult<Order>> Place(PlaceOrder request, CancellationToken cancellationToken)
    {
        var order = await orders.PlaceAsync(request.Customer, request.Total, cancellationToken);
        return CreatedAtAction(nameof(Get), new { id = order.Id }, order);
    }
}
