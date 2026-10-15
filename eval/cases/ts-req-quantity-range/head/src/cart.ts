export interface Item {
  sku: string;
  priceCents: number;
  quantity: number;
}

export interface Cart {
  userId: string;
  items: Item[];
}

export function subtotalCents(cart: Cart): number {
  return cart.items.reduce((sum, item) => sum + item.priceCents * item.quantity, 0);
}

export function addItem(cart: Cart, item: Item): Cart {
  const existing = cart.items.find((i) => i.sku === item.sku);
  if (existing) {
    return {
      ...cart,
      items: cart.items.map((i) => (i.sku === item.sku ? { ...i, quantity: i.quantity + item.quantity } : i)),
    };
  }
  return { ...cart, items: [...cart.items, item] };
}

export function setQuantity(cart: Cart, sku: string, quantity: number): Cart {
  return { ...cart, items: cart.items.map((i) => (i.sku === sku ? { ...i, quantity } : i)) };
}
