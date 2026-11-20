import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fastapi import HTTPException

import main
from main import LaundryRequestHandler, MySQLConnection, initialize_database


class LaundryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.sqlite3"
        initialize_database(database_path)
        handler = type(
            "TestLaundryRequestHandler",
            (LaundryRequestHandler,),
            {"database_path": database_path},
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        status, session = self.request(
            "POST",
            "/api/auth/signup",
            {
                "fullName": "Test Owner",
                "email": "owner@example.com",
                "password": "test-password-123",
            },
            authenticated=False,
        )
        self.assertEqual(status, 201)
        self.token = session["token"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        self.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        authenticated: bool = True,
    ):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        token = getattr(self, "token", None)
        if authenticated and token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_signup_login_and_password_hashing(self) -> None:
        status, response = self.request(
            "POST",
            "/api/auth/signup",
            {
                "fullName": "FreshFold Owner",
                "email": "new@example.com",
                "password": "secure-pass-123",
            },
            authenticated=False,
        )
        self.assertEqual(status, 201)
        self.assertEqual(response["user"]["email"], "new@example.com")
        self.assertTrue(response["token"])

        connection = sqlite3.connect(self.temp_dir.name + "/test.sqlite3")
        try:
            stored_hash = connection.execute(
                "SELECT password_hash FROM freshfold_users WHERE email = ?",
                ("new@example.com",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotEqual(stored_hash, "secure-pass-123")
        self.assertTrue(stored_hash.startswith("pbkdf2_sha256$"))

        status, duplicate = self.request(
            "POST",
            "/api/auth/signup",
            {
                "fullName": "Duplicate Owner",
                "email": "NEW@example.com",
                "password": "secure-pass-456",
            },
            authenticated=False,
        )
        self.assertEqual(status, 409)
        self.assertIn("already exists", duplicate["error"])

        status, login = self.request(
            "POST",
            "/api/auth/login",
            {"email": "NEW@example.com", "password": "secure-pass-123"},
            authenticated=False,
        )
        self.assertEqual(status, 200)
        self.assertEqual(login["user"]["id"], response["user"]["id"])

        status, invalid = self.request(
            "POST",
            "/api/auth/login",
            {"email": "new@example.com", "password": "wrong-password"},
            authenticated=False,
        )
        self.assertEqual(status, 401)
        self.assertIn("Invalid email or password", invalid["error"])

    def test_orders_require_a_valid_session_and_logout_revokes_it(self) -> None:
        status, response = self.request("GET", "/api/orders", authenticated=False)
        self.assertEqual(status, 401)

        status, response = self.request("GET", "/api/orders")
        self.assertEqual(status, 200)

        status, logout = self.request("POST", "/api/auth/logout", {})
        self.assertEqual(status, 200)
        self.assertIn("Signed out", logout["message"])

        status, response = self.request("GET", "/api/orders")
        self.assertEqual(status, 401)

    def test_create_read_update_and_delete_order(self) -> None:
        payload = {
            "customerName": "  Alex Santos ",
            "phone": "09170000000",
            "serviceType": "Wash & Iron",
            "weightKg": 2.5,
            "price": 0,
            "dueDate": "2026-11-12",
            "status": "Received",
        }
        status, created = self.request("POST", "/api/orders", payload)
        self.assertEqual(status, 201)
        self.assertEqual(created["customerName"], "Alex Santos")
        self.assertEqual(created["price"], 162.5)

        order_id = created["id"]
        status, listed = self.request("GET", "/api/orders")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], order_id)

        payload["status"] = "Washing"
        status, updated = self.request("PUT", f"/api/orders/{order_id}", payload)
        self.assertEqual(status, 200)
        self.assertEqual(updated["status"], "Washing")
        self.assertEqual(updated["id"], order_id)

        status, deleted = self.request("DELETE", f"/api/orders/{order_id}")
        self.assertEqual(status, 200)
        self.assertIn("deleted", deleted["message"])
        status, missing = self.request("GET", f"/api/orders/{order_id}")
        self.assertEqual(status, 404)
        self.assertIn("not found", missing["error"])

    def test_new_order_defaults_to_received(self) -> None:
        status, created = self.request(
            "POST",
            "/api/orders",
            {
                "customerName": "New Order",
                "phone": "",
                "serviceType": "Wash & Fold",
                "weightKg": 1,
                "dueDate": "2026-11-14",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["status"], "Received")

    def test_rejects_invalid_order_data(self) -> None:
        status, response = self.request(
            "POST",
            "/api/orders",
            {
                "customerName": "",
                "serviceType": "Wash & Fold",
                "weightKg": -1,
                "status": "Unknown",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("Customer name", response["error"])

    def test_rejects_non_numeric_phone_number(self) -> None:
        status, response = self.request(
            "POST",
            "/api/orders",
            {
                "customerName": "Alex Santos",
                "phone": "0917abc1234",
                "serviceType": "Wash & Fold",
                "weightKg": 1,
                "status": "Received",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("Phone number can contain numbers only", response["error"])

    def test_mysql_connection_translates_query_parameters(self) -> None:
        class Cursor:
            query = ""
            parameters = None

            def execute(self, query, parameters):
                self.query = query
                self.parameters = parameters

        class Connection:
            cursor_instance = Cursor()

            def cursor(self, dictionary=False):
                self.assert_dictionary = dictionary
                return self.cursor_instance

        raw_connection = Connection()
        connection = MySQLConnection(raw_connection)

        connection.execute(
            "UPDATE laundry_orders SET status = :status WHERE id = :id",
            {"status": "Ready", "id": 12},
        )

        self.assertEqual(
            raw_connection.cursor_instance.query,
            "UPDATE laundry_orders SET status = %(status)s WHERE id = %(id)s",
        )
        self.assertEqual(
            raw_connection.cursor_instance.parameters, {"status": "Ready", "id": 12}
        )
        self.assertTrue(raw_connection.assert_dictionary)

    def test_fastapi_auth_endpoints_use_database_and_protect_orders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.multiple(
                main,
                DATABASE_ENGINE="sqlite",
                DATABASE_PATH=Path(temp_dir) / "fastapi.sqlite3",
            ):
                main.initialize_database()
                session = main.sign_up(
                    {
                        "fullName": "FastAPI Owner",
                        "email": "fastapi@example.com",
                        "password": "secure-api-password",
                    }
                )
                user = main.current_user(f"Bearer {session['token']}")
                self.assertEqual(main.list_orders(user), [])

                with self.assertRaises(HTTPException) as unauthorized:
                    main.current_user(None)
                self.assertEqual(unauthorized.exception.status_code, 401)

                with self.assertRaises(HTTPException) as invalid_login:
                    main.log_in(
                        {"email": "fastapi@example.com", "password": "wrong-password"}
                    )
                self.assertEqual(invalid_login.exception.status_code, 401)

                main.log_out(f"Bearer {session['token']}", _user=user)
                with self.assertRaises(HTTPException) as revoked:
                    main.current_user(f"Bearer {session['token']}")
                self.assertEqual(revoked.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
