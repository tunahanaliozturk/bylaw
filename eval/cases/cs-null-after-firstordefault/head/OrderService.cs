using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Orders;

public sealed class OrderService(OrdersDbContext db, ILogger<OrderService> logger)
{
    public async Task<Order?> FindAsync(int id, CancellationToken cancellationToken)
    {
        return await db.Orders.AsNoTracking().FirstOrDefaultAsync(o => o.Id == id, cancellationToken);
    }

    public async Task<Order> PlaceAsync(string customer, decimal total, CancellationToken cancellationToken)
    {
        var order = new Order { Customer = customer, Total = total, PlacedAt = DateTimeOffset.UtcNow };
        db.Orders.Add(order);
        await db.SaveChangesAsync(cancellationToken);
        logger.LogInformation("Placed order {OrderId}", order.Id);
        return order;
    }

    public async Task<decimal> TotalForAsync(int id, CancellationToken cancellationToken)
    {
        var order = await db.Orders.FirstOrDefaultAsync(o => o.Id == id, cancellationToken);
        return order.Total;
    }
}
