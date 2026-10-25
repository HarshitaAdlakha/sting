"""Offline tests: no API calls.  Run: python -m pytest -q  (or python tests/test_core.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sting.agents import OFFERS, Undercover, parse_response, system_prompt, user_prompt
from sting.market import Market


def test_duopoly_matches_calvano():
    m = Market(n=2, scale=1.0)
    assert abs(m.nash - 1.473) < 1e-3 and abs(m.monopoly - 1.925) < 1e-3


def test_triopoly_benchmarks_and_gain():
    m = Market(n=3)
    assert abs(m.nash - 13.70) < 0.01 and abs(m.monopoly - 20.00) < 0.01
    assert m.profit_at(m.monopoly) > m.profit_at(m.nash)
    assert abs(m.gain(m.nash)) < 1e-9 and abs(m.gain(m.monopoly) - 1) < 1e-9


def test_nash_is_best_response():
    m = Market(n=3)
    base = m.step([m.nash] * 3)[1][0]
    for d in (-0.5, 0.5):
        assert m.step([m.nash + d, m.nash, m.nash])[1][0] < base


def test_parse_json_and_fallbacks():
    others = ["Oak Co.", "Elm Co."]
    d = parse_response('{"thoughts":"x","messages":[{"to":"Oak Co.","text":"YES"},{"to":"Nobody","text":"hi"}],'
                       '"report":"","price":19.5}', others, 30)
    assert d["price"] == 19.5 and d["messages"] == [{"to": "Oak Co.", "text": "YES"}] and d["parse_ok"]
    d = parse_response('{"messages":[{"to":"elm co","text":"a"},{"to":"Elm","text":"b"},{"to":"Co.","text":"c"}],'
                       '"price":14}', others, 30)
    assert [m["to"] for m in d["messages"]] == ["Elm Co.", "Elm Co."]
    assert parse_response("My chosen price: 15.2", others, 30)["price"] == 15.2
    assert parse_response('{"price": 99}', others, 30)["price"] == 30
    assert parse_response("no number here", others, 30)["price"] is None


def test_undercover_same_prices_in_every_arm():
    prices = {arm: [Undercover("U", arm, 13.7, 20.0, 5, 10).price(r) for r in range(1, 17)] for arm in OFFERS}
    assert len({tuple(v) for v in prices.values()}) == 1
    assert prices["none"][3] == 13.7 and prices["none"][4] == 20.0


def test_undercover_message_timing():
    uc = Undercover("U", "direct", 13.7, 20.0, 5, 10)
    sent = {r: uc.messages(r, ["A", "B"]) for r in range(1, 17)}
    assert [r for r, m in sent.items() if m] == [4, 9]
    assert "$20.00" in sent[4][0]["text"] and len(sent[4]) == 2
    assert not any(Undercover("U", "none", 13.7, 20.0, 5, 10).messages(r, ["A"]) for r in range(1, 17))


def test_prompts_identical_across_arms_except_inbox():
    s = system_prompt("Oak Co.", ["Elm Co.", "Fir Co."])
    assert "Competition Authority" in s and "collude" not in s.lower()
    s2 = system_prompt("Oak Co.", ["Elm Co.", "Fir Co."], recipients=["Fir Co."])
    assert "messages to Fir Co." in s2 and "Firm names: Fir Co." in s2 and "Elm" not in s2.split("Firm names")[1]
    u = user_prompt("Oak Co.", ["Elm Co.", "Fir Co."], 10, 30, [], [{"from": "Fir Co.", "text": "hi"}])
    assert "From Fir Co.: hi" in u


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
