# MELTIES — Sales & Order Management System

A small-business cookie shop website with customer ordering, an admin dashboard, stock control, order management, and sales reports.

## Features
- Customer menu, cart, pickup/delivery checkout.
- Admin login and dashboard.
- Orders searchable by order ID/customer and filterable by status.
- Order status and payment status updates.
- Product CRUD and inventory tracking.
- Stock is deducted when an order is placed and restored once if cancelled.
- Sales chart and date-filtered reports.
- OMR currency (3 decimal places).

## Requirements
- Python 3.10+
- pip

## Run locally

### Windows (PowerShell)
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

The SQLite database `melties.db` is created automatically on first run, with sample products.

## Business logic
- Checkout validates customer details, order type, product availability, and stock.
- Prices and totals are calculated on the server. Each order item stores the product name and unit price at the time of purchase.
- Stock is deducted once when an order is placed.
- When an order is cancelled, its stock is restored once. Reopening a cancelled order checks stock before deducting again.
- Paid sales include only orders with both `Completed` and `Paid` statuses. Pending payment is shown separately.
- Cancelled orders are excluded from paid sales.

## Project structure
```text
MELTIES_Sales_System/
├── app.py
├── melties.db          # generated on first run
├── requirements.txt
├── README.md
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── login.html
│   ├── dashboard.html
│   ├── orders.html
│   ├── order_detail.html
│   ├── products.html
│   └── reports.html
└── static/
    ├── css/style.css
    └── js/shop.js
```

## Important notes
- This is a learning/demo project. It does not process online payments.
- Customer orders are stored in the local SQLite database.
- Use HTTPS, a production WSGI server, secure environment secrets, CSRF protection, rate limiting, and stronger admin account management before public deployment.
- Chart.js and Google Fonts are loaded from CDNs, so those visual resources need an internet connection.
