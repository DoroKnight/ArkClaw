"""Typed, network-free fake for the narrow OpenAI SDK boundary."""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sjtuclaw.infrastructure.llm.openai_sdk import (
    OpenAIRequest,
    OpenAIResponseEvent,
    OpenAIResponseStream,
)


@dataclass(slots=True, repr=False)
class FakeOpenAIScenario:
    events: tuple[OpenAIResponseEvent | Exception, ...] = ()
    create_error: Exception | None = None
    create_started: asyncio.Event | None = None
    create_gate: asyncio.Event | None = None
    iteration_started: asyncio.Event | None = None
    iteration_gate: asyncio.Event | None = None
    allocate_before_create_gate: bool = False


class FakeOpenAIResponseStream:
    def __init__(
        self,
        owner: FakeOpenAIResponsesClient,
        scenario: FakeOpenAIScenario,
    ) -> None:
        self._owner = owner
        self._scenario = scenario
        self._index = 0
        self.closed = False
        self.cancel_count = 0
        owner._activate(self)

    def __aiter__(self) -> AsyncIterator[OpenAIResponseEvent]:
        return self

    async def __anext__(self) -> OpenAIResponseEvent:
        if self.closed or self._index >= len(self._scenario.events):
            raise StopAsyncIteration
        if self._scenario.iteration_started is not None:
            self._scenario.iteration_started.set()
        try:
            if self._scenario.iteration_gate is not None:
                await self._scenario.iteration_gate.wait()
        except asyncio.CancelledError:
            self.cancel_count += 1
            raise
        if self.closed:
            raise StopAsyncIteration
        item = self._scenario.events[self._index]
        self._index += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._scenario.iteration_gate is not None:
            self._scenario.iteration_gate.set()
        self._owner._deactivate(self)


class FakeOpenAIResponsesClient:
    def __init__(self, factory: FakeOpenAIClientFactory) -> None:
        self._factory = factory
        self.requests: list[OpenAIRequest] = []
        self.streams: list[FakeOpenAIResponseStream] = []
        self._active_streams: dict[int, FakeOpenAIResponseStream] = {}
        self.closed = False
        self.close_count = 0
        self.create_cancel_count = 0

    @property
    def active_stream_count(self) -> int:
        return len(self._active_streams)

    @property
    def request_count(self) -> int:
        return len(self.requests)

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        if self.closed:
            raise RuntimeError("fake client is closed")
        scenario = self._factory._next_scenario()
        self.requests.append(request)
        if scenario.create_started is not None:
            scenario.create_started.set()

        stream: FakeOpenAIResponseStream | None = None
        if scenario.allocate_before_create_gate:
            stream = FakeOpenAIResponseStream(self, scenario)
            self.streams.append(stream)
        try:
            if scenario.create_gate is not None:
                await scenario.create_gate.wait()
        except asyncio.CancelledError:
            self.create_cancel_count += 1
            if stream is not None:
                await stream.close()
            raise

        if scenario.create_error is not None:
            if stream is not None:
                await stream.close()
            raise scenario.create_error
        if stream is None:
            stream = FakeOpenAIResponseStream(self, scenario)
            self.streams.append(stream)
        return stream

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_count += 1
        await asyncio.gather(
            *(stream.close() for stream in tuple(self._active_streams.values())),
            return_exceptions=True,
        )

    def _activate(self, stream: FakeOpenAIResponseStream) -> None:
        self._active_streams[id(stream)] = stream

    def _deactivate(self, stream: FakeOpenAIResponseStream) -> None:
        self._active_streams.pop(id(stream), None)


class FakeOpenAIClientFactory:
    """Records safe request settings but never stores the API key."""

    def __init__(
        self,
        scenarios: tuple[FakeOpenAIScenario, ...] = (),
    ) -> None:
        self._scenarios = deque(scenarios)
        self.clients: list[FakeOpenAIResponsesClient] = []
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
    ) -> FakeOpenAIResponsesClient:
        self.api_key_fingerprints.append(
            hashlib.sha256(api_key.encode("utf-8")).digest()
        )
        self.create_count += 1
        self.settings.append((timeout_seconds, max_retries))
        client = FakeOpenAIResponsesClient(self)
        self.clients.append(client)
        return client

    def _next_scenario(self) -> FakeOpenAIScenario:
        if not self._scenarios:
            raise AssertionError("No FakeOpenAIScenario was queued")
        return self._scenarios.popleft()
