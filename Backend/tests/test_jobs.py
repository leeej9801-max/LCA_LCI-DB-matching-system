"""작업 큐·작업자 시험. 임시 DB + 가짜 임베더."""
import logging
import os
import signal
import subprocess
import sys
import threading
import time

import psycopg
import pytest

from app import jobs
from app.embedder import OLLAMA_DOWN
from app.errors import ApiError
from test_bom_match import add_session, bomdb  # noqa: F401  (fixture 재사용)
from test_indexer import FakeEmbedder
from test_migrate import needs_db, tempdb  # noqa: F401


def make_job(ci, session_id):
    with psycopg.connect(ci) as conn:
        return jobs.enqueue(conn, session_id)


def job(ci, job_id):
    with psycopg.connect(ci) as conn:
        return dict(zip(["state", "stages", "result", "error"],
                        conn.execute("SELECT state, stages, result, error FROM job WHERE job_id = %s", (job_id,)).fetchone()))


@needs_db
def test_queue_limit_429(bomdb, monkeypatch):
    monkeypatch.setattr(jobs, "QUEUE_LIMIT", 2)
    sid = add_session(bomdb, ["냉연강판"])
    make_job(bomdb, sid)
    make_job(bomdb, sid)
    with pytest.raises(ApiError) as e:
        make_job(bomdb, sid)
    assert (e.value.status, e.value.code) == (429, "QUEUE_FULL")


@needs_db
def test_run_updates_stages_and_result(bomdb):
    sid = add_session(bomdb, ["냉연강판", "냉연강판", "열연강판"])
    jid = make_job(bomdb, sid)
    assert jobs.claim(bomdb) == jid and jobs.claim(bomdb) is None
    jobs.run_match_job(bomdb, jid, lambda ci: FakeEmbedder())
    j = job(bomdb, jid)
    assert j["state"] == "succeeded" and j["error"] is None
    assert {k: j["result"][k] for k in ("session_id", "queries", "cache_hits")} == {"session_id": sid, "queries": 2, "cache_hits": 0}
    stages = {s["name"]: s for s in j["stages"]}
    assert [s["name"] for s in j["stages"]] == ["정규화", "후보 검색", "판정·환산"]
    assert (stages["정규화"]["done"], stages["정규화"]["total"]) == (3, 3)
    assert (stages["후보 검색"]["done"], stages["후보 검색"]["total"], stages["후보 검색"]["state"]) == (2, 2, "succeeded")
    assert all(s["state"] == "succeeded" and s["started_at"] and s["finished_at"] for s in j["stages"])


class DownEmbedder(FakeEmbedder):
    def embed(self, texts):
        raise SystemExit(OLLAMA_DOWN)


@needs_db
def test_failure_keeps_session(bomdb):
    sid = add_session(bomdb, ["냉연강판"])
    jid = make_job(bomdb, sid)
    jobs.claim(bomdb)
    jobs.run_match_job(bomdb, jid, lambda ci: DownEmbedder())
    j = job(bomdb, jid)
    assert j["state"] == "failed" and j["error"]["code"] == "EMBEDDER_UNAVAILABLE" and j["error"]["detail"] == OLLAMA_DOWN
    assert {s["name"]: s["state"] for s in j["stages"]}["후보 검색"] == "failed"
    with psycopg.connect(bomdb) as conn:
        assert conn.execute("SELECT count(*) FROM bom_item WHERE project_id = %s", (sid,)).fetchone()[0] == 1  # 세션·행은 남는다
        assert conn.execute("SELECT count(*) FROM match_run").fetchone()[0] == 0  # 매칭 트랜잭션은 롤백
    jid2 = make_job(bomdb, sid)
    jobs.claim(bomdb)
    jobs.run_match_job(bomdb, jid2, lambda ci: FakeEmbedder(model_name="fake:other"))  # 인덱스와 다른 모델 → MATCH_FAILED
    assert job(bomdb, jid2)["error"]["code"] == "MATCH_FAILED"


@needs_db
def test_recover_interrupted_and_cleanup_expired(bomdb):
    sid = add_session(bomdb, ["냉연강판"])
    jid = make_job(bomdb, sid)
    jobs.claim(bomdb)  # running 상태로 서버가 꺼졌다고 하자
    assert jobs.recover_interrupted(bomdb) == 1
    j = job(bomdb, jid)
    assert j["state"] == "failed" and j["error"]["code"] == "interrupted"
    add_session(bomdb, ["열연강판"], "oldoldoldold")
    with psycopg.connect(bomdb) as conn:
        conn.execute("UPDATE bom_project SET expires_at = now() - interval '1 minute' WHERE project_id = 'oldoldoldold'")
    assert jobs.cleanup_expired(bomdb) == 1
    with psycopg.connect(bomdb) as conn:
        assert conn.execute("SELECT count(*) FROM bom_item WHERE project_id = 'oldoldoldold'").fetchone()[0] == 0  # CASCADE
        assert conn.execute("SELECT count(*) FROM bom_project").fetchone()[0] == 1


@needs_db
def test_worker_runs_queued_job(bomdb, monkeypatch):
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.05)
    sid = add_session(bomdb, ["냉연강판"])
    jid = make_job(bomdb, sid)
    w = jobs.Worker(bomdb, lambda ci: FakeEmbedder())
    w.start()
    try:
        deadline = time.time() + 20
        while job(bomdb, jid)["state"] != "succeeded" and time.time() < deadline:
            time.sleep(0.1)
    finally:
        w.stop()
    assert job(bomdb, jid)["state"] == "succeeded"


class SlowEmbedder(FakeEmbedder):
    """embed 에서 release 가 set 될 때까지(최대 60초) 멈춘다. 매칭 도중 종료를 흉내 낸다."""

    def __init__(self, started, release):
        super().__init__()
        self.started, self.release = started, release

    def embed(self, texts):
        self.started.set()
        self.release.wait(60)
        return super().embed(texts)


@needs_db
def test_stop_returns_while_job_running(bomdb, monkeypatch):
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.05)
    jid = make_job(bomdb, add_session(bomdb, ["냉연강판"]))
    started, release = threading.Event(), threading.Event()
    w = jobs.Worker(bomdb, lambda ci: SlowEmbedder(started, release))
    w.start()
    try:
        assert started.wait(20)
        t0 = time.monotonic()
        w.stop()
        assert time.monotonic() - t0 < 5
        assert not w.thread.is_alive() and job(bomdb, jid)["state"] == "running"
    finally:
        release.set()
        for t in threading.enumerate():  # 임시 DB 를 지우기 전에 남은 매칭 스레드를 끝낸다
            if t.name == f"match-{jid}":
                t.join(20)


CHILD = """
import os, signal, sys, threading
sys.path.insert(0, "tests")
from app import jobs
from test_jobs import SlowEmbedder
started, stop = threading.Event(), threading.Event()
for sig in (signal.SIGTERM, getattr(signal, "SIGBREAK", signal.SIGTERM)):
    signal.signal(sig, lambda *a: stop.set())
w = jobs.Worker(os.environ["T9B1_CI"], lambda ci: SlowEmbedder(started, threading.Event()))
w.start()
started.wait(30)
print("running", flush=True)
while not stop.wait(0.1):  # Windows 에서는 긴 wait 중 신호 처리기가 돌지 않는다
    pass
w.stop()
"""


@needs_db
def test_process_exits_after_signal_with_running_job(bomdb):
    """별도 프로세스: 매칭 중 종료 신호 → stop() 후 인터프리터가 매칭 스레드를 기다리지 않고 끝난다. 작업은 다음 시작에 interrupted."""
    jid = make_job(bomdb, add_session(bomdb, ["냉연강판"]))
    win = sys.platform == "win32"
    p = subprocess.Popen([sys.executable, "-c", CHILD], stdout=subprocess.PIPE, text=True, env={**os.environ, "T9B1_CI": bomdb},
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if win else 0)
    try:
        assert p.stdout.readline().strip() == "running"
        t0 = time.monotonic()
        p.send_signal(signal.CTRL_BREAK_EVENT if win else signal.SIGTERM)
        assert p.wait(timeout=10) == 0 and time.monotonic() - t0 < 10
    finally:
        p.kill()
    assert job(bomdb, jid)["state"] == "running"
    jobs.recover_interrupted(bomdb)
    assert job(bomdb, jid)["state"] == "failed" and job(bomdb, jid)["error"]["code"] == "interrupted"


def test_new_stages_shape():
    assert [set(s) for s in jobs.new_stages()] == [{"name", "state", "done", "total", "started_at", "finished_at"}] * 3


@needs_db
def test_failed_job_detail_is_fixed_text_and_original_goes_to_log(bomdb, caplog):
    """A1 #3: 예외 이름·내부 문구는 A21 error.detail 에 나가지 않고 로그에만 남는다."""
    class Broken(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("secret internal detail postgres://u:p@127.0.0.1:5432/x")

    jid = make_job(bomdb, add_session(bomdb, ["냉연강판"]))
    with caplog.at_level(logging.ERROR, logger="lci.jobs"):
        jobs.run_match_job(bomdb, jid, lambda ci: Broken())
    j = job(bomdb, jid)
    assert j["state"] == "failed" and j["error"] == {"detail": jobs.MATCH_FAILED_DETAIL, "code": "MATCH_FAILED"}
    assert "RuntimeError" not in j["error"]["detail"] and "secret" not in str(j["error"])
    assert "secret internal detail" in caplog.text  # 원문은 로그에


@needs_db
def test_ollama_response_body_is_not_in_job_error(bomdb, caplog):
    class Rejecting(FakeEmbedder):
        def embed(self, texts):  # 임베더가 응답 오류를 로그에 남기고 고정 문장으로 멈추는 경로와 같은 모양
            raise SystemExit(OLLAMA_DOWN)

    jid = make_job(bomdb, add_session(bomdb, ["냉연강판"]))
    jobs.run_match_job(bomdb, jid, lambda ci: Rejecting())
    assert job(bomdb, jid)["error"] == {"detail": OLLAMA_DOWN, "code": "EMBEDDER_UNAVAILABLE"}


def test_polling_db_error_is_logged_not_swallowed(monkeypatch, caplog):
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.02)
    monkeypatch.setattr(jobs, "claim", lambda ci: (_ for _ in ()).throw(psycopg.OperationalError("connection refused")))
    w = jobs.Worker("postgresql://nowhere", lambda ci: FakeEmbedder())
    with caplog.at_level(logging.WARNING, logger="lci.jobs"):
        w.thread.start()
        time.sleep(0.4)  # 폴링이 여러 번 실패해도 끊기지 않는다
        alive = w.thread.is_alive()
        w.stop()
    assert alive
    warns = [r for r in caplog.records if "작업 폴링 중 DB 오류" in r.getMessage()]
    assert len(warns) == 1 and "connection refused" in warns[0].getMessage()  # 30초에 한 번이라 몰아서 찍지 않는다
