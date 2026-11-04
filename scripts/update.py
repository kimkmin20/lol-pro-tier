"""Daily update for LoL Pro Tier (runs in GitHub Actions; Python standard library only).
1. New pro games since the last update from the Leaguepedia Cargo API (results, champions by role, players,
   bans, pick order and first-pick team) -> data/extra.json
2. Champion names and icon ids from Riot Data Dragon, champions changed in each new patch from the LoL Wiki -> data/meta.json
The page (index.html) loads both files on start and replays the new games through its rating and tier models."""
import calendar, json, os, re, sys, time, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "LoLProTier/1.0 (+https://github.com; daily update, low request rate)"
LP = "https://lol.fandom.com/api.php"
WIKI = "https://wiki.leagueoflegends.com/en-us/api.php"
SPECIAL = {"nunuwillump": "nunu", "monkeyking": "wukong", "renataglasc": "renata"}
def ckey(s):
    k = re.sub(r"[^a-z0-9]", "", str(s or "").lower()); return SPECIAL.get(k, k) if k else ""
START = time.time()
BUDGET = 40 * 60   # stop waiting on rate limits after 40 minutes; tomorrow's run continues from the same point
def get_json(url, params, tries=8):
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        if time.time() - START > BUDGET: raise RuntimeError("time budget used up")
        try:
            with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": UA}), timeout=60) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("  http error:", e, flush=True); time.sleep(20 * (i + 1)); continue
        if isinstance(d, dict) and "error" in d:
            code = d["error"].get("code")
            if code == "ratelimited": print("  rate limited, waiting", flush=True); time.sleep(60 * (i + 1)); continue
            raise RuntimeError(d["error"].get("info") or code)
        return d
    raise RuntimeError("gave up after retries: " + url)
def cargo(**p):
    p = {"action": "cargoquery", "format": "json", "limit": "500", **p}
    d = get_json(LP, p); time.sleep(3)
    return [x["title"] for x in d.get("cargoquery", [])]

OV = [(r"world championship", "WLDs"), (r"mid-season invitational", "MSI"), (r"first stand", "FST"), (r"esports world cup", "EWC")]
OVPRE = {"LCK": "LCK", "LPL": "LPL", "LEC": "LEC", "LCS": "LCS", "LTA North": "LTA N", "LTA South": "LTA S", "LTA": "LTA", "LCP": "LCP", "CBLOL": "CBLOL", "PCS": "PCS", "VCS": "VCS", "LJL": "LJL", "TCL": "TCL", "LLA": "LLA"}
LGNAME = [(r"champions korea|^lck", "LCK"), (r"pro league|^lpl", "LPL"), (r"emea|european championship|^lec", "LEC"), (r"americas north|lta north", "LTA N"), (r"americas south|lta south", "LTA S"),
          (r"championship of the americas|^lta$", "LTA"), (r"championship series|^lcs", "LCS"), (r"championship pacific|^lcp", "LCP"), (r"brasileiro|cblol", "CBLOL"), (r"pacific championship series|^pcs", "PCS"),
          (r"vietnam|^vcs", "VCS"), (r"japan league|^ljl", "LJL"), (r"turkish|^tcl", "TCL"), (r"latinoam|^lla", "LLA")]
def league_of(op, league, level):
    for pat, l in OV:
        if re.search(pat, op or "", re.I): return l
    l = OVPRE.get(str(op or "").split("/")[0].strip())
    if l: return l
    if str(level or "").lower() != "primary": return None
    for pat, l in LGNAME:
        if re.search(pat, league or "", re.I): return l
    t = (str(op or "").split("/")[0].strip().split() or [""])[0]
    return t if re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", t) else None

def fetch_games(since):
    F = ("SG.GameId=gid,SG.OverviewPage=op,SG.DateTime_UTC=dt,SG.Team1=t1,SG.Team2=t2,SG.WinTeam=win,SG.Patch=patch,"
         "SG.Team1Picks=p1,SG.Team2Picks=p2,SG.Team1Bans=b1,SG.Team2Bans=b2,SG.Gamelength_Number=len")
    rows, off, withT = [], 0, True
    while True:
        try:
            part = (cargo(tables="ScoreboardGames=SG,Tournaments=T", join_on="SG.OverviewPage=T.OverviewPage", fields=F + ",T.League=league,T.TournamentLevel=level",
                          where=f'SG.DateTime_UTC > "{since}"', order_by="SG.DateTime_UTC", offset=str(off)) if withT else
                    cargo(tables="ScoreboardGames=SG", fields=F, where=f'SG.DateTime_UTC > "{since}"', order_by="SG.DateTime_UTC", offset=str(off)))
        except RuntimeError:
            if withT: withT = False; continue
            raise
        rows += part; print(f"games found: {len(rows)}", flush=True)
        if len(part) < 500: break
        off += 500
    rows = [r for r in rows if league_of(r.get("op"), r.get("league"), r.get("level")) and r.get("t1") and r.get("t2") and r.get("win") and r.get("p1") and r.get("p2")]
    print(f"top-level league and international games: {len(rows)}", flush=True)
    roles, pb = {}, {}
    RN = {"top": 0, "jungle": 1, "mid": 2, "bot": 3, "support": 4}
    for i in range(0, len(rows), 40):
        ids = ",".join('"' + str(r["gid"]).replace('"', "") + '"' for r in rows[i:i + 40])
        try:
            for p in cargo(tables="ScoreboardPlayers=SP", fields="SP.GameId=gid,SP.Team=team,SP.Champion=ch,SP.Role=role,SP.Link=player", where=f"SP.GameId IN ({ids})"):
                ri = RN.get(str(p.get("role") or "").lower())
                if ri is not None: roles.setdefault((p["gid"], p["team"]), {})[ri] = (p.get("ch"), p.get("player"))
        except RuntimeError as e: print("  players not available:", e, flush=True)
        f = ",".join([f"PB.Team{t}Pick{k}=k{(t - 1) * 5 + k - 1}" for t in (1, 2) for k in range(1, 6)])
        try:
            try: got = cargo(tables="PicksAndBansS7=PB", fields="PB.GameId=gid," + f + ",PB.Team1=t1,PB.Team2=t2", where=f"PB.GameId IN ({ids})")
            except RuntimeError: got = cargo(tables="PicksAndBansS7=PB", fields="PB.GameId=gid," + f, where=f"PB.GameId IN ({ids})")
            for r in got: pb[r["gid"]] = r
        except RuntimeError as e: print("  pick order not available:", e, flush=True)
    out = []
    for r in rows:
        ts = calendar.timegm(time.strptime(str(r["dt"])[:19], "%Y-%m-%d %H:%M:%S"))
        def side(team, lst):
            m = roles.get((r["gid"], team))
            if m and len(m) == 5: return [ckey(m[i][0]) for i in range(5)], [m[i][1] or "" for i in range(5)]
            ch = [ckey(x) for x in str(lst).split(",") if x.strip()][:5]   # Leaguepedia lists picks in role order
            return ch + [""] * (5 - len(ch)), [""] * 5
        cb, pbn = side(r["t1"], r["p1"]); cr, prn = side(r["t2"], r["p2"])
        if "" in cb or "" in cr: continue
        bans = lambda s: ([ckey(x) if x.strip() and x.strip() != "None" else "" for x in str(s or "").split(",")] + [""] * 5)[:5]
        parts = str(r["op"]).split("/")
        rec = [ts, league_of(r["op"], r.get("league"), r.get("level")), (parts[2] if len(parts) > 2 else parts[1] if len(parts) > 1 else "").strip(),
               1 if re.search(r"playoff|knockout|bracket|final", r["op"], re.I) else 0, r.get("patch") or "", r["t1"], r["t2"], 1 if r["win"] == r["t1"] else 0, "lp",
               cb + cr, bans(r.get("b1")) + bans(r.get("b2")), pbn + prn, "", "", -1, None, None,
               float(r["len"]) if str(r.get("len") or "").replace(".", "", 1).isdigit() else None]
        p = pb.get(r["gid"])
        if p:
            first = 0 if not p.get("t1") or re.sub(r"[^a-z0-9]", "", p["t1"].lower()) == re.sub(r"[^a-z0-9]", "", r["t1"].lower()) else 1
            def order(s):
                ks = [ckey(p.get(f"k{i}")) for i in (range(0, 5) if s == first else range(5, 10))]
                own = (cb if s == 0 else cr)
                return "".join(str(own.index(k)) for k in ks) if all(k in own for k in ks) else ""
            ob, orr = order(0), order(1)
            if len(ob) == 5 and len(orr) == 5: rec[12], rec[13], rec[14] = ob, orr, 1 if first == 0 else 0
        out.append(rec)
    return out

def update_meta(meta):
    try:
        v = get_json("https://ddragon.leagueoflegends.com/api/versions.json", {})[0]
        ko = get_json(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/ko_KR/champion.json", {})["data"]
        en = get_json(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/champion.json", {})["data"]
        meta["ddv"] = v
        meta["champs"] = [[ckey(c["name"]), c["name"], ko.get(i, c)["name"], i] for i, c in en.items()]
        print("Data Dragon", v, len(meta["champs"]), "champions", flush=True)
    except Exception as e: print("Data Dragon not updated:", e, flush=True)
    pn = meta.setdefault("pn", {})
    try:
        known = set(pn) | set(meta.get("pn_base", []))
        newest = max([tuple(map(int, p.split("."))) for p in known] or [(16, 1)])
        for gv in (newest[0], newest[0] + 1):
            d = get_json(WIKI, {"action": "query", "list": "allpages", "apprefix": f"V{gv + 10}.", "aplimit": "100", "format": "json"})
            for t in [x["title"] for x in d.get("query", {}).get("allpages", []) if re.fullmatch(r"V\d+\.\d+", x["title"])]:
                a, b = map(int, t[1:].split("."))
                p = f"{a - 10}.{b:02d}"
                if p in known: continue
                time.sleep(1.5)
                w = get_json(WIKI, {"action": "parse", "page": t, "prop": "wikitext", "format": "json"}).get("parse", {}).get("wikitext", {}).get("*", "")
                ks, ins = [], False
                for ln in w.split("\n"):
                    if re.match(r"^===\s*Champions\s*===\s*$", ln): ins = True; continue
                    if not ins: continue
                    m = re.match(r"^(?:;|=+)\s*\{\{ci\|([^}|]+)", ln)
                    if m: ks.append(ckey(m.group(1))); continue
                    if ln.startswith("=="): break
                if ks: pn[p] = sorted(set(ks)); print("patch", p, len(ks), "champions changed", flush=True)
    except Exception as e: print("patch notes not updated:", e, flush=True)
    return meta

def main():
    base = json.load(open(os.path.join(DATA, "base.json")))
    ex_path = os.path.join(DATA, "extra.json")
    ex = json.load(open(ex_path)) if os.path.exists(ex_path) else {"games": []}
    last = max([base["until"]] + [g[0] for g in ex["games"]])
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last + 60))
    print("looking for games after", since, "UTC", flush=True)
    new = fetch_games(since)
    have = {(round(g[0] / 600), tuple(sorted([g[5].lower(), g[6].lower()]))) for g in ex["games"]}
    added = 0
    for g in new:
        k = (round(g[0] / 600), tuple(sorted([g[5].lower(), g[6].lower()])))
        if k in have or g[0] <= base["until"]: continue
        have.add(k); ex["games"].append(g); added += 1
    ex["games"].sort(key=lambda g: g[0])
    ex["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(ex, open(ex_path, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"added {added} games, {len(ex['games'])} in total since the base data", flush=True)
    mp = os.path.join(DATA, "meta.json")
    meta = json.load(open(mp)) if os.path.exists(mp) else {"pn_base": base.get("patches", [])}
    json.dump(update_meta(meta), open(mp, "w"), ensure_ascii=False, separators=(",", ":"))

if __name__ == "__main__":
    main()
