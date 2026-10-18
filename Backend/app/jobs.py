"""작업 큐와 작업자(spec/08 §2). 외부 큐 없이 job 표 + 프로세스 안 작업자.

작업자: 폴링 스레드 1개가 job 표에서 FOR UPDATE SKIP LOCKED 로 하나씩 가져와 실행 스레드(동시 실행 상한 MAX_RUNNING)에 넘긴다.
스레드는 모두 데몬이다. 종료 때 실행 중인 작업을 기다리지 않고, 그 작업은 다음 시작 때 failed(interrupted)가 된다.
서버 시작 때 running 이던 작업은 failed(interrupted). 만료된 세션은 시작 때와 매시간 지운다.
작업 취소(DELETE)와 재시작 후 자동 재실행은 만들지 않는다.
"""
import logging
import secrets
import threading
import time
import psycopg
from psycopg.types.json import Jsonb

from app.embedder import OLLAMA_DOWN, OllamaEmbedder
from app.errors import ApiError

log = logging.getLogger("lci.jobs")
MATCH_FAILED_DETAIL = "매칭 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."  # A21 error.detail 은 코드별 고정 문장(원문은 로그에만)
MAX_RUNNING = 2  # 매칭 동시 실행 상한(설정값)
QUEUE_LIMIT = 10  # 대기 + 실행 합 상한(설정값). 넘으면 A01 이 429 QUEUE_FULL
POLL_SECONDS = 0.5
CLEANUP_SECONDS = 3600
STAGES = ("정규화", "후보 검색", "판정·환산")


def new_stages():
    return [{"name": n, "state": "queued", "done": 0, "total": 0, "started_at": None, "finished_at": None} for n in STAGES]


def enqueue(conn, session_id):
    """conn 의 트랜잭션 안에서 match 작업을 만든다. 대기+실행이 상한이면 429."""
    conn.execute("SELECT pg_advisory_xact_lock(4201)")  # 동시에 올라온 업로드가 상한을 함께 넘지 않게
    busy = conn.execute("SELECT count(*) FROM job WHERE state IN ('queued', 'running')").fetchone()[0]
    if busy >= QUEUE_LIMIT:
        raise ApiError(429, "지금 처리 중인 작업이 많습니다. 잠시 후 다시 시도해 주세요.", "QUEUE_FULL")
    job_id = f"job-{secrets.token_hex(6)}"
    conn.execute("INSERT INTO job (job_id, kind, params, stages) VALUES (%s, 'match', %s, %s)",
                 (job_id, Jsonb({"session_id": session_id}), Jsonb(new_stages())))
    return job_id


def recover_interrupted(conninfo_):
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        return conn.execute(
            "UPDATE job SET state = 'failed', finished_at = now(), error = %s WHERE state = 'running'",
            (Jsonb({"detail": "서버가 다시 시작되어 작업이 중단되었습니다. 파일을 다시 올려 주세요.", "code": "interrupted"}),)).rowcount


def cleanup_expired(conninfo_):
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        return conn.execute("DELETE FROM bom_project WHERE expires_at < now()").rowcount


def set_stage(conninfo_, job_id, name, **fields):
    """단계 하나의 값을 바꾼다(진행 표시용, 매칭 트랜잭션과 다른 접속)."""
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        stages = conn.execute("SELECT stages FROM job WHERE job_id = %s", (job_id,)).fetchone()[0]
        for s in stages:
            if s["name"] == name:
                for k, v in fields.items():
                    s[k] = conn.execute("SELECT now()").fetchone()[0].isoformat() if v == "now" else v
        conn.execute("UPDATE job SET stages = %s WHERE job_id = %s", (Jsonb(stages), job_id))


def default_embedder(conninfo_):
    with psycopg.connect(conninfo_) as conn:
        row = conn.execute("SELECT model_name FROM index_version WHERE active").fetchone()
    return OllamaEmbedder((row[0] if row else "ollama:bge-m3").split(":", 1)[-1])


def run_match_job(conninfo_, job_id, make_embedder=default_embedder):
    """작업 하나를 실행한다. 실패해도 세션·행은 지우지 않는다."""
    from app.bom.match import match_project
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        session_id = conn.execute("SELECT params->>'session_id' FROM job WHERE job_id = %s", (job_id,)).fetchone()[0]
        total_rows = conn.execute("SELECT count(*) FROM bom_item WHERE project_id = %s", (session_id,)).fetchone()[0]
    try:
        # 정규화는 업로드 때 끝났다(행을 저장할 때 clean 을 만든다)
        set_stage(conninfo_, job_id, "정규화", state="succeeded", done=total_rows, total=total_rows, started_at="now", finished_at="now")
        set_stage(conninfo_, job_id, "후보 검색", state="running", started_at="now")
        embedder = make_embedder(conninfo_)
        digest = embedder.model_digest() if hasattr(embedder, "model_digest") else (None, "임베더가 digest 를 주지 않음")
        with psycopg.connect(conninfo_) as conn:
            result = match_project(conn, session_id, embedder, digest=digest,
                                   progress=lambda done, total: set_stage(conninfo_, job_id, "후보 검색", done=done, total=total))
        set_stage(conninfo_, job_id, "후보 검색", state="succeeded", finished_at="now")
        # 판정·환산(Veto·환산)은 T9b 전까지 건수만 채우고 바로 끝낸다
        set_stage(conninfo_, job_id, "판정·환산", state="succeeded", done=total_rows, total=total_rows, started_at="now", finished_at="now")
        finish(conninfo_, job_id, "succeeded", result={"session_id": session_id, "queries": result["queries"],
                                                       "cache_hits": result["cache_hits"], "run_id": result["run_id"]})
    except SystemExit as e:  # 임베더는 Ollama 에 닿지 못하면 SystemExit(OLLAMA_DOWN…) 로 멈춘다
        code = "EMBEDDER_UNAVAILABLE" if str(e).startswith(OLLAMA_DOWN) else "MATCH_FAILED"
        log.warning("매칭 작업 %s 실패(%s): %s | 원인: %r", job_id, code, e, e.__cause__)  # 원문은 로그에만
        fail(conninfo_, job_id, OLLAMA_DOWN if code == "EMBEDDER_UNAVAILABLE" else MATCH_FAILED_DETAIL, code)
    except Exception as e:  # noqa: BLE001  작업자는 어떤 오류든 작업 실패로 남기고 다음 작업으로 간다
        log.exception("매칭 작업 %s 실패", job_id)
        fail(conninfo_, job_id, MATCH_FAILED_DETAIL, "MATCH_FAILED")


def fail(conninfo_, job_id, detail, code):
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        stages = conn.execute("SELECT stages FROM job WHERE job_id = %s", (job_id,)).fetchone()[0]
        for s in stages:
            if s["state"] == "running":
                s["state"] = "failed"
        conn.execute("UPDATE job SET stages = %s WHERE job_id = %s", (Jsonb(stages), job_id))
    finish(conninfo_, job_id, "failed", error={"detail": detail, "code": code})


def finish(conninfo_, job_id, state, result=None, error=None):
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        conn.execute("UPDATE job SET state = %s, result = %s, error = %s, finished_at = now() WHERE job_id = %s",
                     (state, Jsonb(result or {}), Jsonb(error) if error else None, job_id))


def claim(conninfo_):
    """대기 중인 match 작업 하나를 running 으로 바꿔 가져온다. 없으면 None."""
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        row = conn.execute(
            "UPDATE job SET state = 'running', started_at = now() WHERE job_id = ("
            " SELECT job_id FROM job WHERE state = 'queued' AND kind = 'match' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)"
            " RETURNING job_id").fetchone()
    return row[0] if row else None


class Worker:
    def __init__(self, conninfo_, make_embedder=default_embedder, max_running=MAX_RUNNING):
        self.conninfo, self.make_embedder = conninfo_, make_embedder
        self.slots = threading.Semaphore(max_running)
        self.stop_event = threading.Event()
        self.last_warned = float("-inf")
        self.thread = threading.Thread(target=self.loop, name="job-poller", daemon=True)

    def start(self):
        recover_interrupted(self.conninfo)
        cleanup_expired(self.conninfo)
        self.thread.start()

    def loop(self):
        last_cleanup = time.monotonic()
        while not self.stop_event.is_set():
            try:
                if time.monotonic() - last_cleanup > CLEANUP_SECONDS:
                    cleanup_expired(self.conninfo)
                    last_cleanup = time.monotonic()
                if self.slots.acquire(timeout=POLL_SECONDS):
                    job_id = None if self.stop_event.is_set() else claim(self.conninfo)  # 멈추는 중에는 새로 가져오지 않는다
                    if job_id:
                        threading.Thread(target=self.run, args=(job_id,), name=f"match-{job_id}", daemon=True).start()
                        continue
                    self.slots.release()
            except psycopg.Error as e:  # DB 가 잠시 끊겨도 폴링은 계속한다. 다만 흔적은 남긴다(끊긴 동안 0.5초마다 쓰지 않게 30초에 한 번)
                if time.monotonic() - self.last_warned > 30:
                    self.last_warned = time.monotonic()
                    log.warning("작업 폴링 중 DB 오류(계속 재시도): %s", e)
            self.stop_event.wait(POLL_SECONDS)

    def run(self, job_id):
        try:
            run_match_job(self.conninfo, job_id, self.make_embedder)
        finally:
            self.slots.release()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=3)  # 폴링은 POLL_SECONDS 안에 멈춘다. 실행 중인 매칭 스레드는 합류하지 않는다


def queued_position(conn, job_id):
    row = conn.execute("SELECT count(*) + 1 FROM job WHERE state = 'queued' AND created_at < (SELECT created_at FROM job WHERE job_id = %s)",
                       (job_id,)).fetchone()
    return row[0]
