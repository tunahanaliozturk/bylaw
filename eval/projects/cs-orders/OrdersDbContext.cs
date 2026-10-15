using Microsoft.EntityFrameworkCore;

namespace Orders;

public sealed class OrdersDbContext(DbContextOptions<OrdersDbContext> options) : DbContext(options)
{
    public DbSet<Order> Orders => Set<Order>();
}
