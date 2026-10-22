import os
import sqlite3
API_KEY = os.environ.get("REPORTS_API_KEY", "")

def get_orders_by_customer(db_path, customer_name):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM orders WHERE customer = ?"
        cursor.execute(query, (customer_name,))
        return cursor.fetchall()
    finally:
        conn.close()


def average_order_value(orders):
    if not orders:
        return 0
    total = 0
    for order in orders:
        total += order["amount"]
    return total / len(orders)


def find_customer(customers, email):
    for c in customers:
        if c["email"] == email:
            return c


def customer_display_name(customers, email):
    customer = find_customer(customers, email)
    return customer["first_name"] + " " + customer["last_name"]
