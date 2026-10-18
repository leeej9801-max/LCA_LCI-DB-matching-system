"""임베딩. 파이썬에 모델을 올리지 않고 사용자 PC의 Ollama(bge-m3)를 HTTP로 부른다.

임베더 인터페이스: `model_name`(저장 키) + `embed(list[str]) -> list[list[float]]`(길이 1, 1024차원). 시험은 가짜 임베더로 바꿔 끼운다.
"""
import logging
import math
import os
import time

import httpx

log = logging.getLogger("lci.embedder")
DIM = 1024
BATCH = 32
DEFAULT_HOST = "http://127.0.0.1:11434"
RETRY_DELAYS = (1, 3)  # 다시 시도 전 대기(초), 최대 2번
RETRYABLE = (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)  # 연결 실패·끊김
OLLAMA_DOWN = "Ollama에 접속하지 못했습니다. 실행 중인지, `ollama pull bge-m3`를 했는지 확인하세요"


def l2_normalize(v, dim=DIM):
    """길이 1로 만든다. 차원이 다르면 멈춘다(저장 열이 vector(1024))."""
    if len(v) != dim:
        raise SystemExit(f"임베딩 차원이 {len(v)}입니다. {dim}차원이 필요합니다(bge-m3)")
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        raise SystemExit("임베딩 벡터가 0입니다")
    return [x / n for x in v]


class OllamaEmbedder:
    def __init__(self, model="bge-m3", host=None, transport=None):
        host = host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
        if "://" not in host:  # Ollama 의 OLLAMA_HOST 는 '127.0.0.1:11434' 처럼 scheme 없이 쓰기도 한다
            host = "http://" + host
        self.model = model
        self.model_name = f"ollama:{model}"
        self.client = httpx.Client(base_url=host, timeout=120, transport=transport)

    def model_digest(self):
        """(digest, None) 또는 (None, 사유). Ollama GET /api/tags 의 해당 모델 digest — 재현성 기록용."""
        try:
            r = self.client.get("/api/tags")
        except httpx.TransportError as e:
            return None, f"Ollama 접속 실패: {type(e).__name__}"
        if r.status_code != 200:
            return None, f"/api/tags HTTP {r.status_code}"
        names = {self.model, f"{self.model}:latest"}
        for m in r.json().get("models", []):
            if m.get("name") in names or m.get("model") in names:
                return m.get("digest"), None
        return None, f"/api/tags 에 {self.model} 이 없음"

    def embed(self, texts):
        out = []
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            r = self.post_embed(batch)
            if r.status_code != 200:  # 모델을 받지 않았으면 404 등
                log.warning("Ollama 응답 오류 HTTP %s: %s", r.status_code, r.text[:500])  # 원문은 로그에만. 사용자에게는 고정 문장
                raise SystemExit(OLLAMA_DOWN)
            vectors = r.json()["embeddings"]
            if len(vectors) != len(batch):
                raise SystemExit(f"Ollama가 {len(batch)}개 중 {len(vectors)}개만 돌려주었습니다")
            out += [l2_normalize(v) for v in vectors]
        return out

    def post_embed(self, batch):
        """연결 실패·끊김일 때만 RETRY_DELAYS 만큼 쉬고 다시 보낸다. 시간 초과·응답 오류는 바로 돌려준다(호출자가 멈춘다)."""
        for delay in (*RETRY_DELAYS, None):
            try:
                return self.client.post("/api/embed", json={"model": self.model, "input": batch})
            except RETRYABLE as e:
                if delay is None:
                    raise SystemExit(OLLAMA_DOWN) from e
                time.sleep(delay)
            except httpx.TransportError as e:  # 시간 초과 등
                raise SystemExit(OLLAMA_DOWN) from e
