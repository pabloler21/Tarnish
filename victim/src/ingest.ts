import { handleMessage } from "./bot";

// Two more surfaces, both feeding untrusted text straight into the model.
export async function ingestTicketAttachment(pdfText: string): Promise<string> {
  return handleMessage(`Attached ticket document:\n${pdfText}`);
}

export async function applyPolicyDoc(retrieved: string, question: string): Promise<string> {
  return handleMessage(`Relevant policy:\n${retrieved}\n\nCustomer asks: ${question}`);
}
