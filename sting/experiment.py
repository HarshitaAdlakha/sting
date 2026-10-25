"""Run a grid of episodes concurrently; skips episodes that already have a log (resumable).

  python -m sting.experiment --models gpt-4.1-mini --arms none direct --seeds 3 --persona plain
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from openai import AsyncOpenAI

from .run import ROOT, episode_path, load_env, run_episode


async def main(args):
    load_env()
    client = AsyncOpenAI()
    results = Path(args.results)
    jobs = [(m, a, p, s) for m in args.models for p in args.persona for a in args.arms
            for s in range(args.seed_start, args.seed_start + args.seeds)]
    todo = [j for j in jobs if not episode_path(results, *j[:3], j[3], args.channel).exists()]
    print(f"{len(jobs)} episodes in grid, {len(todo)} to run, ~{len(todo) * 2 * args.rounds} calls")
    sem = asyncio.Semaphore(args.concurrency)
    done = 0
    t0 = time.time()

    async def one(m, a, p, s):
        nonlocal done
        async with sem:
            try:
                await run_episode(client, model=m, arm=a, persona=p, seed=s, rounds=args.rounds,
                                  channel=args.channel, out=episode_path(results, m, a, p, s, args.channel))
            except Exception as e:
                print(f"FAILED {m} {p} {a} s{s}: {e!r}")
                return
            done += 1
            print(f"[{done}/{len(todo)}] {m} {p} {a} s{s}  ({time.time() - t0:.0f}s)", flush=True)

    await asyncio.gather(*(one(*j) for j in todo))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gpt-4.1-mini"])
    ap.add_argument("--arms", nargs="+", default=["none", "benign", "hint", "direct"])
    ap.add_argument("--persona", nargs="+", default=["plain"], choices=["plain", "compliance", "collude"])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=16)
    ap.add_argument("--channel", default="all", choices=["all", "uc_only"])
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--results", default=str(ROOT / "results"))
    asyncio.run(main(ap.parse_args()))
