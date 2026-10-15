import express, { type Request, type Response } from "express";

import type { Cart } from "./cart.ts";
import { logger } from "./logger.ts";
import { cancelOrder, findOrder, orderFromCart, saveOrder } from "./orders.ts";

export const app = express();
app.use(express.json());

function userId(req: Request): string | undefined {
  return req.header("x-user-id") ?? undefined;
}

app.get("/orders/:id", async (req: Request, res: Response) => {
  const order = await findOrder(req.params.id);
  if (!order || order.userId !== userId(req)) {
    res.status(404).end();
    return;
  }
  res.json(order);
});

app.post("/orders", async (req: Request, res: Response) => {
  const cart = req.body as Cart;
  const order = orderFromCart(crypto.randomUUID(), cart);
  await saveOrder(order);
  logger.info("order created", { orderId: order.id });
  res.status(201).json(order);
});

app.delete("/orders/:id", async (req: Request, res: Response) => {
  const order = await findOrder(req.params.id);
  if (!order) {
    res.status(404).end();
    return;
  }
  await cancelOrder(order.id);
  res.status(204).end();
});
