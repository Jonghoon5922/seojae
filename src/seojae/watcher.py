"""파일 감시 증분 색인.

폴더에 파일을 던져 넣으면 알아서 색인된다. 재색인 명령을 사람이 기억할 필요가 없어야
"폴더에 꽂아두면 끝"이라는 약속이 성립한다.

파일 시스템 이벤트를 그대로 믿고 곧바로 색인하면 안 된다. 두 가지 때문이다.

1. **에디터는 저장 한 번에 이벤트를 여러 개 뱉는다.** (쓰기 → 임시파일 → 이름 변경 …)
   그래서 잠잠해질 때까지 기다렸다가 한 번만 처리한다(디바운스).
2. **복사가 끝나기 전에 이벤트가 먼저 온다.** 특히 윈도우에서 큰 파일을 복사하면
   생성 이벤트 시점에 파일이 아직 잠겨 있거나 내용이 잘려 있다.
   그래서 실패하면 잠시 뒤 다시 시도한다.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .index import forget_one, index_one
from .paths import DATA_DIRNAME, SUPPORTED_EXTS, is_inside

# 마지막 이벤트 이후 이만큼 조용하면 처리한다
DEFAULT_DEBOUNCE = 1.0

# 파일이 아직 잠겨 있을 때 다시 시도하는 간격 (초)
RETRY_DELAYS = (0.5, 1.5, 3.0)

# 대기 목록을 살펴보는 주기
TICK = 0.2


def _is_watchable(root: Path, path: Path) -> bool:
    """색인 대상 파일인지. 숨김·색인 폴더·루트 밖은 제외한다."""
    if path.suffix.lower() not in SUPPORTED_EXTS:
        return False
    try:
        relative = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return not any(part.startswith(".") or part == DATA_DIRNAME for part in relative.parts)


class _Handler(FileSystemEventHandler):
    """이벤트를 판단하지 않고 모으기만 한다. 판단은 워커가 한다."""

    def __init__(self, watcher: ShelfWatcher) -> None:
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        self._touch(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._touch(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.mark_deleted(Path(str(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._watcher.mark_deleted(Path(str(event.src_path)))
        dest = getattr(event, "dest_path", None)
        if dest:
            self._watcher.mark_changed(Path(str(dest)))

    def _touch(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.mark_changed(Path(str(event.src_path)))


class ShelfWatcher:
    """루트를 감시하며 바뀐 파일만 다시 색인한다.

    DB 연결과 락은 밖에서 받는다. MCP 서버와 같은 연결을 공유해야
    검색이 방금 들어온 파일을 곧바로 볼 수 있다.
    """

    def __init__(
        self,
        root: Path,
        conn,
        lock: threading.Lock,
        debounce: float = DEFAULT_DEBOUNCE,
        on_change: Callable[[str, str], None] | None = None,
    ) -> None:
        self.root = root
        self._conn = conn
        self._lock = lock
        self._debounce = debounce
        self._on_change = on_change

        self._pending: dict[Path, float] = {}  # 경로 → 마지막 이벤트 시각
        self._deleted: set[Path] = set()
        self._retries: dict[Path, int] = {}
        self._state = threading.Lock()

        self._observer: Observer | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    # ── 이벤트 수집 ────────────────────────────────────────────────────────

    def mark_changed(self, path: Path) -> None:
        if not _is_watchable(self.root, path):
            return
        with self._state:
            self._pending[path] = time.monotonic()
            self._deleted.discard(path)

    def mark_deleted(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_EXTS:
            return
        if not is_inside(self.root, path.parent):
            return
        with self._state:
            self._deleted.add(path)
            self._pending.pop(path, None)
            self._retries.pop(path, None)

    # ── 수명 ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.root), recursive=True)
        self._observer.start()

        self._worker = threading.Thread(target=self._run, name="seojae-watcher", daemon=True)
        self._worker.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout)
            self._observer = None
        if self._worker is not None:
            self._worker.join(timeout)
            self._worker = None

    # ── 처리 ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.wait(TICK):
            try:
                self.process_due()
            except Exception as e:  # 감시 스레드가 죽으면 자동 색인이 조용히 멈춘다
                self._report("감시 오류", str(e))

    def _due(self) -> tuple[list[Path], list[Path]]:
        now = time.monotonic()
        with self._state:
            ready = [p for p, seen in self._pending.items() if now - seen >= self._debounce]
            for path in ready:
                self._pending.pop(path, None)
            deleted = list(self._deleted)
            self._deleted.clear()
        return ready, deleted

    def process_due(self) -> int:
        """디바운스가 끝난 것들을 처리한다. 처리한 건수를 돌려준다."""
        changed, deleted = self._due()
        handled = 0

        for path in deleted:
            with self._lock:
                if forget_one(self.root, self._conn, path):
                    handled += 1
                    self._report("삭제", path.name)

        for path in changed:
            if not path.exists():  # 디바운스 사이에 지워졌다
                with self._lock:
                    forget_one(self.root, self._conn, path)
                continue
            if self._index(path):
                handled += 1

        return handled

    def _index(self, path: Path) -> bool:
        try:
            with self._lock:
                stats = index_one(self.root, self._conn, path)
        except (PermissionError, OSError) as e:
            return self._retry_later(path, str(e))

        self._retries.pop(path, None)
        if stats.indexed:
            self._report("색인", f"{path.name} (청크 {stats.chunks})")
            return True
        if stats.failed:
            self._report("읽기 실패", path.name)
            return True
        return False

    def _retry_later(self, path: Path, reason: str) -> bool:
        """복사가 끝나기 전이라 파일이 잠겨 있을 수 있다. 조금 뒤 다시 본다."""
        attempt = self._retries.get(path, 0)
        if attempt >= len(RETRY_DELAYS):
            self._retries.pop(path, None)
            self._report("포기", f"{path.name} — {reason}")
            return False

        self._retries[path] = attempt + 1
        with self._state:
            self._pending[path] = time.monotonic() + RETRY_DELAYS[attempt] - self._debounce
        return False

    def _report(self, kind: str, detail: str) -> None:
        if self._on_change:
            self._on_change(kind, detail)
