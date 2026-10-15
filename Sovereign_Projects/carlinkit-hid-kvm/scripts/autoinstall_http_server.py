#!/usr/bin/env python3
import http.server
import socketserver
import os
import sys

PORT = 8089
DIRECTORY = "/var/www/imac_autoinstall"

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")
        sys.stderr.flush()

if __name__ == "__main__":
    os.makedirs(DIRECTORY, exist_ok=True)
    with ReusableTCPServer(("", PORT), Handler) as httpd:
        sys.stderr.write(f"Autoinstall HTTP server running on port {PORT} serving {DIRECTORY}\n")
        sys.stderr.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
