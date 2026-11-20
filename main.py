import base64
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import AsyncGenerator, Generator, Mapping
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import mysql.connector
from mysql.connector import Error as MySQLDatabaseError
from mysql.connector import IntegrityError as MySQLIntegrityError


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = Path(
    os.environ.get("LAUNDRY_DB_PATH", ROOT / "database" / "laundry.db")
)
DATABASE_ENGINE = os.environ.get("LAUNDRY_DB_ENGINE", "sqlite").lower()
MYSQL_CONFIG = {
    "host": os.environ.get("LAUNDRY_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("LAUNDRY_DB_PORT", "3306")),
    "user": os.environ.get("LAUNDRY_DB_USER", "root"),
    "password": os.environ.get("LAUNDRY_DB_PASSWORD", ""),
    "database": os.environ.get("LAUNDRY_DB_NAME", "laundrytracker"),
}
DATABASE_ERRORS = (sqlite3.Error, MySQLDatabaseError)
DATABASE_INTEGRITY_ERRORS = (sqlite3.IntegrityError, MySQLIntegrityError)
SERVICE_RATES = {"Wash & Fold": 45, "Wash & Iron": 65, "Dry Cleaning": 120}
ORDER_STATUSES = {"Received", "Washing", "Ready", "Completed"}
LOGGER = logging.getLogger(__name__)
PASSWORD_ITERATIONS = 600_000
SESSION_DURATION = timedelta(hours=12)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RequestError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@contextmanager
def database(path: Path | None = None) -> Generator[object, None, None]:
    if path is None and DATABASE_ENGINE == "mysql":
        raw_connection = mysql.connector.connect(**MYSQL_CONFIG)
        connection = MySQLConnection(raw_connection)
    elif path is not None or DATABASE_ENGINE == "sqlite":
        sqlite_path = path or DATABASE_PATH
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_connection = sqlite3.connect(sqlite_path)
        sqlite_connection.row_factory = sqlite3.Row
        connection = sqlite_connection
    else:
        raise RuntimeError(
            "LAUNDRY_DB_ENGINE must be set to either 'mysql' or 'sqlite'."
        )
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class MySQLConnection:
    def __init__(self, connection: mysql.connector.MySQLConnection) -> None:
        self._connection = connection

    def execute(
        self, query: str, parameters: dict[str, object] | tuple[object, ...] = ()
    ):
        cursor = self._connection.cursor(dictionary=True)
        query = re.sub(r":([A-Za-z_]\w*)", r"%(\1)s", query)
        query = query.replace("?", "%s")
        cursor.execute(query, parameters)
        return cursor

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def initialize_database(path: Path | None = None) -> None:
    with database(path) as connection:
        if path is None and DATABASE_ENGINE == "mysql":
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS laundry_orders (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    customer_name VARCHAR(120) NOT NULL,
                    phone VARCHAR(40) NOT NULL DEFAULT '',
                    service_type VARCHAR(40) NOT NULL,
                    weight_kg DECIMAL(7, 2) NOT NULL,
                    price DECIMAL(10, 2) NOT NULL,
                    due_date VARCHAR(10) NOT NULL DEFAULT '',
                    status VARCHAR(20) NOT NULL,
                    created_at VARCHAR(40) NOT NULL,
                    updated_at VARCHAR(40) NOT NULL
                )
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS laundry_orders (
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
                )
                """
            )

        if path is None and DATABASE_ENGINE == "mysql":
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS freshfold_users (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    full_name VARCHAR(120) NOT NULL,
                    email VARCHAR(254) NOT NULL UNIQUE,
                    password_hash VARCHAR(256) NOT NULL,
                    created_at VARCHAR(40) NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS freshfold_sessions (
                    token_hash CHAR(64) PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    expires_at VARCHAR(40) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES freshfold_users(id) ON DELETE CASCADE
                )
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS freshfold_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS freshfold_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES freshfold_users(id) ON DELETE CASCADE
                )
                """
            )


def validate_auth_payload(payload: object, require_name: bool) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise RequestError("The request body must be a JSON object.")

    email = payload.get("email")
    if not isinstance(email, str) or len(email.strip()) > 254:
        raise RequestError("Enter a valid email address.")
    normalized_email = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized_email):
        raise RequestError("Enter a valid email address.")

    password = payload.get("password")
    if not isinstance(password, str) or not password or len(password) > 128:
        raise RequestError("Password must contain 1 to 128 characters.")
    if require_name and len(password) < 8:
        raise RequestError("Password must contain at least 8 characters.")

    result = {"email": normalized_email, "password": password}
    if require_name:
        full_name = payload.get("fullName")
        if not isinstance(full_name, str) or not full_name.strip():
            raise RequestError("Full name is required.")
        if len(full_name.strip()) > 120:
            raise RequestError("Full name must be 120 characters or fewer.")
        result["full_name"] = full_name.strip()
    return result


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt_text}${digest_text}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$")
        iterations = int(iterations_text)
        if algorithm != "pbkdf2_sha256" or not 100_000 <= iterations <= 1_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected_digest = base64.urlsafe_b64decode(
            digest_text + "=" * (-len(digest_text) % 4)
        )
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual_digest, expected_digest)


DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


def serialize_user(row: Mapping[str, object] | sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "fullName": row["full_name"],
        "email": row["email"],
    }


def create_session(
    connection: object, user_id: int
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    expires_at = (now + SESSION_DURATION).isoformat(timespec="seconds")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    connection.execute(
        "DELETE FROM freshfold_sessions WHERE expires_at <= ?", (now.isoformat(),)
    )
    connection.execute(
        """
        INSERT INTO freshfold_sessions (token_hash, user_id, expires_at)
        VALUES (?, ?, ?)
        """,
        (token_hash, user_id, expires_at),
    )
    return token, expires_at


def register_user(payload: object, path: Path | None = None) -> dict[str, object]:
    account = validate_auth_payload(payload, require_name=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with database(path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO freshfold_users (full_name, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    account["full_name"],
                    account["email"],
                    hash_password(account["password"]),
                    now,
                ),
            )
            user = connection.execute(
                "SELECT * FROM freshfold_users WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            token, expires_at = create_session(connection, int(user["id"]))
    except DATABASE_INTEGRITY_ERRORS as error:
        raise RequestError("An account with this email already exists.", 409) from error
    return {"token": token, "expiresAt": expires_at, "user": serialize_user(user)}


def authenticate_user(payload: object, path: Path | None = None) -> dict[str, object]:
    account = validate_auth_payload(payload, require_name=False)
    with database(path) as connection:
        user = connection.execute(
            "SELECT * FROM freshfold_users WHERE email = ?", (account["email"],)
        ).fetchone()
        password_hash = (
            str(user["password_hash"]) if user is not None else DUMMY_PASSWORD_HASH
        )
        password_matches = verify_password(account["password"], password_hash)
        if user is None or not password_matches:
            raise RequestError("Invalid email or password.", 401)
        token, expires_at = create_session(connection, int(user["id"]))
    return {"token": token, "expiresAt": expires_at, "user": serialize_user(user)}


def authenticated_user(
    token: str, path: Path | None = None
) -> dict[str, object] | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with database(path) as connection:
        row = connection.execute(
            """
            SELECT freshfold_users.*
            FROM freshfold_sessions
            JOIN freshfold_users ON freshfold_users.id = freshfold_sessions.user_id
            WHERE freshfold_sessions.token_hash = ?
                AND freshfold_sessions.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
    return serialize_user(row) if row is not None else None


def revoke_session(token: str, path: Path | None = None) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with database(path) as connection:
        connection.execute(
            "DELETE FROM freshfold_sessions WHERE token_hash = ?", (token_hash,)
        )


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def current_user(authorization: str | None = Header(default=None)) -> dict[str, object]:
    token = bearer_token(authorization)
    user = authenticated_user(token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Session is invalid or expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def serialize_order(row: Mapping[str, object] | sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "customerName": row["customer_name"],
        "phone": row["phone"],
        "serviceType": row["service_type"],
        "weightKg": float(row["weight_kg"]),
        "price": float(row["price"]),
        "dueDate": row["due_date"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def validate_order(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RequestError("The request body must be a JSON object.")

    customer_name = payload.get("customerName")
    if not isinstance(customer_name, str) or not customer_name.strip():
        raise RequestError("Customer name is required.")
    if len(customer_name.strip()) > 120:
        raise RequestError("Customer name must be 120 characters or fewer.")

    phone = payload.get("phone", "")
    if not isinstance(phone, str) or len(phone) > 40:
        raise RequestError("Phone number must be 40 characters or fewer.")
    if phone and (not phone.isascii() or not phone.isdigit()):
        raise RequestError("Phone number can contain numbers only.")

    service_type = payload.get("serviceType")
    if not isinstance(service_type, str) or service_type not in SERVICE_RATES:
        raise RequestError("Choose a valid laundry service.")

    weight_value = payload.get("weightKg")
    if isinstance(weight_value, bool) or not isinstance(weight_value, (int, float)):
        raise RequestError("Weight must be a number.")
    weight = float(weight_value)
    if not math.isfinite(weight) or weight <= 0 or weight > 200:
        raise RequestError("Weight must be greater than 0 and no more than 200 kg.")

    status = payload.get("status", "Received")
    if not isinstance(status, str) or status not in ORDER_STATUSES:
        raise RequestError("Choose a valid order status.")

    due_date = payload.get("dueDate", "")
    if not isinstance(due_date, str):
        raise RequestError("Due date must be a date string.")
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError as error:
            raise RequestError("Due date must use YYYY-MM-DD format.") from error

    return {
        "customer_name": customer_name.strip(),
        "phone": phone.strip(),
        "service_type": service_type,
        "weight_kg": round(weight, 2),
        "price": round(weight * SERVICE_RATES[service_type], 2),
        "due_date": due_date,
        "status": status,
    }


class LaundryRequestHandler(BaseHTTPRequestHandler):
    database_path: Path | None = None

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        path_parts = self._path_parts()
        try:
            if path_parts == ["api", "health"]:
                self._send_json(200, {"status": "ok"})
            elif path_parts == ["api", "orders"]:
                self._require_authenticated()
                with database(self.database_path) as connection:
                    rows = connection.execute(
                        "SELECT * FROM laundry_orders ORDER BY id DESC"
                    ).fetchall()
                self._send_json(200, [serialize_order(row) for row in rows])
            elif len(path_parts) == 3 and path_parts[:2] == ["api", "orders"]:
                self._require_authenticated()
                order_id = self._order_id(path_parts[2])
                with database(self.database_path) as connection:
                    row = connection.execute(
                        "SELECT * FROM laundry_orders WHERE id = ?", (order_id,)
                    ).fetchone()
                if row is None:
                    raise RequestError("Laundry order not found.", 404)
                self._send_json(200, serialize_order(row))
            else:
                raise RequestError("Endpoint not found.", 404)
        except RequestError as error:
            self._send_error(error)
        except DATABASE_ERRORS as error:
            self._database_error(error)

    def do_POST(self) -> None:
        path_parts = self._path_parts()
        if path_parts == ["api", "auth", "signup"]:
            try:
                self._send_json(201, register_user(self._read_json(), self.database_path))
            except RequestError as error:
                self._send_error(error)
            except DATABASE_ERRORS as error:
                self._database_error(error)
            return
        if path_parts == ["api", "auth", "login"]:
            try:
                self._send_json(200, authenticate_user(self._read_json(), self.database_path))
            except RequestError as error:
                self._send_error(error)
            except DATABASE_ERRORS as error:
                self._database_error(error)
            return
        if path_parts == ["api", "auth", "logout"]:
            try:
                token = self._require_authenticated()
                revoke_session(token, self.database_path)
                self._send_json(200, {"message": "Signed out."})
            except RequestError as error:
                self._send_error(error)
            except DATABASE_ERRORS as error:
                self._database_error(error)
            return
        if path_parts != ["api", "orders"]:
            self._send_json(404, {"error": "Endpoint not found."})
            return
        try:
            self._require_authenticated()
            order = validate_order(self._read_json())
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with database(self.database_path) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO laundry_orders (
                        customer_name, phone, service_type, weight_kg, price,
                        due_date, status, created_at, updated_at
                    ) VALUES (
                        :customer_name, :phone, :service_type, :weight_kg, :price,
                        :due_date, :status, :created_at, :updated_at
                    )
                    """,
                    {**order, "created_at": now, "updated_at": now},
                )
                row = connection.execute(
                    "SELECT * FROM laundry_orders WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            self._send_json(201, serialize_order(row))
        except RequestError as error:
            self._send_error(error)
        except DATABASE_ERRORS as error:
            self._database_error(error)

    def do_PUT(self) -> None:
        path_parts = self._path_parts()
        if len(path_parts) != 3 or path_parts[:2] != ["api", "orders"]:
            self._send_json(404, {"error": "Endpoint not found."})
            return
        try:
            self._require_authenticated()
            order_id = self._order_id(path_parts[2])
            order = validate_order(self._read_json())
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with database(self.database_path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE laundry_orders
                    SET customer_name = :customer_name, phone = :phone,
                        service_type = :service_type, weight_kg = :weight_kg,
                        price = :price, due_date = :due_date, status = :status,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {**order, "updated_at": now, "id": order_id},
                )
                if cursor.rowcount == 0:
                    raise RequestError("Laundry order not found.", 404)
                row = connection.execute(
                    "SELECT * FROM laundry_orders WHERE id = ?", (order_id,)
                ).fetchone()
            self._send_json(200, serialize_order(row))
        except RequestError as error:
            self._send_error(error)
        except DATABASE_ERRORS as error:
            self._database_error(error)

    def do_DELETE(self) -> None:
        path_parts = self._path_parts()
        if len(path_parts) != 3 or path_parts[:2] != ["api", "orders"]:
            self._send_json(404, {"error": "Endpoint not found."})
            return
        try:
            self._require_authenticated()
            order_id = self._order_id(path_parts[2])
            with database(self.database_path) as connection:
                cursor = connection.execute(
                    "DELETE FROM laundry_orders WHERE id = ?", (order_id,)
                )
            if cursor.rowcount == 0:
                raise RequestError("Laundry order not found.", 404)
            self._send_json(200, {"message": "Laundry order deleted."})
        except RequestError as error:
            self._send_error(error)
        except DATABASE_ERRORS as error:
            self._database_error(error)

    def _path_parts(self) -> list[str]:
        return [part for part in urlparse(self.path).path.strip("/").split("/") if part]

    def _require_authenticated(self) -> str:
        authorization = self.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            raise RequestError("Authentication is required.", 401)
        token = token.strip()
        if authenticated_user(token, self.database_path) is None:
            raise RequestError("Session is invalid or expired. Please sign in again.", 401)
        return token

    def _read_json(self) -> object:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise RequestError("Invalid Content-Length header.") from error
        if length > 1_000_000:
            raise RequestError("Request body is too large.", 413)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestError("Request body must contain valid JSON.") from error

    @staticmethod
    def _order_id(value: str) -> int:
        try:
            order_id = int(value)
        except ValueError as error:
            raise RequestError("Order ID must be an integer.", 400) from error
        if order_id <= 0:
            raise RequestError("Order ID must be a positive integer.", 400)
        return order_id

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, error: RequestError) -> None:
        self._send_json(error.status, {"error": str(error)})

    def _database_error(self, error: Exception) -> None:
        print(f"Database error: {error}", flush=True)
        self._send_json(500, {"error": "Database operation failed."})


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(MySQLDatabaseError)
@app.exception_handler(sqlite3.Error)
async def database_exception_handler(
    _request: Request, error: Exception
) -> JSONResponse:
    LOGGER.exception("Database operation failed for %s: %s", _request.url.path, error)
    return JSONResponse(
        status_code=500, content={"detail": "Database operation failed."}
    )


@app.get("/")
def get_api_info() -> dict[str, object]:
    return {
        "name": "FreshFold Laundry Tracker API",
        "status": "running",
        "health": "/api/health",
        "docs": "/docs",
        "orders": "/api/orders",
    }


@app.get("/api/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/signup", status_code=201)
def sign_up(payload: dict[str, object]) -> dict[str, object]:
    try:
        return register_user(payload)
    except RequestError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@app.post("/api/auth/login")
def log_in(payload: dict[str, object]) -> dict[str, object]:
    try:
        return authenticate_user(payload)
    except RequestError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@app.post("/api/auth/logout")
def log_out(
    authorization: str | None = Header(default=None),
    _user: dict[str, object] = Depends(current_user),
) -> dict[str, str]:
    revoke_session(bearer_token(authorization))
    return {"message": "Signed out."}


@app.get("/api/auth/me")
def get_current_user(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return user


@app.get("/api/orders")
def list_orders(
    _user: dict[str, object] = Depends(current_user),
) -> list[dict[str, object]]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM laundry_orders ORDER BY id DESC"
        ).fetchall()
    return [serialize_order(row) for row in rows]


@app.get("/api/orders/{order_id}")
def get_order(
    order_id: int, _user: dict[str, object] = Depends(current_user)
) -> dict[str, object]:
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM laundry_orders WHERE id = ?", (order_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Laundry order not found.")
    return serialize_order(row)


@app.post("/api/orders")
def create_order(
    payload: dict[str, object], _user: dict[str, object] = Depends(current_user)
) -> dict[str, object]:
    try:
        order = validate_order(payload)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with database() as connection:
            cursor = connection.execute(
                """
                INSERT INTO laundry_orders (
                    customer_name, phone, service_type, weight_kg, price,
                    due_date, status, created_at, updated_at
                ) VALUES (
                    :customer_name, :phone, :service_type, :weight_kg, :price,
                    :due_date, :status, :created_at, :updated_at
                )
                """,
                {**order, "created_at": now, "updated_at": now},
            )
            row = connection.execute(
                "SELECT * FROM laundry_orders WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return serialize_order(row)
    except RequestError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@app.put("/api/orders/{order_id}")
def update_order(
    order_id: int,
    payload: dict[str, object],
    _user: dict[str, object] = Depends(current_user),
) -> dict[str, object]:
    try:
        order = validate_order(payload)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with database() as connection:
            cursor = connection.execute(
                """
                UPDATE laundry_orders
                SET customer_name = :customer_name, phone = :phone,
                    service_type = :service_type, weight_kg = :weight_kg,
                    price = :price, due_date = :due_date, status = :status,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {**order, "updated_at": now, "id": order_id},
            )
            if cursor.rowcount == 0:
                raise RequestError("Laundry order not found.", 404)
            row = connection.execute(
                "SELECT * FROM laundry_orders WHERE id = ?", (order_id,)
            ).fetchone()
        return serialize_order(row)
    except RequestError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@app.delete("/api/orders/{order_id}")
def delete_order(
    order_id: int, _user: dict[str, object] = Depends(current_user)
) -> dict[str, str]:
    try:
        with database() as connection:
            cursor = connection.execute(
                "DELETE FROM laundry_orders WHERE id = ?", (order_id,)
            )
        if cursor.rowcount == 0:
            raise RequestError("Laundry order not found.", 404)
        return {"message": "Laundry order deleted."}
    except RequestError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


def main() -> None:
    initialize_database()
    server = ThreadingHTTPServer(("0.0.0.0", 5000), LaundryRequestHandler)
    print("Laundry Tracker API listening on http://localhost:5000", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Laundry Tracker API.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()