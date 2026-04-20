import time

from market_digest.web.jobs import JobTracker


def test_create_returns_pending_job():
    tr = JobTracker()
    job = tr.create("AAPL", "2026-04-17")
    assert job.status == "pending"
    assert job.ticker == "AAPL"
    assert job.date == "2026-04-17"
    assert job.job_id  # non-empty
    assert tr.get(job.job_id) is job


def test_find_active_matches_pending_and_running():
    tr = JobTracker()
    j1 = tr.create("AAPL", "2026-04-17")
    assert tr.find_active("AAPL", "2026-04-17") is j1
    tr.mark_running(j1.job_id)
    assert tr.find_active("AAPL", "2026-04-17") is j1
    tr.mark_done(j1.job_id, "/x")
    assert tr.find_active("AAPL", "2026-04-17") is None


def test_mark_done_sets_output_url():
    tr = JobTracker()
    j = tr.create("AAPL", "2026-04-17")
    tr.mark_done(j.job_id, "/2026-04-17/us-rating-0/research")
    got = tr.get(j.job_id)
    assert got.status == "done"
    assert got.output_url == "/2026-04-17/us-rating-0/research"


def test_mark_failed_stores_error():
    tr = JobTracker()
    j = tr.create("AAPL", "2026-04-17")
    tr.mark_failed(j.job_id, "boom")
    got = tr.get(j.job_id)
    assert got.status == "failed"
    assert got.error == "boom"


def test_active_lists_pending_and_running_only():
    tr = JobTracker()
    a = tr.create("AAPL", "2026-04-17")
    b = tr.create("MSFT", "2026-04-17")
    tr.mark_running(b.job_id)
    c = tr.create("NVDA", "2026-04-17")
    tr.mark_done(c.job_id, "/x")
    d = tr.create("META", "2026-04-17")
    tr.mark_failed(d.job_id, "x")
    active = tr.active()
    ids = {j.job_id for j in active}
    assert a.job_id in ids
    assert b.job_id in ids
    assert c.job_id not in ids
    assert d.job_id not in ids


def test_get_unknown_returns_none():
    tr = JobTracker()
    assert tr.get("does-not-exist") is None
