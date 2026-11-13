"""Providers: who does the model Units' write and fanout steps - one interface, any number of implementations.

The executor (executors.py) hands every provider the same WorkerRequest and gets the same WorkerResult back
(base.py); it never asks which provider runs. Two kinds:

  chat.py           ChatProvider        a model without tools: the files and the lookups in the prompt, one JSON
                                        answer, the conductor writes the files the scope allows
    claude.py       ClaudeProvider      "claude" (the default): the Anthropic Messages API
    gpt.py          GPTProvider         "gpt": the OpenAI Responses API
    gemini.py       GeminiProvider      "gemini": the Gemini API (generateContent)
    ollama.py       OllamaProvider      "ollama": an Ollama server's HTTP API
  agent.py          AgentProvider       a worker with tools: it opens its files, runs the allowed skill commands
                                        (shims) and writes its answer itself - none is built in; the only kind that
                                        could run B6

[harness] worker names the provider: a name registered here ("claude", "gpt", "gemini", "ollama") or
"package.module:Class" (a Provider subclass of your own, imported when the config is read). To add one:

  - an agent (another coding-agent CLI, an API with tool use): subclass AgentProvider, implement run();
  - a chat API without tools (OpenAI-compatible, vLLM ...): subclass ChatProvider and implement chat() - the prompt,
    the conversation, the answer's schema and the write scope come with it (claude.py, gpt.py, gemini.py and
    ollama.py are four);
  - set `name`, then register(cls) or use worker = "package.module:Class"; its own settings go in a
    [harness.provider_options.<name>] table (Provider.options()), check_config() refuses a config it cannot run, and
    default_model() names the model when [harness] model is not set.
"""
from __future__ import annotations

import importlib

from .agent import AgentProvider
from .base import TRANSPORT, FileScope, Provider, WorkerRequest, WorkerResult
from .chat import ChatProvider
from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .gpt import GPTProvider
from .ollama import OllamaProvider

__all__ = ["PROVIDERS", "TRANSPORT", "AgentProvider", "ChatProvider", "ClaudeProvider", "FileScope", "GPTProvider",
           "GeminiProvider", "OllamaProvider", "Provider", "WorkerRequest", "WorkerResult", "make_provider",
           "provider_class", "register"]

PROVIDERS: dict[str, type[Provider]] = {"claude": ClaudeProvider, "gpt": GPTProvider, "gemini": GeminiProvider,
                                        "ollama": OllamaProvider}
REMOVED = {"claude-code": 'the claude -p worker is removed: worker = "claude" is the Claude API'}


def register(cls: type[Provider], name: str | None = None) -> type[Provider]:
    """Make a provider available as [harness] worker = "<name>" (default: its `name`); also a class decorator."""
    key = name or cls.name
    if not key:
        raise ValueError(f"{cls.__name__} has no name to be registered under")
    PROVIDERS[key] = cls
    return cls


def provider_class(worker: str) -> type[Provider]:
    """The provider [harness] worker names: a registered name, or "package.module:Class"."""
    if worker in PROVIDERS:
        return PROVIDERS[worker]
    if worker in REMOVED:
        raise ValueError(f"worker {worker!r}: {REMOVED[worker]}")
    mod, sep, attr = str(worker).partition(":")
    if not (sep and mod and attr):
        raise ValueError(f"worker must be one of {', '.join(sorted(PROVIDERS))} or package.module:Class, "
                         f"not {worker!r}")
    try:
        cls = getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"worker {worker!r}: {e}") from e
    if not (isinstance(cls, type) and issubclass(cls, Provider)):
        raise ValueError(f"worker {worker!r} is not a Provider subclass (harness/providers/base.py)")
    return cls


def make_provider(cfg, state_dir=None) -> Provider:
    """The run's provider: the one cfg.worker names, made with the config and the run's state folder."""
    return provider_class(cfg.worker)(cfg, state_dir)
