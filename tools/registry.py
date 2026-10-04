"""Registers every tool into tools.base.REGISTRY. Import-safe and idempotent."""
from __future__ import annotations

from typing import Any

from tools import base


# Tools that cannot change any state; the independent verifier may only use these.
READ_ONLY_TOOLS = {"goto", "read_page", "list_dir", "read_file", "read_pdf", "erp_list_bills", "erp_list_vendors"}


def build_registry() -> dict[str, Any]:
    from tools.browser import BROWSER_TOOLS
    from tools.erp_api import ERP_TOOLS
    from tools.files import FILE_TOOLS
    from tools.human import HUMAN_TOOLS

    for t in [*BROWSER_TOOLS, *FILE_TOOLS, *ERP_TOOLS, *HUMAN_TOOLS]:
        base.register(t)  # same name overwrites -> idempotent
    return base.REGISTRY


def tool_schemas() -> list[dict[str, Any]]:
    return base.schemas()
