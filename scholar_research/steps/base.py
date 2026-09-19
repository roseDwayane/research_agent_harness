"""Shared step plumbing: a ``Context`` every step receives, and the ``Step`` protocol.

A step is a function ``run(ctx) -> StepOutput``.  It must be a pure function of
its input files + cached external responses + checkpoint decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm.client import LLMClient
from ..providers.base import HttpClient
from ..session import Session


@dataclass
class StepOutput:
    files: list[Path]
    notes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)  # printed to the user


class Context:
    def __init__(self, session: Session, config: Config, llm_backend: Any | None = None):
        self.session = session
        self.config = config
        self._llm: LLMClient | None = None
        self._llm_backend = llm_backend
        self._http: HttpClient | None = None
        self.checkpoint_mode: str = "interactive"
        self.decisions: dict[str, Any] = {}
        self.ui_print = print

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config.llm, self.session.cache, self.session.ledger, backend=self._llm_backend, api_key=self.config.api.anthropic_api_key)
        return self._llm

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            self._http = HttpClient(self.session.cache, timeout=self.config.search.request_timeout, max_attempts=self.config.search.max_attempts)
        return self._http

    def ts(self, step: int) -> str:
        return self.session.clock.for_step(step)

    def date(self, step: int) -> str:
        return self.ts(step)[:10]

    def say(self, msg: str) -> None:
        self.ui_print(msg)

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
