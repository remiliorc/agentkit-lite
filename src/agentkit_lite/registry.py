"""Directory of AGENT.md files with hot reload on change.

Layout: ``agents/<name>/AGENT.md`` or ``agents/<name>.md``. Edit a file and the
next ``get()`` picks up the new version; a broken edit keeps serving the last
valid version and reports the error, so a typo cannot take an app down.
"""

from __future__ import annotations

from pathlib import Path

from .spec import AgentSpec, SpecError, load


class Registry:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._cache: dict[str, AgentSpec] = {}
        self.errors: dict[str, str] = {}
        self.refresh()

    def _files(self) -> list[Path]:
        found = list(self.root.glob("*/AGENT.md")) + list(self.root.glob("*.md"))
        return sorted(p for p in found if p.is_file())

    def refresh(self) -> None:
        files = set(self._files())
        # forget agents whose file was deleted or renamed
        for name, spec in list(self._cache.items()):
            if spec.path not in files:
                del self._cache[name]
        for key in list(self.errors):
            if Path(key) not in files:
                del self.errors[key]
        for f in sorted(files):
            key = str(f)
            cached = next((s for s in self._cache.values() if s.path == f), None)
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if cached and cached.mtime == mtime:
                continue
            try:
                spec = load(f)
            except SpecError as e:
                self.errors[key] = str(e)
                continue
            self.errors.pop(key, None)
            if cached and cached.name != spec.name:   # agent renamed in place
                self._cache.pop(cached.name, None)
            other = self._cache.get(spec.name)
            if other and other.path != f:
                self.errors[key] = f"duplicate agent name '{spec.name}' (also in {other.path})"
                continue
            self._cache[spec.name] = spec

    def names(self) -> list[str]:
        self.refresh()
        return sorted(self._cache)

    def get(self, name: str) -> AgentSpec:
        self.refresh()
        if name not in self._cache:
            raise KeyError(f"unknown agent '{name}'")
        return self._cache[name]
