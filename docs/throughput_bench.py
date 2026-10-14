#!/usr/bin/env python3
"""Throughput benchmark for nokamute over UHP.

games <depth> <n_games> <workers>   : self play games, random openings, single thread each
label <n_games> <workers> <maxdepth>: play depth-2 games, time `bestmove depth d` on every
                                      position for d=1..maxdepth (each worker labels its own game)
Output: JSON lines to stdout, summary to stderr.
"""
import json
import random
import subprocess
import sys
import time
from multiprocessing import Pool

BIN = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))), "engine", "nokamute", "target", "release", "nokamute")
PLY_CAP = 300

class Uhp:
    def __init__(self):
        self.p = subprocess.Popen([BIN, "uhp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self._read()  # unsolicited startup banner ends with "ok"
        self.cmd("options set NumThreads 1")
    def cmd(self, s):
        self.p.stdin.write(s + "\n"); self.p.stdin.flush()
        return self._read(s)
    def _read(self, s=""):
        lines = []
        while True:
            l = self.p.stdout.readline()
            if not l: raise RuntimeError("engine died on: " + s)
            l = l.rstrip("\n")
            if l == "ok": return lines
            lines.append(l)
    def close(self):
        try: self.cmd("exit")
        except (OSError, RuntimeError): pass  # engine may already be gone
        self.p.kill()

def state(gs): return gs.split(";")[1]

def play_game(eng, depth, seed, label_depths=()):
    rng = random.Random(seed)
    gs = eng.cmd("newgame Base+MLP")[0]
    plies, move_times, labels = 0, [], []
    while state(gs) in ("NotStarted", "InProgress") and plies < PLY_CAP:
        if plies < 2:
            # random opening: diversify games (engine's RandomOpening only randomizes nokamute's own first moves)
            moves = eng.cmd("validmoves")[0].split(";")
            mv = rng.choice(moves)
        else:
            for d in label_depths:
                t = time.perf_counter(); eng.cmd(f"bestmove depth {d}"); labels.append((plies, d, time.perf_counter() - t))
            t = time.perf_counter(); mv = eng.cmd(f"bestmove depth {depth}")[0]; move_times.append(time.perf_counter() - t)
        gs = eng.cmd(f"play {mv}")[0]
        if gs.startswith("invalidmove"): raise RuntimeError(gs)
        plies += 1
    return {"result": state(gs), "plies": plies, "search_s": sum(move_times), "max_move_s": max(move_times, default=0), "labels": labels}

def game_worker(args):
    depth, seed = args
    eng = Uhp(); t = time.perf_counter()
    try:
        r = play_game(eng, depth, seed); r.update(depth=depth, seed=seed, wall_s=time.perf_counter() - t); return r
    finally: eng.close()

def label_worker(args):
    seed, maxd = args
    eng = Uhp()
    try: return play_game(eng, 2, seed, label_depths=range(1, maxd + 1))
    finally: eng.close()

def pct(xs, q): xs = sorted(xs); return xs[min(len(xs) - 1, int(q * len(xs)))]

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "games":
        depth, n, workers = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
        t0 = time.perf_counter()
        with Pool(workers) as pool: rs = pool.map(game_worker, [(depth, 1000 * depth + i) for i in range(n)])
        wall = time.perf_counter() - t0
        for r in rs: r.pop("labels"); print(json.dumps(r))
        w = [r["wall_s"] for r in rs]; p = [r["plies"] for r in rs]
        res = {}
        for r in rs: res[r["result"]] = res.get(r["result"], 0) + 1
        print(f"depth {depth}: {n} games on {workers} workers in {wall:.1f}s wall | per game median {pct(w,.5):.2f}s p90 {pct(w,.9):.2f}s max {max(w):.2f}s | plies median {pct(p,.5)} max {max(p)} | results {res}", file=sys.stderr)
    elif mode == "label":
        n, workers, maxd = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
        with Pool(workers) as pool: rs = pool.map(label_worker, [(5000 + i, maxd) for i in range(n)])
        by = {}
        for r in rs:
            for ply, d, s in r["labels"]: by.setdefault(d, []).append((ply, s))
        for d in sorted(by):
            xs = [s for _, s in by[d]]; late = [s for ply, s in by[d] if ply >= 30]
            print(json.dumps({"depth": d, "n": len(xs), "mean_s": sum(xs)/len(xs), "median_s": pct(xs,.5), "p90_s": pct(xs,.9), "max_s": max(xs), "mean_s_after_ply30": (sum(late)/len(late) if late else None)}))
        print(f"labeled {sum(len(r['labels']) for r in rs)//maxd} positions from {n} games", file=sys.stderr)
