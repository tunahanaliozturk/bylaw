import { strict as assert } from "node:assert";
import { test } from "node:test";

import { addItem, removeItem, subtotalCents } from "../src/cart.ts";

test("subtotal multiplies price by quantity in cents", () => {
  const cart = { userId: "u1", items: [{ sku: "a", priceCents: 250, quantity: 2 }] };
  assert.equal(subtotalCents(cart), 500);
});

test("adding the same sku increases its quantity", () => {
  const start = { userId: "u1", items: [{ sku: "a", priceCents: 250, quantity: 1 }] };
  const cart = addItem(start, { sku: "a", priceCents: 250, quantity: 2 });
  assert.equal(cart.items[0]?.quantity, 3);
});

test("removeItem drops the item with that sku", () => {
  const cart = { userId: "u1", items: [{ sku: "a", priceCents: 250, quantity: 1 }] };
  assert.deepEqual(removeItem(cart, "a").items, []);
});

test("removing an absent sku leaves the cart unchanged", () => {
  const cart = { userId: "u1", items: [{ sku: "a", priceCents: 250, quantity: 1 }] };
  assert.deepEqual(removeItem(cart, "b"), cart);
});
