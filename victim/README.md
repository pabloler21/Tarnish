# victim — deliberately vulnerable support bot

Tarnish's gate target for M2/M3. **Never deploy this.** It exists to be attacked:

- `SYSTEM_PROMPT` tells the model attachments are authoritative.
- `refundOrder` has a side effect and no confirmation.
- Three untrusted-input surfaces: `handleMessage`, `ingestTicketAttachment`, `applyPolicyDoc`.

Tarnish never runs it. `HarnessTransport` reconstructs the prompt + tool schemas and attacks that.
