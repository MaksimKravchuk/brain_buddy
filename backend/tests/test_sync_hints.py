"""026-FR-004/011/023 and SC-004: authenticated, content-free SSE sync hints.

The hub tests drive ``HintHub`` with a controllable counter and admission. The
route tests drive the real ``APIRouter`` through the production authority and
container dependencies with a raw ASGI driver (a test client buffers a whole
streaming body). The process tests serve the real application in one process and
commit from another, so publication provably reads the shared committed counter.
"""

from __future__ import annotations

import asyncio
import json
import queue
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import allure
import httpx
import pytest

from app.api import sync_hints
from app.modules.tasks.sync.hints import (
    HEARTBEAT,
    STREAM_HEADERS,
    Generations,
    HintHub,
    SqliteCommitCounter,
)
from tests.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    _build_authenticated_client,
)
from tests.sync_hints_processes import commit

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync hints"),
    allure.story("Authenticated SSE wakes clients for committed changes"),
]
BACKEND = Path(__file__).resolve().parents[1]
FLAG = "rust_core_sync"
URL = "/api/sync/v1/hints"
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
GENERATIONS = Generations("server-1", "feed-1", "access-1", "storage-1")
EVENT_KEYS = {
    "scope_id",
    "server_generation",
    "feed_generation",
    "server_now",
    "correlation_id",
}
SECONDS = 3.0
QUIET = 0.25


def parse(frame: bytes | str) -> dict[str, Any]:
    text = frame.decode() if isinstance(frame, bytes) else frame
    lines = text.strip("\n").split("\n")
    assert lines[0] == "event: scope_changed", text
    assert len(lines) == 2 and lines[1].startswith("data: "), text
    return json.loads(lines[1].removeprefix("data: "))  # type: ignore[no-any-return]


# --- the hub, without HTTP ---------------------------------------------------


class Source:
    """A counter and an admission a test can move between watcher passes."""

    def __init__(self) -> None:
        self.sequence: str | None = "1"
        self.generations: Generations | None = GENERATIONS
        self.reads = 0
        self.fail = False

    def counter(self, scope_id: str) -> str | None:
        self.reads += 1
        if self.fail:
            raise sqlite3.OperationalError("database is locked")
        return self.sequence

    def admission(self) -> Generations | None:
        return self.generations

    def hub(self, **bounds: float) -> HintHub:
        bounds = {"poll": 0.01, "heartbeat": 5.0, "max_age": 60.0} | bounds
        return HintHub(self.counter, lambda: NOW, **bounds)


def test_026_FR_004_the_initial_event_is_content_free_and_closes_the_race():
    source = Source()

    async def scenario() -> None:
        stream = source.hub().stream("owner", source.admission, "corr-1")
        first = await asyncio.wait_for(anext(stream), SECONDS)
        with allure.step("the first frame is one scope_changed event with 5 fields"):
            event = parse(first)
            assert set(event) == EVENT_KEYS
            assert event["scope_id"] == "owner"
            assert event["server_generation"] == "server-1"
            assert event["feed_generation"] == "feed-1"
            assert event["server_now"] == NOW.isoformat()
            assert event["correlation_id"] == "corr-1"
        with allure.step("a commit right after subscribing is a second event"):
            source.sequence = "2"
            assert parse(await asyncio.wait_for(anext(stream), SECONDS)) == event

    asyncio.run(scenario())


def test_026_FR_023_commits_between_passes_coalesce_and_duplicates_are_silent():
    source = Source()

    async def scenario() -> None:
        hub = source.hub()
        stream = hub.stream("owner", source.admission, "corr-1")
        assert await asyncio.wait_for(anext(stream), SECONDS)
        with allure.step("three commits within one pass become one pending event"):
            for sequence in ("2", "3", "4"):
                source.sequence = sequence
            assert parse(await asyncio.wait_for(anext(stream), SECONDS))
        with allure.step("an unchanged counter publishes nothing"):
            quiet = asyncio.ensure_future(anext(stream))
            done, _ = await asyncio.wait({quiet}, timeout=QUIET)
            assert not done
            quiet.cancel()

    asyncio.run(scenario())


def test_026_FR_004_one_watcher_serves_every_connection_but_not_their_authority():
    source = Source()
    revoked = Source()

    async def scenario() -> None:
        hub = source.hub()
        first = hub.stream("owner", source.admission, "a")
        second = hub.stream("owner", revoked.admission, "b")
        for stream in (first, second):
            assert await asyncio.wait_for(anext(stream), SECONDS)
        with allure.step("two connections of one scope share one watcher"):
            assert hub.watched_scopes == 1
        with allure.step("revoking one connection closes only that one"):
            revoked.generations = None
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(second), SECONDS)
            source.sequence = "2"
            assert parse(await asyncio.wait_for(anext(first), SECONDS))
        with allure.step("the watcher stops with its last listener"):
            await first.aclose()
            await asyncio.sleep(0.1)
            assert hub.watched_scopes == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "moved",
    [
        Generations("server-2", "feed-1", "access-1", "storage-1"),
        Generations("server-1", "feed-2", "access-1", "storage-1"),
        Generations("server-1", "feed-1", "access-2", "storage-1"),
        Generations("server-1", "feed-1", "access-1", "storage-2"),
        None,
    ],
)
def test_026_FR_011_a_generation_change_or_revocation_closes_the_stream(moved):
    source = Source()

    async def scenario() -> None:
        stream = source.hub().stream("owner", source.admission, "corr-1")
        assert await asyncio.wait_for(anext(stream), SECONDS)
        source.generations = moved
        with (
            allure.step("the stream ends without another event"),
            pytest.raises(StopAsyncIteration),
        ):
            await asyncio.wait_for(anext(stream), SECONDS)

    asyncio.run(scenario())


def test_026_FR_004_a_scope_that_is_not_admitted_never_opens():
    source = Source()
    source.generations = None

    async def scenario() -> None:
        hub = source.hub()
        assert [frame async for frame in hub.stream("o", source.admission, "c")] == []
        assert hub.watched_scopes == 0

    asyncio.run(scenario())


def test_026_FR_004_heartbeats_and_the_age_cap_bound_a_connection():
    source = Source()

    async def scenario() -> None:
        stream = source.hub(heartbeat=0.03, max_age=0.2).stream(
            "o", source.admission, "c"
        )
        frames = [frame async for frame in stream]
        with allure.step("silence is a comment heartbeat, then the stream reopens"):
            assert parse(frames[0])
            assert frames[1:] and set(frames[1:]) == {HEARTBEAT}
            assert HEARTBEAT.startswith(b":") and not HEARTBEAT.startswith(b"event")

    asyncio.run(scenario())


def test_026_FR_004_a_failing_commit_counter_fails_closed_and_close_ends_streams():
    source = Source()

    async def scenario() -> None:
        hub = source.hub()
        stream = hub.stream("owner", source.admission, "corr-1")
        assert await asyncio.wait_for(anext(stream), SECONDS)
        source.fail = True
        with (
            allure.step("a storage fault closes the stream so the client reconnects"),
            pytest.raises(StopAsyncIteration),
        ):
            await asyncio.wait_for(anext(stream), SECONDS)
        source.fail = False
        survivor = hub.stream("owner", source.admission, "corr-2")
        assert await asyncio.wait_for(anext(survivor), SECONDS)
        with allure.step("shutdown closes every open stream"):
            hub.close()
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(survivor), SECONDS)

    asyncio.run(scenario())


def test_026_SC_004_the_committed_counter_is_read_from_the_shared_database(tmp_path):
    database = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sync_scopes (owner_id TEXT, commit_seq TEXT)")
    counter = SqliteCommitCounter(database)
    with allure.step("no scope row reads as no sequence"):
        assert counter("owner") is None
    with allure.step("a committed row is visible, an open transaction is not"):
        writer = sqlite3.connect(database, isolation_level=None)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO sync_scopes VALUES ('owner', '7')")
        assert counter("owner") is None
        writer.execute("COMMIT")
        writer.close()
        assert counter("owner") == "7"
    assert STREAM_HEADERS["X-Accel-Buffering"] == "no"


# --- the real router, in this process ----------------------------------------


class Asgi:
    """One raw ASGI request whose response body is read frame by frame."""

    def __init__(self, app: Any, query: str, headers: dict[str, str]) -> None:
        self.app, self.query, self.extra = app, query, headers
        self.status = 0
        self.headers: dict[str, str] = {}
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.frames: asyncio.Queue[bytes] = asyncio.Queue()
        self.started = asyncio.Event()

    async def __aenter__(self) -> Asgi:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": URL,
            "raw_path": URL.encode(),
            "query_string": self.query.encode(),
            "root_path": "",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in self.extra.items()
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 5000),
        }
        self.inbox.put_nowait({"type": "http.request", "body": b"", "more_body": False})

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self.headers = {k.decode(): v.decode() for k, v in message["headers"]}
                self.started.set()
            elif message["type"] == "http.response.body":
                self.frames.put_nowait(message.get("body", b""))

        self.task = asyncio.create_task(self.app(scope, self.inbox.get, send))
        await asyncio.wait_for(self.started.wait(), SECONDS)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.inbox.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(self.task, SECONDS)

    async def frame(self, wait: float = SECONDS) -> bytes | None:
        try:
            return await asyncio.wait_for(self.frames.get(), wait)
        except TimeoutError:
            return None

    async def silent(self, window: float = QUIET) -> bool:
        while (frame := await self.frame(window)) is not None:
            if frame not in (HEARTBEAT, b""):
                return False
        return True

    async def ended(self, wait: float = SECONDS) -> bool:
        await asyncio.wait({self.task}, timeout=wait)
        return self.task.done()

    async def body(self) -> bytes:
        await asyncio.wait_for(self.task, SECONDS)
        chunks = []
        while not self.frames.empty():
            chunks.append(self.frames.get_nowait())
        return b"".join(chunks)


class World:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.app = client.app
        self.container = self.app.state.container
        self.owner = client.get("/api/auth/me").json()["id"]
        self.db_path = self.container.task_repo.db_path
        self.data_dir = self.db_path.parent
        self.app.include_router(sync_hints.router, prefix="/api")
        self.set_flag(True)
        self.app.state.sync_hint_hub = HintHub(
            SqliteCommitCounter(self.db_path),
            self.container.task_service.clock,
            poll=0.02,
            heartbeat=5.0,
        )
        # Opening the stream creates the scope row through the production authority.
        self.cookie = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)

    def set_flag(self, on: bool) -> None:
        flags = self.container.feature_flag_service
        flags.set_mode(FLAG, "on" if on else "off", operator_id="sync-hints")

    def open(self, scope: str | None = None, **headers: str) -> Asgi:
        query = f"scope_id={scope or self.owner}"
        return Asgi(self.app, query, {"cookie": self.cookie, **headers})

    def commit(self, key: str, *, rollback: bool = False) -> str:
        return commit(self.data_dir, self.owner, key, rollback=rollback)

    def sql(self, statement: str, *params: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(statement, params)


@pytest.fixture()
def world(tmp_path, monkeypatch) -> Iterator[World]:
    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="sync-hints",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    yield World(client)
    client.close()


def test_026_FR_004_the_route_streams_unbuffered_content_free_hints(world):
    async def scenario() -> None:
        async with world.open(**{"Last-Event-ID": "99"}) as stream:
            with allure.step("success is an unbuffered text/event-stream"):
                assert stream.status == 200
                assert stream.headers["content-type"].startswith("text/event-stream")
                assert stream.headers["cache-control"] == "no-store"
                assert stream.headers["x-accel-buffering"] == "no"
            with allure.step("the initial event names the scope and generations only"):
                first = await stream.frame()
                assert first is not None
                event = parse(first)
                assert set(event) == EVENT_KEYS
                assert event["scope_id"] == world.owner
                assert event["correlation_id"] == stream.headers["x-correlation-id"]
                with sqlite3.connect(world.db_path) as conn:
                    row = conn.execute(
                        "SELECT server_generation, feed_generation, commit_seq "
                        "FROM sync_scopes WHERE owner_id = ?",
                        (world.owner,),
                    ).fetchone()
                assert (event["server_generation"], event["feed_generation"]) == row[:2]
                assert row[2] == "0"
            with allure.step("Last-Event-ID neither replays nor positions the feed"):
                assert await stream.silent()

    asyncio.run(scenario())


def test_026_SC_004_only_committed_changes_wake_the_stream_with_no_content(world):
    async def scenario() -> None:
        async with world.open() as stream:
            assert await stream.frame()
            with allure.step("a rolled-back writer produces no event"):
                await asyncio.to_thread(world.commit, "rolled", rollback=True)
                assert await stream.silent()
            with allure.step("a committed writer produces one content-free event"):
                assert await asyncio.to_thread(world.commit, "kept") == "1"
                frame = await stream.frame()
                assert frame is not None
                assert set(parse(frame)) == EVENT_KEYS
                assert b"Secret" not in frame and b"kept" not in frame
                assert await stream.silent()

    asyncio.run(scenario())


def test_026_FR_004_reopening_after_missed_commits_catches_up_immediately(world):
    async def scenario() -> None:
        async with world.open() as stream:
            assert await stream.frame()
        with allure.step("commits while no stream is open leave nothing to replay"):
            await asyncio.to_thread(world.commit, "while-away")
        async with world.open() as reopened:
            with allure.step("the reconnect opens with an event that requests a pull"):
                assert await reopened.frame() is not None
                assert await reopened.silent()

    asyncio.run(scenario())


def test_026_FR_011_foreign_unknown_and_unauthenticated_scopes_are_refused(world):
    async def scenario() -> None:
        bodies = []
        for scope in ("user_someone_else", "scope-unknown"):
            async with world.open(scope) as stream:
                assert stream.status == 404
                body = json.loads(await stream.body())
                assert scope not in json.dumps(body)
                bodies.append(body)
        with allure.step("both 404s differ only by correlation ID"):
            assert bodies[0]["error"]["code"] == "RESOURCE_NOT_FOUND"
            assert [b["error"] for b in bodies][0] == bodies[1]["error"]
        async with Asgi(world.app, f"scope_id={world.owner}", {}) as anonymous:
            with allure.step("no session cookie is 401 AUTH_REQUIRED"):
                assert anonymous.status == 401
                assert json.loads(await anonymous.body())["error"]["code"] == (
                    "AUTH_REQUIRED"
                )
        world.set_flag(False)
        async with world.open() as disabled:
            with allure.step("a scope whose sync is off is not opened"):
                assert disabled.status == 403
                assert json.loads(await disabled.body())["error"]["code"] == (
                    "ACCESS_DENIED"
                )

    asyncio.run(scenario())


def _change_credential(world: World) -> None:
    world.container.user_repo.update_email(world.owner, "changed@example.com")


@pytest.mark.parametrize(
    "revoke",
    [
        _change_credential,
        lambda w: w.sql("UPDATE sync_scopes SET admission_open = 0"),
        lambda w: w.set_flag(False),
        lambda w: w.sql("UPDATE sync_scopes SET feed_generation = 'feed-reset'"),
        lambda w: w.sql("UPDATE sync_scopes SET server_generation = 'server-reset'"),
    ],
    ids=["credential", "admission", "flag-off", "feed-generation", "server-generation"],
)
def test_026_FR_011_revocation_and_generation_change_close_the_open_stream(
    world, revoke
):
    async def scenario() -> None:
        async with world.open() as stream:
            assert await stream.frame()
            revoke(world)
            with allure.step("the stream ends and no resource detail follows"):
                assert await stream.ended()
                assert await stream.silent(0.05)

    asyncio.run(scenario())


# --- separate stream and writer processes ------------------------------------


class Sse:
    """A real HTTP SSE connection read on a thread so every wait is bounded."""

    END = object()

    def __init__(self, base: str, scope: str, cookie: str) -> None:
        self.items: queue.Queue[object] = queue.Queue()
        self.ready = threading.Event()
        self.status = 0
        self.headers: httpx.Headers = httpx.Headers()
        self._thread = threading.Thread(
            target=self._pump, args=(f"{base}{URL}?scope_id={scope}", cookie)
        )
        self._thread.daemon = True
        self._thread.start()
        assert self.ready.wait(10), "no response headers"

    def _pump(self, url: str, cookie: str) -> None:
        try:
            with (
                httpx.Client(timeout=httpx.Timeout(10.0)) as client,
                client.stream("GET", url, headers={"Cookie": cookie}) as response,
            ):
                self.status, self.headers = response.status_code, response.headers
                self.ready.set()
                block: list[str] = []
                for line in response.iter_lines():
                    if line:
                        block.append(line)
                    else:
                        self.items.put("\n".join(block))
                        block = []
        except httpx.HTTPError:
            pass
        finally:
            self.ready.set()
            self.items.put(self.END)

    def next(self, timeout: float = 5.0) -> object | None:
        try:
            return self.items.get(timeout=timeout)
        except queue.Empty:
            return None

    def event(self, timeout: float = 5.0) -> dict[str, Any]:
        """The next scope_changed event, skipping heartbeat comments."""
        deadline = time.monotonic() + timeout
        while (item := self.next(max(deadline - time.monotonic(), 0.01))) is not None:
            assert item is not self.END, "stream closed"
            assert isinstance(item, str)
            if not item.startswith(":"):
                return parse(item)
        raise AssertionError("no event")

    def quiet(self, window: float) -> bool:
        deadline = time.monotonic() + window
        while (item := self.next(max(deadline - time.monotonic(), 0.01))) is not None:
            if item is self.END or not str(item).startswith(":"):
                return False
        return True


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def run_writer(data_dir: Path, owner: str, key: str, *flags: str) -> str:
    done = subprocess.run(  # noqa: S603 -- current interpreter, module and pytest-owned paths
        [sys.executable, "-m", "tests.sync_hints_processes", "write", str(data_dir)]
        + [owner, key, *flags],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture()
def live(world) -> Iterator[tuple[str, World]]:
    """The real application, with the hints router, served by another process."""
    world.set_flag(True)
    port = free_port()
    server = subprocess.Popen(  # noqa: S603 -- current interpreter, module and pytest-owned paths
        [sys.executable, "-m", "tests.sync_hints_processes", "serve"]
        + [str(world.data_dir), str(port)],
        cwd=BACKEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert server.poll() is None, server.stderr.read() if server.stderr else ""
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("the stream process never became healthy")
        yield base, world
    finally:
        server.kill()
        server.wait(timeout=10)
        if server.stderr:
            server.stderr.close()


def test_026_SC_004_a_writer_process_wakes_the_stream_process(live):
    base, world = live
    with allure.step("open the real stream in the server process"):
        stream = Sse(base, world.owner, world.cookie)
        assert stream.status == 200
        assert stream.headers["x-accel-buffering"] == "no"
        assert stream.headers["cache-control"] == "no-store"
        assert set(stream.event()) == EVENT_KEYS
        assert stream.quiet(0.4)
    with allure.step("a rolled-back writer process publishes nothing"):
        assert run_writer(world.data_dir, world.owner, "w0", "rollback") == (
            "rolled back"
        )
        assert stream.quiet(0.8)
    with allure.step("a committed writer process wakes the open stream"):
        started = time.monotonic()
        assert run_writer(world.data_dir, world.owner, "w1") == "1"
        committed = time.monotonic()
        event = stream.event()
        assert set(event) == EVENT_KEYS
        allure.attach(
            f"{time.monotonic() - committed:.3f}s after commit returned "
            f"({committed - started:.3f}s writer)",
            name="Commit to event latency (informational; the pilot measures SC-004)",
        )
    with allure.step("a second commit is one more event, then silence"):
        run_writer(world.data_dir, world.owner, "w2")
        stream.event()
        assert stream.quiet(0.8)
    with allure.step("an idle stream carries comment heartbeats"):
        assert str(stream.next(3.0)).startswith(":")
    with allure.step("a foreign scope is the same 404 as an unknown one"):
        refused = [Sse(base, scope, world.cookie) for scope in ("other", "unknown")]
        assert [r.status for r in refused] == [404, 404]
    with allure.step("a reconnect after missed commits opens with an event"):
        run_writer(world.data_dir, world.owner, "w4")
        reopened = Sse(base, world.owner, world.cookie)
        assert set(reopened.event()) == EVENT_KEYS


def test_026_FR_011_revoking_the_credential_closes_a_stream_in_another_process(live):
    base, world = live
    stream = Sse(base, world.owner, world.cookie)
    stream.event()
    with allure.step("a credential change in this process ends the other's stream"):
        world.container.user_repo.update_email(world.owner, "rotated@example.com")
        assert stream.next(5.0) is stream.END


def test_026_FR_004_the_application_builds_one_default_hub_on_first_use(world):
    del world.app.state.sync_hint_hub

    async def scenario() -> None:
        async with world.open() as stream:
            assert await stream.frame()
            hub = world.app.state.sync_hint_hub
            assert (hub._poll, hub._heartbeat, hub._max_age) == (0.25, 15.0, 900.0)
            async with world.open() as second:
                assert await second.frame()
                assert world.app.state.sync_hint_hub is hub
                assert hub.watched_scopes == 1

    asyncio.run(scenario())
