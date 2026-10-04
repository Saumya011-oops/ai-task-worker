"""Read-only ERP JSON API tools (httpx). Logs in itself and caches the session cookie."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from agent.types import Observation
from tools._util import clip, fail, ok, schema

load_dotenv()


class ErpClient:
    def __init__(self) -> None:
        self.cookies: httpx.Cookies | None = None

    def _base(self) -> str:
        return os.getenv("SANDBOX_URL", "http://localhost:8000").rstrip("/")

    def _login(self) -> bool:
        r = httpx.post(self._base() + "/erp/login", timeout=10, follow_redirects=False,
                       data={"email": os.getenv("ERP_USER", ""), "password": os.getenv("ERP_PASSWORD", "")})
        if r.status_code in (301, 302, 303, 307) and "erp_session" in r.cookies:
            self.cookies = r.cookies
            return True
        return False

    def get(self, path: str, params: dict[str, Any] | None = None) -> Observation:
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            for attempt in (1, 2):
                if self.cookies is None and not self._login():
                    return fail("auth", "ERP login failed (check ERP_USER/ERP_PASSWORD)")
                r = httpx.get(self._base() + path, params=params, cookies=self.cookies, timeout=10, follow_redirects=False)
                if r.status_code == 401 or 300 <= r.status_code < 400:
                    self.cookies = None  # expired -> re-login once
                    if attempt == 2:
                        return fail("auth", "ERP session rejected after re-login")
                    continue
                if r.status_code >= 500:
                    return fail("transient", f"ERP API HTTP {r.status_code}")
                if r.status_code == 404:
                    return fail("not_found", "ERP API 404")
                if r.status_code >= 400:
                    return fail("fatal", f"ERP API HTTP {r.status_code}: {r.text[:200]}")
                return ok(clip(json.dumps(r.json(), separators=(",", ":")), 12000))
            return fail("auth", "ERP auth failed")
        except (httpx.TimeoutException, httpx.TransportError) as e:
            return fail("transient", f"ERP API network error: {e}")
        except Exception as e:
            return fail("fatal", f"{type(e).__name__}: {e}")


CLIENT = ErpClient()


class _Tool:
    name = ""
    description = ""
    json_schema: dict[str, Any] = {}

    def run(self, **args: Any) -> Observation:  # pragma: no cover
        raise NotImplementedError


class ErpListBills(_Tool):
    name = "erp_list_bills"
    snapshot = True  # verifier dumps snapshot tools (no-arg call) as ground truth
    description = ("Query the ERP bills JSON API (read-only). All filters optional and AND-ed; dates are ISO YYYY-MM-DD "
                   "(due_from/due_to inclusive). Returns a JSON list of bill records.")
    json_schema = schema({
        "vendor_id": {"type": "string"}, "invoice_number": {"type": "string"},
        "status": {"type": "string"}, "due_from": {"type": "string"}, "due_to": {"type": "string"},
    })

    def run(self, **args: Any) -> Observation:
        keys = ("vendor_id", "invoice_number", "status", "due_from", "due_to")
        return CLIENT.get("/erp/api/bills", {k: args.get(k) for k in keys})


class ErpListVendors(_Tool):
    name = "erp_list_vendors"
    snapshot = True  # verifier dumps snapshot tools (no-arg call) as ground truth
    description = "List all vendors from the ERP JSON API (read-only): id, name, email, bank account."
    json_schema = schema({})

    def run(self, **_: Any) -> Observation:
        return CLIENT.get("/erp/api/vendors")


ERP_TOOLS: list[_Tool] = [ErpListBills(), ErpListVendors()]
