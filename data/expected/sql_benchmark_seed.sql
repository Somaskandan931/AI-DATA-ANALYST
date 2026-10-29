
-- M2 SQL benchmark: deterministic sample database
-- Contains NULLs, duplicate values, joins, and boundary amounts.

DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    amount REAL NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

INSERT INTO customers (customer_id, name, city) VALUES
    (1, 'Asha', 'Chennai'),
    (2, 'Ravi', 'Bengaluru'),
    (3, 'Mina', 'Chennai'),
    (4, 'Asha', NULL),
    (5, 'Kiran', 'Mumbai');

INSERT INTO orders (order_id, customer_id, amount) VALUES
    (101, 1, 100.00),
    (102, 1, 150.00),
    (103, 2, 200.00),
    (104, 3, 100.00),
    (105, 4, 50.00);
