from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import errors
from app.api import datasets, evaluation, jobs, sample, sessions
from app.db.connection import conninfo
from app.jobs import Worker


@asynccontextmanager
async def lifespan(app):
    # 매칭 작업자: 시작 때 중단된 작업 정리·만료 세션 삭제 후 폴링 시작
    worker = Worker(conninfo())
    worker.start()
    app.state.worker = worker
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(lifespan=lifespan)
errors.install(app)
app.include_router(datasets.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(sample.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")

@app.get("/")
def read_root():
  return {"Hello": "World"}
