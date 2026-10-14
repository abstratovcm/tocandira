"""Minimal Universal Hive Protocol client and player specs.

A player spec is a comma separated string, e.g.
    "depth=4"                      nokamute, fixed depth 4
    "seconds=1,Aggression=5"       nokamute, 1 s/move, UHP option Aggression=5
    "cmd=/path/to/engine,depth=3"  any UHP engine
    "cmd=ref,seconds=1"            the frozen reference build (reference/nokamute-1.0.3)
Keys: name, cmd, depth, seconds; every other key is sent as `options set Key Value`.
NumThreads defaults to 1 so games can run in parallel.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import IO

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The engine build; TOCANDIRA_ENGINE overrides it (Colab, other checkouts).
NOKAMUTE = os.environ.get("TOCANDIRA_ENGINE") or os.path.join(
    REPO_ROOT, "engine", "nokamute", "target", "release", "nokamute"
)
# Frozen reference opponent, built by scripts/build_reference.sh. Spec shorthand: cmd=ref;
# TOCANDIRA_REFERENCE overrides the path.
REFERENCE = os.environ.get("TOCANDIRA_REFERENCE") or os.path.join(
    REPO_ROOT, "reference", "nokamute-1.0.3"
)


class UhpError(RuntimeError):
    """An engine died, rejected a move, or answered a command with `err`."""


@dataclass
class PlayerSpec:
    """How to launch and limit one engine; see the module docstring for the text form."""

    cmd: str = NOKAMUTE
    depth: int | None = None
    seconds: float | None = None
    options: dict[str, str] = field(default_factory=dict)
    name: str = ""

    @classmethod
    def parse(cls, text: str) -> PlayerSpec:
        """Parse the comma separated spec text; needs `depth=` or `seconds=`."""
        spec = cls()
        for item in filter(None, (t.strip() for t in text.split(","))):
            key, _, value = item.partition("=")
            if key == "cmd":
                spec.cmd = REFERENCE if value == "ref" else value
            elif key == "depth":
                spec.depth = int(value)
            elif key == "seconds":
                spec.seconds = float(value)
            elif key == "name":
                spec.name = value
            else:
                spec.options[key] = value
        if spec.depth is None and spec.seconds is None:
            raise ValueError(f"player spec needs depth= or seconds=: {text!r}")
        spec.options.setdefault("NumThreads", "1")
        if not spec.name:
            limit = f"d{spec.depth}" if spec.depth is not None else f"{spec.seconds}s"
            extra = ",".join(f"{k}={v}" for k, v in spec.options.items() if k != "NumThreads")
            spec.name = spec.binary + " " + limit + (" " + extra if extra else "")
        return spec

    @property
    def binary(self) -> str:
        """The executable's name, without its directory or arguments such as `--nnue`."""
        return os.path.basename(self.cmd.split()[0])

    @property
    def is_nokamute(self) -> bool:
        """Whether the engine understands nokamute's unofficial commands (`seconds`, `search`)."""
        return self.binary.startswith("nokamute")

    def limit_args(self) -> str:
        """Argument string for `bestmove` / `search`."""
        if self.depth is not None:
            return f"depth {self.depth}"
        assert self.seconds is not None
        if self.is_nokamute:
            return f"seconds {self.seconds:g}"
        secs = max(1, round(self.seconds))
        return f"time {secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def game_state(game_string: str) -> str:
    """State field of a UHP game string: NotStarted, InProgress, Draw, WhiteWins or BlackWins."""
    return game_string.split(";")[1]


class Engine:
    """One UHP engine process. Every command returns the lines printed before `ok`."""

    def __init__(self, spec: PlayerSpec | None = None):
        self.spec = spec or PlayerSpec(depth=1)
        self.proc = subprocess.Popen(
            self.spec.cmd.split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self._in: IO[str] = self.proc.stdin
        self._out: IO[str] = self.proc.stdout
        self.banner = self._read()  # engines print `id ...` then `ok` on startup
        for key, value in self.spec.options.items():
            self.cmd(f"options set {key} {value}")

    def _read(self) -> list[str]:
        lines: list[str] = []
        while True:
            line = self._out.readline()
            if not line:
                raise UhpError(f"engine exited: {self.spec.cmd}")
            line = line.rstrip("\n")
            if line == "ok":
                return lines
            lines.append(line)

    def cmd(self, command: str) -> list[str]:
        """Send one command line and return the reply lines (raises on `err`)."""
        self._in.write(command + "\n")
        self._in.flush()
        lines = self._read()
        if lines and lines[0].startswith("err "):
            raise UhpError(f"{command!r} -> {lines[0]}")
        return lines

    def newgame(self, game_type: str = "Base+MLP") -> str:
        """Start a game and return its game string."""
        return self.cmd(f"newgame {game_type}")[0]

    def validmoves(self) -> list[str]:
        """Legal moves in UHP notation (a lone `pass` when there is none)."""
        return self.cmd("validmoves")[0].split(";")

    def play(self, move: str) -> str:
        """Play a move and return the new game string; raises UhpError on an invalid move."""
        line = self.cmd(f"play {move}")[0]
        if line.startswith("invalidmove"):
            raise UhpError(line)
        return line

    def bestmove(self) -> str:
        """Search with the spec's limit and return the chosen move."""
        return self.cmd(f"bestmove {self.spec.limit_args()}")[0]

    def search(self) -> tuple[str, int | None, int]:
        """Nokamute extension: (move, root score for the side to move, pv length)."""
        move, score, pvlen = self.cmd(f"search {self.spec.limit_args()}")[0].split(";")
        return move, (int(score) if score else None), int(pvlen)

    def eval(self) -> int:
        """Fork extension: the hand tuned static evaluation, side to move's perspective."""
        return int(self.cmd("eval")[0])

    def close(self) -> None:
        """Ask the engine to exit, killing it if it does not."""
        try:
            self._in.write("exit\n")
            self._in.flush()
            self.proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
