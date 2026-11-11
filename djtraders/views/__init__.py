"""
The djtraders views, one module per entity:

  landing.py   - the app's home page
  customers.py - customer pages, their tabs and the customer login
  employees.py - employee pages, the dashboard charts and the employee login
  orders.py    - order pages and the shopping cart
  products.py  - product pages and the cart's autocomplete search
  suppliers.py - supplier pages and the supplier login
  agent.py     - the Ask tab: the assistant's answers and its confirmed changes
  access.py    - the rules about who may see or do what

urls.py imports these modules and routes each URL to a function in one of them.
"""
