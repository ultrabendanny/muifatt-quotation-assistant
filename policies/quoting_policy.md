# Quoting Policy (EXAMPLE DATA ONLY)

> Example policy for a training project. Figures are invented and not real prices.

## 1. Who approves
- Every quote produced by the assistant is a **draft**. A human must approve it. The assistant never sends a quote to a customer.

## 2. Price floor and margin
- The minimum margin is **10% over unit cost** for every SKU (`price_rules.min_margin_pct`).
- The **price floor** is `unit_cost x (1 + min_margin_pct / 100)`, stored in `price_rules.price_floor`.
- **Never quote below the price floor.** If a customer asks for a price below the floor, decline that price and offer the floor price or the list price.
- Never reveal `unit_cost` or the margin in anything addressed to a customer.

## 3. Default price and volume break
- Default quote price is the **list price** (`price_rules.list_price`).
- A volume break applies when the requested quantity is at least `price_rules.volume_break_qty`: the unit price becomes `list_price x (1 - volume_discount_pct / 100)`, rounded to 2 decimals, and still never below the price floor.
- Example: EXAMPLE-RESIN-001 lists at MYR 5.00 per KG. At 2000 KG or more the volume break is 7%, so MYR 4.65 per KG.

## 4. Units of measure
- 1 MT = 1000 KG. Prices stored per KG are multiplied by 1000 when a customer asks in MT.
- ROLL is a separate unit for film SKUs and is not converted.

## 5. Currency and validity
- Currency is MYR unless the enquiry clearly says otherwise.
- A quote is valid for **14 days** from the quote date.

## 6. Extra discounts
- No discount beyond the volume break may be offered by the assistant. Any other discount request must be sent to a human manager.
