"""Tests for the in-process event bus."""

import asyncio
import pytest


@pytest.mark.asyncio
async def test_event_bus_publishes_to_subscribers():
    """Subscribers should receive events published after they subscribe."""
    from grimoire.services.event_bus import event_bus

    received = []

    async def collect_events():
        async for event in event_bus.subscribe("queue"):
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(collect_events())

    await asyncio.sleep(0.01)  # let subscriber register
    await event_bus.publish("queue", {"type": "task_completed", "id": 1})
    await event_bus.publish("queue", {"type": "task_completed", "id": 2})

    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 2
    assert received[0]["id"] == 1
    assert received[1]["id"] == 2


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    """Multiple subscribers should each receive the same events."""
    from grimoire.services.event_bus import event_bus

    received_a = []
    received_b = []

    async def collect_a():
        async for event in event_bus.subscribe("queue"):
            received_a.append(event)
            if len(received_a) >= 1:
                break

    async def collect_b():
        async for event in event_bus.subscribe("queue"):
            received_b.append(event)
            if len(received_b) >= 1:
                break

    task_a = asyncio.create_task(collect_a())
    task_b = asyncio.create_task(collect_b())

    await asyncio.sleep(0.01)
    await event_bus.publish("queue", {"type": "task_completed", "id": 1})

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_on_disconnect():
    """When a subscriber breaks out of the loop, it should be cleaned up."""
    from grimoire.services.event_bus import event_bus

    initial_count = len(event_bus._subscribers.get("test_unsub", []))

    async def subscribe_and_break():
        async for event in event_bus.subscribe("test_unsub"):
            break  # disconnect after first event

    task = asyncio.create_task(subscribe_and_break())
    await asyncio.sleep(0.01)  # let subscriber register

    # Publish one event so the generator can yield and then break
    await event_bus.publish("test_unsub", {"type": "test"})
    await asyncio.wait_for(task, timeout=1.0)

    # Give cleanup a moment
    await asyncio.sleep(0.01)

    final_count = len(event_bus._subscribers.get("test_unsub", []))
    assert final_count == initial_count  # subscriber should be removed
