"""Network-free fake for the DeepSeek Chat Completions boundary."""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sjtuclaw.infrastructure.llm.deepseek_sdk import (
    DeepSeekEvent,
    DeepSeekRequest,
    DeepSeekStream,
)


@dataclass(slots=True, repr=False)
class FakeDeepSeekScenario:
    events: tuple[DeepSeekEvent | Exception, ...] = ()
    create_error: Exception | None = None
    create_started: asyncio.Event | None = None
    create_gate: asyncio.Event | None = None
    iteration_started: asyncio.Event | None = None
    iteration_gate: asyncio.Event | None = None
    stream_close_started: asyncio.Event | None = None
    stream_close_gate: asyncio.Event | None = None
    client_close_started: asyncio.Event | None = None
    client_close_gate: asyncio.Event | None = None
    stream_close_failures: int = 0
    client_close_failures: int = 0


class FakeDeepSeekStream:
    def __init__(
        self,
        owner: FakeDeepSeekClient,
        scenario: FakeDeepSeekScenario,
    ) -> None:
        self._owner = owner
        self._scenario = scenario
        self._index = 0
        self.closed = False
        self.close_count = 0
        owner._active_streams[id(self)] = self

    def __aiter__(self) -> AsyncIterator[DeepSeekEvent]:
        return self

    async def __anext__(self) -> DeepSeekEvent:
        if self.closed or self._index >= len(self._scenario.events):
            raise StopAsyncIteration
        if self._scenario.iteration_started is not None:
            self._scenario.iteration_started.set()
        if self._scenario.iteration_gate is not None:
            await self._scenario.iteration_gate.wait()
        item = self._scenario.events[self._index]
        self._index += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.close_count += 1
        if self._scenario.stream_close_started is not None:
            self._scenario.stream_close_started.set()
        if self._scenario.stream_close_gate is not None:
            await self._scenario.stream_close_gate.wait()
        if self.close_count <= self._scenario.stream_close_failures:
            raise RuntimeError("fake stream close failure")
        if self.closed:
            return
        self.closed = True
        if self._scenario.iteration_gate is not None:
            self._scenario.iteration_gate.set()
        self._owner._active_streams.pop(id(self), None)


class FakeDeepSeekClient:
    def __init__(
        self,
        factory: FakeDeepSeekClientFactory,
    ) -> None:
        self._factory = factory
        self._last_scenario: FakeDeepSeekScenario | None = None
        self.requests: list[DeepSeekRequest] = []
        self.streams: list[FakeDeepSeekStream] = []
        self._active_streams: dict[int, FakeDeepSeekStream] = {}
        self.closed = False
        self.close_count = 0

    async def create(self, request: DeepSeekRequest) -> DeepSeekStream:
        scenario = self._factory._next_scenario()
        self._last_scenario = scenario
        self.requests.append(request)
        if scenario.create_started is not None:
            scenario.create_started.set()
        if scenario.create_gate is not None:
            await scenario.create_gate.wait()
        if scenario.create_error is not None:
            raise scenario.create_error
        stream = FakeDeepSeekStream(self, scenario)
        self.streams.append(stream)
        return stream

    async def close(self) -> None:
        self.close_count += 1
        scenario = self._last_scenario
        if (
            scenario is not None
            and scenario.client_close_started is not None
        ):
            scenario.client_close_started.set()
        if (
            scenario is not None
            and scenario.client_close_gate is not None
        ):
            await scenario.client_close_gate.wait()
        close_failures = (
            scenario.client_close_failures
            if scenario is not None
            else 0
        )
        if self.close_count <= close_failures:
            raise RuntimeError("fake client close failure")
        if self.closed:
            return
        self.closed = True
        for stream in tuple(self._active_streams.values()):
            await stream.close()


class FakeDeepSeekClientFactory:
    def __init__(
        self,
        scenarios: tuple[FakeDeepSeekScenario, ...] = (),
    ) -> None:
        self._scenarios = deque(scenarios)
        self.clients: list[FakeDeepSeekClient] = []
        self.settings: list[tuple[float, int]] = []
        self.api_key_fingerprints: list[bytes] = []
        self.create_count = 0
        self.network_request_count = 0

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> FakeDeepSeekClient:
        self.create_count += 1
        self.settings.append((timeout_seconds, max_retries))
        self.api_key_fingerprints.append(
            hashlib.sha256(api_key.encode("utf-8")).digest()
        )
        client = FakeDeepSeekClient(self)
        self.clients.append(client)
        return client

    def _next_scenario(self) -> FakeDeepSeekScenario:
        if not self._scenarios:
            raise AssertionError("No FakeDeepSeekScenario was queued")
        return self._scenarios.popleft()
