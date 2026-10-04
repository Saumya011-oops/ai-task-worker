"""Filesystem tools restricted to the project workspace/ directory."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from agent.types import Observation
from tools._util import WORKSPACE, clip, fail, ok, schema


class PathEscape(Exception):
    pass


def _resolve(path: str) -> Path:
    """Resolve a path (relative to workspace/ or absolute) and ensure it stays inside workspace/."""
    root = WORKSPACE.resolve()
    path = path[len("workspace/"):] if path.startswith("workspace/") else path  # models often include the prefix
    p = Path(path)
    p = (p if p.is_absolute() else root / p).resolve()
    if p != root and root not in p.parents:
        raise PathEscape(f"Path '{path}' is outside the workspace directory")
    return p


def _guard(fn: Any) -> Observation:
    try:
        return fn()
    except PathEscape as e:
        return fail("validation", str(e))
    except FileNotFoundError as e:
        return fail("not_found", f"File not found: {e.filename or e}")
    except (IsADirectoryError, NotADirectoryError) as e:
        return fail("validation", f"Wrong path type: {e}")
    except Exception as e:
        return fail("fatal", f"{type(e).__name__}: {e}")


class _Tool:
    name = ""
    description = ""
    json_schema: dict[str, Any] = {}

    def run(self, **args: Any) -> Observation:  # pragma: no cover
        raise NotImplementedError


class ListDir(_Tool):
    name = "list_dir"
    description = "List files/folders in a workspace directory (default: workspace root)."
    json_schema = schema({"path": {"type": "string", "description": "Relative to workspace/"}})

    def run(self, path: str = ".", **_: Any) -> Observation:
        def go() -> Observation:
            p = _resolve(path or ".")
            if not p.exists():
                raise FileNotFoundError(path)
            items = sorted(p.iterdir())
            return ok("\n".join(f"{'d' if i.is_dir() else 'f'} {i.name}" + ("" if i.is_dir() else f" ({i.stat().st_size}B)")
                                for i in items) or "(empty)")
        return _guard(go)


class ReadFile(_Tool):
    name = "read_file"
    description = "Read a UTF-8 text file from the workspace."
    json_schema = schema({"path": {"type": "string"}}, ["path"])

    def run(self, path: str = "", **_: Any) -> Observation:
        return _guard(lambda: ok(clip(_resolve(path).read_text(encoding="utf-8", errors="replace"), 8000)))


class ReadPdf(_Tool):
    name = "read_pdf"
    description = "Extract the text of a PDF in the workspace (e.g. downloads/file.pdf)."
    json_schema = schema({"path": {"type": "string"}}, ["path"])

    def run(self, path: str = "", **_: Any) -> Observation:
        def go() -> Observation:
            from pypdf import PdfReader
            p = _resolve(path)
            if not p.exists():
                raise FileNotFoundError(path)
            try:
                text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages).strip()
            except Exception as e:
                return fail("validation", f"Could not parse PDF: {e}")
            return ok(clip(text, 8000)) if text else fail("validation", "PDF has no extractable text (scanned?)")
        return _guard(go)


class WriteFile(_Tool):
    name = "write_file"
    description = "Write text to a file in the workspace (creates folders; overwrites)."
    json_schema = schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])

    def run(self, path: str = "", content: str = "", **_: Any) -> Observation:
        def go() -> Observation:
            p = _resolve(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ok(f"wrote {p.relative_to(WORKSPACE.resolve())} ({len(content)} chars)")
        return _guard(go)


class WriteCsv(_Tool):
    name = "write_csv"
    description = "Write a CSV file in the workspace. rows = list of rows, each row a list of cell strings; the FIRST row is the header."
    json_schema = schema({"path": {"type": "string"},
                          "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                                   "description": "Rows as arrays of strings, header row first"}}, ["path", "rows"])

    def run(self, path: str = "", rows: list | None = None, **_: Any) -> Observation:
        def go() -> Observation:
            if not rows:
                return fail("validation", "rows must be a non-empty list")
            p = _resolve(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            buf = io.StringIO()
            w = csv.writer(buf)
            if isinstance(rows[0], dict):
                keys = list(rows[0].keys())
                w.writerow(keys)
                for r in rows:
                    w.writerow([r.get(k, "") for k in keys])
            else:
                w.writerows(rows)
            p.write_text(buf.getvalue(), encoding="utf-8", newline="")
            return ok(f"wrote {p.relative_to(WORKSPACE.resolve())} ({len(rows)} rows)")
        return _guard(go)


FILE_TOOLS: list[_Tool] = [ListDir(), ReadFile(), ReadPdf(), WriteFile(), WriteCsv()]
