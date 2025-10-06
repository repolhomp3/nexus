#!/usr/bin/env python3
"""SQLite-backed MCP service for Nexus."""

import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

DB_PATH = os.getenv("SQLITE_DB_PATH", "/data/learning.db")


class SQLiteMCP:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_sample_data()

    def init_sample_data(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            sample_users = [
                ("Alice Johnson", "alice@example.com"),
                ("Bob Smith", "bob@example.com"),
            ]
            cursor.executemany("INSERT INTO users (name, email) VALUES (?, ?)", sample_users)

        conn.commit()
        conn.close()

    def handle_request(self, request):
        method = request.get("method")
        params = request.get("params", {})

        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "execute_query",
                        "description": "Execute a SQL query",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "SQL query to execute"}
                            },
                            "required": ["query"],
                        },
                    }
                ]
            }

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "execute_query":
                return self.execute_query(args["query"])

        return {"error": "Unknown method"}

    def execute_query(self, query):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(query)

            if query.strip().upper().startswith("SELECT"):
                results = [dict(row) for row in cursor.fetchall()]
                return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}

            conn.commit()
            return {"content": [{"type": "text", "text": f"Query executed. Rows affected: {cursor.rowcount}"}]}

        except Exception as exc:  # pylint: disable=broad-except
            return {"error": str(exc)}
        finally:
            conn.close()


class MCPHandler(BaseHTTPRequestHandler):
    def __init__(self, mcp_server, *args, **kwargs):
        self.mcp_server = mcp_server
        super().__init__(*args, **kwargs)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
            response = self.mcp_server.handle_request(request)

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = SQLiteMCP()

    def handler(*args, **kwargs):
        MCPHandler(server, *args, **kwargs)

    httpd = HTTPServer(("0.0.0.0", 8000), handler)
    print("Database MCP Server running on port 8000")
    httpd.serve_forever()
