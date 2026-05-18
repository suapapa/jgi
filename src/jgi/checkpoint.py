"""실행 단계별 결과를 디스크에 저장해 중간 실패 후 재개를 지원한다.

레이아웃::

    cache/
      days7_2026-05-16/
        state.json        # 진행 상태 (last_scanned_page 등)
        metas.jsonl       # 수집된 PostMeta — 한 줄당 하나, append-only
        bodies.jsonl      # 본문이 채워진 Post — 한 줄당 하나, append-only
        analysis.json     # LLM 결과 AnalysisResult

같은 `days`와 같은 날짜로 다시 실행하면 자동 재개된다.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Iterator

from .models import AnalysisResult, Post, PostMeta


class RunCheckpoint:
    def __init__(
        self,
        cache_dir: Path | str,
        days: int | None = None,
        run_date: date | None = None,
        *,
        run_id: str | None = None,
    ):
        if run_id is not None:
            self.run_id = run_id
        else:
            if days is None:
                raise ValueError("days or run_id required")
            run_date = run_date or date.today()
            self.run_id = f"days{days}_{run_date:%Y-%m-%d}"
        self.dir = Path(cache_dir) / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.metas_path = self.dir / "metas.jsonl"
        self.bodies_path = self.dir / "bodies.jsonl"
        self.analysis_path = self.dir / "analysis.json"
        self._state: dict | None = None

    def _ensure_state(self) -> dict:
        if self._state is not None:
            return self._state
        if self.state_path.exists():
            self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self._state = {}
        return self._state

    def _persist_state(self) -> None:
        state = self._ensure_state()
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ----- state -----
    def load_state(self) -> dict:
        return dict(self._ensure_state())

    def save_state(self, **fields) -> None:
        state = self._ensure_state()
        state.update(fields)
        self._persist_state()

    def _count_jsonl_lines(self, path: Path) -> int:
        if not path.exists():
            return 0
        count = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                count += chunk.count(b"\n")
        return count

    # ----- metas (append-only jsonl) -----
    def iter_metas(self) -> Iterator[PostMeta]:
        if not self.metas_path.exists():
            return
        with self.metas_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield PostMeta.model_validate_json(line)

    def append_metas(self, posts: list[PostMeta]) -> None:
        if not posts:
            return
        with self.metas_path.open("a", encoding="utf-8") as f:
            f.writelines(p.model_dump_json() + "\n" for p in posts)
        state = self._ensure_state()
        state["meta_count"] = int(state.get("meta_count", 0)) + len(posts)

    # ----- bodies (append-only jsonl) -----
    def load_bodies(self) -> dict[int, Post]:
        result: dict[int, Post] = {}
        if not self.bodies_path.exists():
            return result
        with self.bodies_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    p = Post.model_validate_json(line)
                    result[p.no] = p
        return result

    def append_body(self, post: Post) -> None:
        with self.bodies_path.open("a", encoding="utf-8") as f:
            f.write(post.model_dump_json())
            f.write("\n")
        state = self._ensure_state()
        state["body_count"] = int(state.get("body_count", 0)) + 1

    # ----- analysis result -----
    def load_analysis(self) -> AnalysisResult | None:
        if not self.analysis_path.exists():
            return None
        return AnalysisResult.model_validate_json(
            self.analysis_path.read_text(encoding="utf-8")
        )

    def save_analysis(self, result: AnalysisResult) -> None:
        self.analysis_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )

    # ----- housekeeping -----
    def reset(self) -> None:
        """캐시 디렉토리 전체 삭제 후 재생성."""
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._state = {}

    def reset_analysis(self) -> None:
        if self.analysis_path.exists():
            self.analysis_path.unlink()

    def summary(self) -> str:
        state = self._ensure_state()
        n_metas = int(state["meta_count"]) if "meta_count" in state else self._count_jsonl_lines(
            self.metas_path
        )
        n_bodies = int(state["body_count"]) if "body_count" in state else self._count_jsonl_lines(
            self.bodies_path
        )
        has_analysis = self.analysis_path.exists()
        return (
            f"run_id={self.run_id} "
            f"page={state.get('last_scanned_page', 0)} "
            f"metas={n_metas} bodies={n_bodies} "
            f"analysis={'O' if has_analysis else 'X'}"
        )
