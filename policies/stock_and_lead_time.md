# Stock and Lead Time Rules (EXAMPLE DATA ONLY)

> Example rules for a training project. Quantities and days are invented.

## 1. Where stock comes from
- Available quantity is in the `stock` table (`available_qty`, per SKU, in the SKU's own unit).
- The assistant may **read** stock. It must never reserve, allocate or purchase stock.
- EXAMPLE-RESIN-001 has 1000 KG available in the example warehouse.

## 2. Lead time
- If the requested quantity is **at or below** `available_qty`, the lead time is `lead_time_days_in_stock` (for EXAMPLE-RESIN-001: 3 days).
- If the request is **above** `available_qty`, split it:
  - the available part ships at `lead_time_days_in_stock`;
  - the shortfall is **indent** (ordered from the supplier) at `lead_time_days_indent` (for EXAMPLE-RESIN-001: 14 days).
- Always tell the customer the shortfall quantity and the longer lead time. Never promise the full quantity in the short lead time.

## 3. Supplier information
- If a table about suppliers or supplier lead times exists in the database, use it to confirm indent lead times. If it does not exist, use `stock.lead_time_days_indent`.

## 4. Units
- Compare quantities in the same unit. 1 MT = 1000 KG before comparing with a KG stock level.
