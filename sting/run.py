"""Run one episode: two LLM sellers and one scripted undercover firm in a repeated market."""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from pathlib import Path

from openai import AsyncOpenAI

from .agents import Undercover, parse_response, system_prompt, user_prompt
from .market import Market

ROOT = Path(__file__).resolve().parents[1]
NAME_POOL = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Hazel", "Juniper", "Linden", "Maple",
             "Oak", "Pine", "Rowan", "Spruce", "Willow", "Yew"]


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def is_reasoning(model: str) -> bool:
    return model.startswith(("gpt-5", "o3", "o4"))


async def chat(client: AsyncOpenAI, model: str, messages: list[dict], seed: int) -> tuple[str, dict]:
    kw = dict(model=model, messages=messages, response_format={"type": "json_object"})
    if is_reasoning(model):
        kw.update(reasoning_effort="low", max_completion_tokens=4000)
    else:
        kw.update(temperature=1.0, max_tokens=700, seed=seed)
    for attempt in range(6):
        try:
            r = await client.chat.completions.create(**kw)
            u = r.usage
            return r.choices[0].message.content or "", {"in": u.prompt_tokens, "out": u.completion_tokens}
        except Exception as e:  # rate limits and transient errors
            if attempt == 5:
                raise
            await asyncio.sleep(2 ** attempt + random.random())
    raise RuntimeError("unreachable")


async def run_episode(client: AsyncOpenAI, *, model: str, arm: str, persona: str, seed: int,
                      rounds: int = 16, offer_round: int = 5, follow_round: int = 10, channel: str = "all",
                      out: Path) -> dict:
    """channel="all": sellers can message every firm. channel="uc_only": sellers can message only the
    undercover firm, so any coordination between the two sellers has to go through prices."""
    rng = random.Random(seed)
    names = [f"{n} Co." for n in rng.sample(NAME_POOL, 3)]
    sellers, uc_name = names[:2], names[2]
    mkt = Market(n=3)
    uc = Undercover(uc_name, arm, mkt.nash, mkt.monopoly, offer_round, follow_round)
    others = {s: [o for o in names if o != s] for s in sellers}
    recipients = {s: (others[s] if channel == "all" else [uc_name]) for s in sellers}
    sys = {s: system_prompt(s, others[s], persona, recipients[s]) for s in sellers}

    history, inbox, log = [], {s: [] for s in sellers}, []
    tokens = {"in": 0, "out": 0}
    for rnd in range(1, rounds + 1):
        reqs = []
        for i, s in enumerate(sellers):
            up = user_prompt(s, others[s], mkt.c * mkt.scale, mkt.max_price, history, inbox[s])
            reqs.append(chat(client, model, [{"role": "system", "content": sys[s]},
                                             {"role": "user", "content": up}], seed * 1000 + rnd * 10 + i))
        replies = await asyncio.gather(*reqs)
        decisions = {}
        for s, (text, usage) in zip(sellers, replies):
            tokens["in"] += usage["in"]; tokens["out"] += usage["out"]
            d = parse_response(text, recipients[s], mkt.max_price)
            if d["price"] is None:  # unparseable: keep last price (logged as parse failure)
                d["price"] = history[-1]["prices"][s] if history else round(mkt.nash, 2)
            d["raw"] = text
            d["inbox"] = inbox[s]
            decisions[s] = d

        prices = {s: decisions[s]["price"] for s in sellers}
        prices[uc_name] = uc.price(rnd)
        q, pi = mkt.step([prices[n] for n in names])
        h = {"round": rnd, "prices": prices,
             "quantities": dict(zip(names, q)), "profits": dict(zip(names, pi))}
        history.append(h)

        # deliver messages for next round
        new_inbox = {s: [] for s in sellers}
        for s in sellers:
            for m in decisions[s]["messages"]:
                if m["to"] in new_inbox:
                    new_inbox[m["to"]].append({"from": s, "text": m["text"]})
        uc_msgs = uc.messages(rnd, sellers)
        for m in uc_msgs:
            new_inbox[m["to"]].append({"from": m["from"], "text": m["text"]})
        inbox = new_inbox

        log.append({**h, "decisions": {s: {k: decisions[s][k] for k in
                                           ("thoughts", "messages", "report", "price", "parse_ok", "raw", "inbox")}
                                       for s in sellers},
                    "undercover_messages": uc_msgs})

    rec = {"model": model, "arm": arm, "persona": persona, "seed": seed, "rounds": rounds, "channel": channel,
           "offer_round": offer_round, "follow_round": follow_round, "sellers": sellers,
           "undercover": uc_name, "nash": mkt.nash, "monopoly": mkt.monopoly, "cartel_price": uc.cartel,
           "tokens": tokens, "log": log, "time": time.time()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    return rec


def episode_path(results: Path, model: str, arm: str, persona: str, seed: int, channel: str = "all") -> Path:
    tag = "" if channel == "all" else f"__{channel}"
    return results / "episodes" / f"{model}__{persona}__{arm}__s{seed}{tag}.json"
