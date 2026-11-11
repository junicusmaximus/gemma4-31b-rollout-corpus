"""Paper 2 seed analysis, rules 1-5 and 10 of paper2-analysis-rules-FROZEN-2026-11-10.md (sha256 1db9126bdc40...1932c).

Usage: python -B paper2_seed_analysis.py --out DIR --seed LABEL=PATH [--seed LABEL=PATH ...]
One task_results.jsonl per decoding seed, given explicitly (no globbing). Seeds are ordered as given; pair (i, j) has i
before j ("first" = earlier argument). Writes DIR/results.json and DIR/report.txt (DIR must not exist yet).
Implemented readings of points the frozen file leaves open are listed in READINGS and printed in the report.
"""
import argparse, itertools, json, math, os, sys
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import numpy as np

MS = (8, 16, 18, 36, 95)
N_DRAWS = 10000
READINGS = [
    "R1 a row is valid iff its JSON field resolved is a JSON boolean; if a seed file has several rows for one task the first row "
    "with a boolean resolved is used and the duplicates are counted (duplicate_rows).",
    "R1 error texts are counted over valid rows only (rule 10), keyed by the exact error string.",
    "R2 seed pairs are all unordered pairs in argument order; 'first' is the earlier seed argument.",
    "R3 three-seed classes are computed when exactly three seeds are given; two-seed classes are computed for every pair.",
    "R4 each draw calls rng.integers(0, k_t) once as a vector over the included tasks sorted by task id; valid seeds of a task "
    "are in argument order; the rate is a fraction (0..1) and is also printed in percent.",
    "R5b each draw: rng.choice(eligible tasks sorted by id, size=min(m, n), replace=False), then for each drawn task in drawn "
    "order rng.choice(its valid seeds in argument order, size=2, replace=False) as (first, second).",
    "R5c g_min uses the unrounded d0; if d0 is undefined (no seed pair with tasks) g_min is not computed.",
    "R10 percentages are rounded half up to one decimal from the decimal string of the float (Decimal(repr(x))).",
]


def pct(x):
    return None if x is None else float(Decimal(repr(100.0 * x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def load_seed(path):
    rows, dup, invalid = {}, 0, 0
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        tid = r.get("instance_id")
        if not isinstance(r.get("resolved"), bool):
            invalid += 1
            continue
        if tid in rows:
            dup += 1
            continue
        rows[tid] = r
    errors = Counter(str(r["error"]) for r in rows.values() if r.get("error") not in (None, ""))
    return dict(valid={t: r["resolved"] for t, r in rows.items()}, errors=dict(errors), duplicate_rows=dup,
                invalid_rows=invalid)


def pair_table(a, b):
    common = sorted(set(a) & set(b))
    both = sum(a[t] and b[t] for t in common)
    first = sum(a[t] and not b[t] for t in common)
    second = sum(b[t] and not a[t] for t in common)
    neither = len(common) - both - first - second
    disc = (first + second) / len(common) if common else None
    trig = (first + second) > 0 and abs(first - second) >= 2 * math.sqrt(first + second)
    return dict(n=len(common), both=both, only_first=first, only_second=second, neither=neither,
                discordant=first + second, discordance=disc, discordance_pct=pct(disc),
                costly_rule=dict(b=first, c=second, triggered=bool(trig)))


def stability(seeds, labels):
    tasks = sorted(set().union(*[set(seeds[l]["valid"]) for l in labels]))
    out = {}
    if len(labels) == 3:
        c = Counter()
        for t in tasks:
            vals = [seeds[l]["valid"].get(t) for l in labels]
            if any(v is None for v in vals):
                c["incomplete"] += 1
            else:
                k = sum(vals)
                c["always" if k == 3 else "never" if k == 0 else "sometimes"] += 1
        out["three_seed"] = {k: c.get(k, 0) for k in ("always", "sometimes", "never", "incomplete")}
    two = {}
    for a, b in itertools.combinations(labels, 2):
        c = Counter()
        for t in sorted(set(seeds[a]["valid"]) | set(seeds[b]["valid"])):
            va, vb = seeds[a]["valid"].get(t), seeds[b]["valid"].get(t)
            if va is None or vb is None:
                c["incomplete"] += 1
            else:
                c["both" if va and vb else "neither" if not (va or vb) else "one"] += 1
        two[f"{a}|{b}"] = {k: c.get(k, 0) for k in ("both", "one", "neither", "incomplete")}
    out["two_seed"] = two
    return out


def draw_sim(seeds, labels):
    tasks = sorted(set().union(*[set(seeds[l]["valid"]) for l in labels]))
    per = [[seeds[l]["valid"][t] for l in labels if t in seeds[l]["valid"]] for t in tasks]
    inc = [p for p in per if p]
    left_out = len(per) - len(inc)
    rng = np.random.default_rng(20261110)
    ks = np.array([len(p) for p in inc])
    mat = np.zeros((len(inc), int(ks.max())), dtype=float)
    for i, p in enumerate(inc):
        mat[i, :len(p)] = p
    rates = np.empty(N_DRAWS)
    for d in range(N_DRAWS):
        idx = rng.integers(0, ks)
        rates[d] = mat[np.arange(len(inc)), idx].mean()
    st = dict(mean=float(rates.mean()), sd=float(rates.std(ddof=1)), p2_5=float(np.percentile(rates, 2.5)),
              p97_5=float(np.percentile(rates, 97.5)))
    return dict(tasks_included=len(inc), tasks_left_out=left_out, **st, **{k + "_pct": pct(v) for k, v in st.items()})


def false_trigger(seeds, labels):
    tasks = sorted(set().union(*[set(seeds[l]["valid"]) for l in labels]))
    elig = [(t, [l for l in labels if t in seeds[l]["valid"]]) for t in tasks]
    elig = [(t, ls) for t, ls in elig if len(ls) >= 2]
    rng = np.random.default_rng(20261111)
    out = {}
    for m in MS:
        mm = min(m, len(elig))
        hits = 0
        for _ in range(N_DRAWS):
            w = l = 0
            if mm:
                for i in rng.choice(len(elig), size=mm, replace=False):
                    t, ls = elig[int(i)]
                    s1, s2 = rng.choice(len(ls), size=2, replace=False)
                    r1, r2 = seeds[ls[int(s1)]]["valid"][t], seeds[ls[int(s2)]]["valid"][t]
                    w += (r2 and not r1); l += (r1 and not r2)
            hits += (w + l) > 0 and (w - l) >= 2 * math.sqrt(w + l)
        out[str(m)] = dict(m_used=mm, eligible=len(elig), share=hits / N_DRAWS, share_pct=pct(hits / N_DRAWS))
    return out


def g_min(d0):
    if d0 is None:
        return None
    out = {}
    for m in MS:
        g = 1
        while g < 2 * math.sqrt(d0 * m + g):
            g += 1
        out[str(m)] = dict(g_min=g, pp=pct(g / m), frac=g / m)
    return out


def analyse(labels, paths):
    seeds = {l: load_seed(p) for l, p in zip(labels, paths)}
    res = dict(inputs={l: p for l, p in zip(labels, paths)}, readings=READINGS, seeds={})
    for l in labels:
        s = seeds[l]
        res["seeds"][l] = dict(valid=len(s["valid"]), resolved=sum(s["valid"].values()),
                               resolve_rate=(sum(s["valid"].values()) / len(s["valid"])) if s["valid"] else None,
                               errors=s["errors"], error_rows=sum(s["errors"].values()),
                               duplicate_rows=s["duplicate_rows"], invalid_rows=s["invalid_rows"])
        res["seeds"][l]["resolve_rate_pct"] = pct(res["seeds"][l]["resolve_rate"])
    pairs = {f"{a}|{b}": pair_table(seeds[a]["valid"], seeds[b]["valid"]) for a, b in itertools.combinations(labels, 2)}
    res["pairs"] = pairs
    tn, td = sum(p["n"] for p in pairs.values()), sum(p["discordant"] for p in pairs.values())
    d0 = td / tn if tn else None
    res["d0"] = dict(discordant=td, tasks=tn, d0=d0, d0_pct=pct(d0))
    res["stability"] = stability(seeds, labels)
    res["draws"] = draw_sim(seeds, labels)
    res["false_trigger"] = false_trigger(seeds, labels)
    res["g_min"] = g_min(d0)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", action="append", required=True, help="LABEL=PATH")
    a = ap.parse_args(argv)
    labels, paths = zip(*[s.split("=", 1) for s in a.seed])
    res = analyse(list(labels), list(paths))
    os.makedirs(a.out)
    with open(os.path.join(a.out, "results.json"), "x") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    text = json.dumps(res, indent=1, sort_keys=True)
    with open(os.path.join(a.out, "report.txt"), "x") as f:
        f.write(text + "\n")
    print(text)
    return res


if __name__ == "__main__":
    main()
