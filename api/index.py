"""Vercel serverless entrypoint.

`includeFiles: app/**` in vercel.json ships the whole package, so this import works.
Without it the function bundle contains only this file and the import below dies.
"""

from app.main import app

__all__ = ["app"]
