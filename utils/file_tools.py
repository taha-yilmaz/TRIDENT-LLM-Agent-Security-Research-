"""
utils/file_tools.py
====================
ReadDocumentTool — a LangChain/CrewAI-compatible BaseTool that reads the
contents of a .txt or .md file and returns it as a plain string.

Used by CrewAI agents so they can ingest documents as part of their task
context (including, intentionally, poisoned documents during S1/S2 tests).
"""

from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import AliasChoices, BaseModel, Field


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------
class ReadDocumentInput(BaseModel):
    file_path: str = Field(
        ...,
        description="Absolute or relative path to the .txt or .md file to read.",
        validation_alias=AliasChoices("file_path", "path"),
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------
class ReadDocumentTool(BaseTool):
    """Read the full text content of a .txt or .md file from disk."""

    name: str = "read_document"
    description: str = (
        "Use this tool to read the contents of a text file (.txt or .md). "
        "Pass file_path (or path) as the file path string. "
        "Returns the raw text content of the file."
    )
    args_schema: Type[BaseModel] = ReadDocumentInput

    # ------------------------------------------------------------------
    # Synchronous run (required by BaseTool)
    # ------------------------------------------------------------------
    def _run(self, file_path: str) -> str:
        path = Path(file_path)

        # --- Validation -----------------------------------------------
        if not path.exists():
            return f"[ERROR] File not found: {file_path}"

        if not path.is_file():
            return f"[ERROR] Path is not a file: {file_path}"

        suffix = path.suffix.lower()
        if suffix not in {".txt", ".md"}:
            return (
                f"[ERROR] Unsupported file type '{suffix}'. "
                "Only .txt and .md files are allowed."
            )

        # --- Read -------------------------------------------------------
        try:
            content = path.read_text(encoding="utf-8")
        except PermissionError:
            return f"[ERROR] Permission denied when reading: {file_path}"
        except Exception as exc:  # noqa: BLE001
            return f"[ERROR] Unexpected error reading file: {exc}"

        if not content.strip():
            return "[WARNING] File is empty."

        return content

    # ------------------------------------------------------------------
    # Async run — delegates to the sync version for simplicity
    # ------------------------------------------------------------------
    async def _arun(self, file_path: str) -> str:
        return self._run(file_path)
