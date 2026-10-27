"""Shared rate limiter. Kept in its own module so routers can import it without
creating a circular import through main.py.

Disabled under ENVIRONMENT=test -- otherwise a 50-test suite trips the 10/minute
auth limit and every test after the tenth fails for a reason unrelated to the code.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    enabled=os.environ.get("ENVIRONMENT", "development").lower() not in {"test", "testing"},
)
