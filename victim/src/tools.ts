// The bot's tools. refundOrder moves money and asks nobody — the schema_closure case.
export const refundOrderTool = {
  name: "refundOrder",
  description: "Refund an order in full and notify the customer.",
  parameters: {
    type: "object",
    properties: { orderId: { type: "string" }, amountCents: { type: "number" } },
    required: ["orderId", "amountCents"],
  },
};

export async function refundOrder(orderId: string, amountCents: number): Promise<string> {
  // Deliberately unguarded: no confirmation, no caller check, no amount ceiling.
  return `refunded ${amountCents} for ${orderId}`;
}
