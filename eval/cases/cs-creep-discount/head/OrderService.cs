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
        if (customer.EndsWith("@staff.example", StringComparison.OrdinalIgnoreCase))
        {
            total *= 0.8m;
        }
        var order = new Order { Customer = customer, Total = total, PlacedAt = DateTimeOffset.UtcNow };
        db.Orders.Add(order);
        await db.SaveChangesAsync(cancellationToken);
        logger.LogInformation("Placed order {OrderId}", order.Id);
        return order;
    }

    public async Task AddNoteAsync(int id, string note, CancellationToken cancellationToken)
    {
        if (note.Length > 200)
        {
            throw new ArgumentException("A note is at most 200 characters.", nameof(note));
        }
        var order = await db.Orders.FirstAsync(o => o.Id == id, cancellationToken);
        order.Note = note;
        await db.SaveChangesAsync(cancellationToken);
    }
}
