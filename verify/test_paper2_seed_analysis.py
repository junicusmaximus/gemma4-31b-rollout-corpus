"""Fixture tests with hand-computed answers. Usage: python -B test_paper2_seed_analysis.py WORKDIR (WORKDIR must not exist)."""
import json, os, sys
import paper2_seed_analysis as P

W = sys.argv[1]
os.makedirs(W)
ERR = "Agent exceeded turns budget (80 turns)"


def write(name, rows):
    p = os.path.join(W, name)
    with open(p, "x") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def row(t, r, e=None): return {"instance_id": t, "resolved": r, "error": e}


ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want or (isinstance(want, float) and got is not None and abs(got - want) < 1e-9):
        ok += 1
    else:
        fail += 1; print("FAIL", name, "got", got, "want", want)


def near(name, got, want, tol):
    global ok, fail
    if abs(got - want) <= tol: ok += 1
    else: fail += 1; print("FAIL", name, got, want)


# rounding half up
for x, want in ((0.0225, 2.3), (0.22222, 22.2), (0.305555, 30.6), (0.0005, 0.1), (0.5, 50.0)):
    check(f"pct {x}", P.pct(x), want)

# Fixture A: two seeds; t5 non-boolean in s1; t6 missing in s2; t4 error row
a1 = write("A_s1.jsonl", [row("t1", True), row("t2", False), row("t3", True), row("t4", False, ERR), row("t5", "yes"), row("t6", True)])
a2 = write("A_s2.jsonl", [row("t1", True), row("t2", True), row("t3", False), row("t4", False), row("t5", True)])
A = P.analyse(["s1", "s2"], [a1, a2])
check("A valid s1", A["seeds"]["s1"]["valid"], 5); check("A invalid s1", A["seeds"]["s1"]["invalid_rows"], 1)
check("A valid s2", A["seeds"]["s2"]["valid"], 5)
check("A errors s1", A["seeds"]["s1"]["errors"], {ERR: 1}); check("A errors s2", A["seeds"]["s2"]["errors"], {})
p = A["pairs"]["s1|s2"]
check("A table", (p["n"], p["both"], p["only_first"], p["only_second"], p["neither"]), (4, 1, 1, 1, 1))
check("A disc pct", p["discordance_pct"], 50.0)
check("A costly", (p["costly_rule"]["b"], p["costly_rule"]["c"], p["costly_rule"]["triggered"]), (1, 1, False))
check("A d0", A["d0"]["d0"], 0.5)
check("A two-seed classes", A["stability"]["two_seed"]["s1|s2"], dict(both=1, one=2, neither=1, incomplete=2))
check("A gmin", {m: v["g_min"] for m, v in A["g_min"].items()}, {"8": 7, "16": 8, "18": 9, "36": 11, "95": 16})
check("A gmin pp", {m: v["pp"] for m, v in A["g_min"].items()}, {"8": 87.5, "16": 50.0, "18": 50.0, "36": 30.6, "95": 16.8})
check("A draws included", (A["draws"]["tasks_included"], A["draws"]["tasks_left_out"]), (6, 0))
near("A draws mean", A["draws"]["mean"], 4 / 6, 0.01); near("A draws sd", A["draws"]["sd"], 0.5 ** 0.5 / 6, 0.005)
check("A draws p2.5", A["draws"]["p2_5"], 0.5); check("A draws p97.5", A["draws"]["p97_5"], 5 / 6)
check("A false trigger", {m: (v["m_used"], v["share"]) for m, v in A["false_trigger"].items()},
      {m: (4, 0.0) for m in ("8", "16", "18", "36", "95")})

# Fixture B: b + c = 0, d0 = 0, m larger than eligible
b1 = write("B_s1.jsonl", [row("x1", True), row("x2", False)])
b2 = write("B_s2.jsonl", [row("x1", True), row("x2", False)])
B = P.analyse(["s1", "s2"], [b1, b2])
p = B["pairs"]["s1|s2"]
check("B table", (p["n"], p["both"], p["only_first"], p["only_second"], p["neither"], p["discordance_pct"]), (2, 1, 0, 0, 1, 0.0))
check("B costly", p["costly_rule"]["triggered"], False)
check("B gmin", {m: (v["g_min"], v["pp"]) for m, v in B["g_min"].items()},
      {"8": (4, 50.0), "16": (4, 25.0), "18": (4, 22.2), "36": (4, 11.1), "95": (4, 4.2)})
check("B false trigger", {m: (v["m_used"], v["eligible"], v["share"]) for m, v in B["false_trigger"].items()},
      {m: (2, 2, 0.0) for m in ("8", "16", "18", "36", "95")})
check("B draws", (B["draws"]["mean"], B["draws"]["sd"], B["draws"]["p2_5"], B["draws"]["p97_5"]), (0.5, 0.0, 0.5, 0.5))

# Fixture C: three seeds, y4 missing in seed 3, duplicate row in s1
c1 = write("C_s1.jsonl", [row("y1", True), row("y2", True), row("y3", False), row("y4", False), row("y1", False)])
c2 = write("C_s2.jsonl", [row("y1", True), row("y2", False), row("y3", False), row("y4", True)])
c3 = write("C_s3.jsonl", [row("y1", True), row("y2", False), row("y3", False)])
C = P.analyse(["s1", "s2", "s3"], [c1, c2, c3])
check("C dup", C["seeds"]["s1"]["duplicate_rows"], 1)
check("C 12", [C["pairs"]["s1|s2"][k] for k in ("n", "both", "only_first", "only_second", "neither")], [4, 1, 1, 1, 1])
check("C 13", [C["pairs"]["s1|s3"][k] for k in ("n", "both", "only_first", "only_second", "neither")], [3, 1, 1, 0, 1])
check("C 23", [C["pairs"]["s2|s3"][k] for k in ("n", "both", "only_first", "only_second", "neither")], [3, 1, 0, 0, 2])
check("C d0", (C["d0"]["discordant"], C["d0"]["tasks"], C["d0"]["d0_pct"]), (3, 10, 30.0))
check("C 13 costly", C["pairs"]["s1|s3"]["costly_rule"], dict(b=1, c=0, triggered=False))
check("C three classes", C["stability"]["three_seed"], dict(always=1, sometimes=1, never=1, incomplete=1))

# costly rule trigger case: b=4, c=0 -> 4 >= 2*2 -> triggered
check("costly trigger", P.pair_table({"a": 1, "b": 1, "c": 1, "d": 1}, {"a": 0, "b": 0, "c": 0, "d": 0})["costly_rule"]["triggered"], True)
check("costly b3c0", P.pair_table({"a": 1, "b": 1, "c": 1}, {"a": 0, "b": 0, "c": 0})["costly_rule"]["triggered"], False)

print(f"tests passed {ok}, failed {fail}")
sys.exit(1 if fail else 0)
