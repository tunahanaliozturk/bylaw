namespace Orders;

public sealed class Order
{
    public int Id { get; set; }
    public required string Customer { get; set; }
    public decimal Total { get; set; }
    public DateTimeOffset PlacedAt { get; set; }
}
