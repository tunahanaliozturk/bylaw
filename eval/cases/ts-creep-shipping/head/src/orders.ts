import type { Cart } from "./cart.ts";
import { subtotalCents } from "./cart.ts";

export interface Order {
  id: string;
  userId: string;
  totalCents: number;
}

const orders = new Map<string, Order>();

export async function saveOrder(order: Order): Promise<void> {
  orders.set(order.id, order);
}

export async function findOrder(id: string): Promise<Order | undefined> {
  return orders.get(id);
}

export function orderFromCart(id: string, cart: Cart): Order {
  return { id, userId: cart.userId, totalCents: subtotalCents(cart) + 499 };
}
