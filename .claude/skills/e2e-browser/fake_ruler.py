"""Minimal Mimir Ruler stub: accepts rule-group POSTs, records headers/bodies."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = "/tmp/fake_ruler_requests.jsonl"


class Handler(BaseHTTPRequestHandler):
    def _record(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else ""
        with open(LOG, "a") as f:
            f.write(
                json.dumps(
                    {
                        "method": self.command,
                        "path": self.path,
                        "x_scope_orgid": self.headers.get("X-Scope-OrgID"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": body,
                    }
                )
                + "\n"
            )

    def do_POST(self):
        self._record()
        self.send_response(202)
        self.end_headers()

    def do_GET(self):
        self._record()
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        self._record()
        self.send_response(202)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 18080), Handler).serve_forever()
