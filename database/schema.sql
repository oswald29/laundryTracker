BEGIN TRANSACTION;
CREATE TABLE freshfold_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES freshfold_users(id) ON DELETE CASCADE
                );
CREATE TABLE freshfold_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
CREATE TABLE laundry_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    service_type TEXT NOT NULL,
                    weight_kg REAL NOT NULL,
                    price REAL NOT NULL,
                    due_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
DELETE FROM "sqlite_sequence";
COMMIT;
