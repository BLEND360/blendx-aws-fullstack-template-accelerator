"""Ports: what services need from the outside, as types.

Declared here, in the layer that owns the need, and implemented in clients/,
repositories/ and harness/. Services compose these, never concrete adapters,
so every service is testable with a stand-in and no AWS.
"""

from typing import Protocol


class DependencyProbe(Protocol):
    """One reachability check for /ready. Raises AppError when unreachable."""

    name: str

    def check(self) -> None: ...
