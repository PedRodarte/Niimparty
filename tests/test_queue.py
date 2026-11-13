import asyncio
import time

from PIL import Image

from app.printers import PrinterError
from app.printers.mock import MockPrinter
from app.queue import DONE, PREVIEW, QUEUED, PrintQueue


def make_queue(tmp_path, printer):
    return PrintQueue(tmp_path / "db.sqlite", tmp_path / "output", printer)


def add_job(q, tmp_path, job_id, ip="1.1.1.1"):
    path = tmp_path / f"{job_id}.png"
    Image.new("L", (40, 60), 128).save(path)
    return q.create_job(job_id, path, None, "", ip)


async def wait_for(cond, timeout=5.0):
    start = time.monotonic()
    while not cond():
        if time.monotonic() - start > timeout:
            raise AssertionError("tempo esgotado")
        await asyncio.sleep(0.01)


def test_positions_follow_submission_order(tmp_path, b2):
    q = make_queue(tmp_path, MockPrinter(b2, {"mock_delay_s": 0}))
    for jid in ("a", "b", "c"):
        add_job(q, tmp_path, jid)
    assert q.get("a").status == PREVIEW
    assert q.position("a") is None
    q.submit("b")
    q.submit("a")
    q.submit("c")
    assert [q.position(j) for j in ("b", "a", "c")] == [1, 2, 3]
    assert q.queue_length() == 3


def test_worker_prints_everything_in_order(tmp_path, b2):
    printer = MockPrinter(b2, {"mock_delay_s": 0})
    q = make_queue(tmp_path, printer)

    async def scenario():
        await q.start()
        for jid in ("a", "b", "c"):
            add_job(q, tmp_path, jid)
            q.submit(jid)
        await wait_for(lambda: all(q.get(j).status == DONE for j in "abc"))
        await q.stop()

    asyncio.run(scenario())
    assert printer.printed == ["a", "b", "c"]
    outputs = sorted((tmp_path / "output").glob("*.png"))
    assert len(outputs) == 3
    assert all(q.get(j).output_path for j in "abc")


def test_pause_and_resume(tmp_path, b2):
    printer = MockPrinter(b2, {"mock_delay_s": 0})
    q = make_queue(tmp_path, printer)

    async def scenario():
        await q.start()
        q.pause()
        add_job(q, tmp_path, "a")
        q.submit("a")
        await asyncio.sleep(0.2)
        assert q.get("a").status == QUEUED
        q.resume()
        await wait_for(lambda: q.get("a").status == DONE)
        await q.stop()

    asyncio.run(scenario())


def test_printer_error_pauses_queue_and_keeps_job(tmp_path, b2):
    printer = MockPrinter(b2, {"mock_delay_s": 0, "mock_fail_with": "no_paper"})
    q = make_queue(tmp_path, printer)

    async def scenario():
        await q.start()
        add_job(q, tmp_path, "a")
        add_job(q, tmp_path, "b")
        q.submit("a")
        q.submit("b")
        await wait_for(lambda: q.paused)
        st = q.status_payload("a")
        assert st["status"] == QUEUED and st["error"] == "no_paper" and st["position"] == 1
        assert q.pause_reason == "no_paper"
        printer.fail_with = None  # organizador trocou o rolo
        q.resume()
        await wait_for(lambda: q.get("b").status == DONE)
        await q.stop()

    asyncio.run(scenario())
    assert printer.printed == ["a", "b"]


def test_queue_survives_restart(tmp_path, b2):
    q1 = make_queue(tmp_path, MockPrinter(b2, {"mock_delay_s": 0}))
    add_job(q1, tmp_path, "a")
    q1.submit("a")
    q1.close()

    printer = MockPrinter(b2, {"mock_delay_s": 0})
    q2 = make_queue(tmp_path, printer)

    async def scenario():
        await q2.start()
        await wait_for(lambda: q2.get("a").status == DONE)
        await q2.stop()

    asyncio.run(scenario())
    assert printer.printed == ["a"]


def test_pause_state_survives_restart(tmp_path, b2):
    q1 = make_queue(tmp_path, MockPrinter(b2, {"mock_delay_s": 0}))
    q1.pause("manual")
    q1.close()
    q2 = make_queue(tmp_path, MockPrinter(b2, {"mock_delay_s": 0}))
    assert q2.paused and q2.pause_reason == "manual"


def test_submissions_since_counts_per_ip(tmp_path, b2):
    q = make_queue(tmp_path, MockPrinter(b2, {"mock_delay_s": 0}))
    for jid, ip in (("a", "1.1.1.1"), ("b", "1.1.1.1"), ("c", "2.2.2.2"), ("d", "1.1.1.1")):
        add_job(q, tmp_path, jid, ip)
    for jid in "abc":
        q.submit(jid)
    since = time.time() - 60
    assert q.submissions_since("1.1.1.1", since) == 2  # "d" ficou só na prévia
    assert q.submissions_since("2.2.2.2", since) == 1


def test_reprint_and_delete(tmp_path, b2):
    printer = MockPrinter(b2, {"mock_delay_s": 0})
    q = make_queue(tmp_path, printer)

    async def scenario():
        await q.start()
        add_job(q, tmp_path, "a")
        q.submit("a")
        await wait_for(lambda: q.get("a").status == DONE)
        q.submit("a")  # reimprimir
        await wait_for(lambda: len(printer.printed) == 2)
        await wait_for(lambda: q.get("a").status == DONE)
        await q.stop()

    asyncio.run(scenario())
    label = q.get("a").label_path
    q.delete("a")
    assert q.get("a") is None
    assert not (tmp_path / "a.png").exists() and label
