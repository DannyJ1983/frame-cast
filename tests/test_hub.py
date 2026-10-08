import asyncio

import pytest

from framecast.hub import PENDING_TTL, Hub, PlayCommand, sse


def command(title="Clip", created=None):
    cmd = PlayCommand(url="https://cdn/a.m3u8", title=title, kind="hls", page_url="https://page")
    if created is not None:
        cmd.created = created
    return cmd


def drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_play_with_no_tv_stays_pending_and_reaches_tv_on_connect():
    async def run():
        hub = Hub()
        cmd = command()
        assert hub.play(cmd) == 0
        assert hub.pending is cmd
        queue = hub.subscribe_tv()
        events = drain(queue)
        assert events == [("play", cmd.to_event())]

    asyncio.run(run())


def test_stale_pending_not_delivered():
    async def run():
        now = [1000.0]
        hub = Hub(clock=lambda: now[0])
        hub.play(command(created=now[0]))
        now[0] += PENDING_TTL + 1
        queue = hub.subscribe_tv()
        assert drain(queue) == []
        assert hub.pending is None

    asyncio.run(run())


def test_ack_clears_pending_and_wakes_waiter():
    async def run():
        hub = Hub()
        queue = hub.subscribe_tv()
        cmd = command()
        assert hub.play(cmd) == 1
        assert drain(queue)[0][0] == "play"
        waiter = asyncio.create_task(hub.wait_for_ack(cmd.id, 2))
        await asyncio.sleep(0)
        hub.report_status({"command_id": cmd.id, "state": "loading"})
        assert await waiter is True
        assert hub.pending is None

    asyncio.run(run())


def test_wait_for_ack_times_out():
    async def run():
        hub = Hub()
        cmd = command()
        hub.play(cmd)
        assert await hub.wait_for_ack(cmd.id, 0.05) is False
        assert await hub.wait_for_ack("unknown", 0.05) is False

    asyncio.run(run())


def test_idle_status_is_not_an_ack():
    async def run():
        hub = Hub()
        cmd = command()
        hub.play(cmd)
        hub.report_status({"command_id": cmd.id, "state": "idle"})
        assert hub.pending is cmd

    asyncio.run(run())


def test_control_goes_to_tvs_and_stop_clears_pending():
    async def run():
        hub = Hub()
        hub.play(command())
        queue = hub.subscribe_tv()
        drain(queue)
        assert hub.control("seek", 30) == 1
        assert drain(queue) == [("control", {"action": "seek", "seconds": 30})]
        hub.control("stop")
        assert hub.pending is None
        with pytest.raises(ValueError):
            hub.control("explode")

    asyncio.run(run())


def test_phone_gets_state_and_updates():
    async def run():
        hub = Hub()
        phone = hub.subscribe_phone()
        first = drain(phone)
        assert first[0][0] == "state"
        assert first[0][1]["tv_connected"] is False
        tv = hub.subscribe_tv()
        assert drain(phone)[-1][1]["tv_connected"] is True
        hub.unsubscribe_tv(tv)
        assert drain(phone)[-1][1]["tv_connected"] is False
        hub.note("Hello", "error")
        assert drain(phone) == [("message", hub.last_message)]
        hub.unsubscribe_phone(phone)
        hub.note("Again")
        assert drain(phone) == []

    asyncio.run(run())


def test_state_shows_current_and_recent():
    async def run():
        hub = Hub()
        hub.play(command("First"))
        hub.play(command("Second"))
        state = hub.state()
        assert state["current"]["title"] == "Second"
        assert [r["title"] for r in state["recent"]] == ["Second", "First"]
        assert state["pending"] is True

    asyncio.run(run())


def test_full_queue_drops_rather_than_blocks():
    async def run():
        hub = Hub()
        queue = hub.subscribe_tv()
        for _ in range(queue.maxsize + 5):
            hub.control("toggle")
        assert queue.full()

    asyncio.run(run())


def test_sse_format():
    assert sse("play", {"a": 1}) == 'event: play\ndata: {"a":1}\n\n'
