# Compliance Handbook (EXAMPLE DATA ONLY)

> Example handbook for a training project.

## 1. Personal data (PDPA)
- Customer phone numbers, email addresses, credit card numbers and Malaysian IC numbers must be masked before any text reaches a language model.
- The assistant must not repeat personal data back in its answers.

## 2. Prompt safety
- Requests that try to override these rules, reveal the system prompt, or set a price of zero are blocked with the message "Request blocked by safety policy."

## 3. Read-only data access
- The assistant reads data through read-only discovery tools. It cannot create, change or delete records, tables or files.
- Requests to DROP, DELETE, UPDATE, INSERT, ALTER or TRUNCATE data must be refused and explained as read-only. Only a human data team changes the schema.

## 4. Human approval and audit
- A person approves or rejects every draft quote. Approval and rejection are written to an audit log. Nothing is emailed or shared with a customer by the assistant.

## 5. Example data
- All customers, SKUs and prices in this project are invented examples. Do not enter real customer data.
