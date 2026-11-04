"""Daily update for LoL Pro Tier (runs in GitHub Actions; Python standard library only).
1. New pro games since the last update from the Leaguepedia Cargo API (results, champions by role, players,
   bans, pick order and first-pick team) -> data/extra.json
2. Champion names and icon ids from Riot Data Dragon, champions changed in each new patch from the LoL Wiki,
   champion traits for the composition model (scripts/champ_traits.py) -> data/meta.json
The page (index.html) loads both files on start and replays the new games through its rating and tier models."""
import calendar, http.cookiejar, json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import champ_traits
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "LoLProTier/1.0 (+https://github.com; daily update, low request rate)"
LP = "https://lol.fandom.com/api.php"
WIKI = "https://wiki.leagueoflegends.com/en-us/api.php"
SPECIAL = {"nunuwillump": "nunu", "monkeyking": "wukong", "renataglasc": "renata"}
def ckey(s):
    k = re.sub(r"[^a-z0-9]", "", str(s or "").lower()); return SPECIAL.get(k, k) if k else ""
START = time.time()
BUDGET = 15 * 60   # Leaguepedia only (anonymous): stop waiting on its rate limit after 15 minutes; the next run continues from the same point
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def get_json(url, params, tries=8, data=None):
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        if url == LP and time.time() - START > BUDGET: raise RuntimeError("time budget used up")
        try:
            req = urllib.request.Request(q, headers={"User-Agent": UA}, data=urllib.parse.urlencode(data).encode() if data else None)
            with OPENER.open(req, timeout=60) as r:
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

# Oracle's Elixir (official Google Drive folder): the current year's file has pick order, first pick and gold differences.
# Drive sometimes refuses downloads of popular files ("quota exceeded"); then Leaguepedia alone is used for that run,
# and the workflow runs three times a day so a busy morning does not cost a whole day.
OE_FOLDER = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
OE_LG = {"LCK", "LPL", "LEC", "LCS", "LTA N", "LTA S", "LTA", "LCP", "PCS", "VCS", "CBLOL", "LJL", "TCL", "LLA", "WLDs", "MSI", "FST", "EWC"}
POS = ["top", "jng", "mid", "bot", "sup"]
def http_text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
        return r.read().decode("utf-8", "replace")
def fetch_oe(since_ts, extra_leagues=()):
    import csv, io
    try:
        html = http_text(f"https://drive.google.com/embeddedfolderview?id={OE_FOLDER}")
    except Exception as e:
        print("Oracle's Elixir folder not reachable:", e, flush=True); return []
    files = dict((t, i) for i, t in re.findall(r'href="https://drive.google.com/file/d/([^/"]+)/[^"]*".*?flip-entry-title">([^<]+)<', html, re.S))
    out = []
    for y in sorted({time.gmtime(since_ts).tm_year, time.gmtime().tm_year}):
        fid = files.get(f"{y}_LoL_esports_match_data_from_OraclesElixir.csv")
        if not fid: continue
        text = ""
        for t in range(3):   # Drive answers big files with a confirmation page first, and busy files with a "quota" page
            try: text = http_text(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t" + (f"&uuid={uid}" if t and uid else ""))
            except Exception as e: print("Oracle's Elixir download failed:", e, flush=True); text = ""
            if text.startswith("gameid"): break
            m = re.search(r'name="uuid" value="([^"]+)"', text); uid = m.group(1) if m else ""
            ttl = re.search(r"<title>([^<]*)</title>", text)
            print(f"Oracle's Elixir {y}: not the data file ({(ttl.group(1) if ttl else text[:80]).strip()})", flush=True)
            if not uid: time.sleep(30)
        if not text.startswith("gameid"): print(f"Oracle's Elixir {y}: download refused; the next run tries again", flush=True); continue
        games = {}
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("league") not in OE_LG and row.get("league") not in extra_leagues: continue
            g = games.setdefault(row["gameid"], {"row": row, "team": {}, "pl": {"Blue": {}, "Red": {}}})
            if row["position"] == "team": g["team"][row["side"]] = row
            elif row["side"] in g["pl"]: g["pl"][row["side"]][row["position"]] = row
        num = lambda v: None if v in (None, "") else float(v)
        for gid, g in games.items():
            B, R = g["team"].get("Blue"), g["team"].get("Red")
            if not B or not R or any(p not in g["pl"][s] for s in ("Blue", "Red") for p in POS): continue
            try: ts = calendar.timegm(time.strptime(B["date"][:19], "%Y-%m-%d %H:%M:%S"))
            except ValueError: continue
            if ts <= since_ts: continue
            picks = [ckey(g["pl"][s][p]["champion"]) for s in ("Blue", "Red") for p in POS]
            if "" in picks: continue
            rec = [ts, B["league"], B.get("split") or "", int(num(B.get("playoffs")) or 0), B.get("patch") or "", B["teamname"], R["teamname"], 1 if B.get("result") == "1" else 0, "oe",
                   picks, [ckey(T.get(f"ban{i}")) for T in (B, R) for i in range(1, 6)], [g["pl"][s][p].get("playername") or "" for s in ("Blue", "Red") for p in POS],
                   "", "", -1, None, None, None]
            def order(T, own):
                ks = [ckey(T.get(f"pick{i}")) for i in range(1, 6)]
                return "".join(str(own.index(k)) for k in ks) if all(k in own for k in ks) else ""
            ob, orr = order(B, picks[:5]), order(R, picks[5:])
            if len(ob) == 5 and len(orr) == 5 and (B.get("firstPick") == "1" or R.get("firstPick") == "1"):
                rec[12], rec[13], rec[14] = ob, orr, 1 if B.get("firstPick") == "1" else 0
            gd = [num(B.get(f"golddiffat{m}")) for m in (10, 15, 20, 25)]
            if any(v is not None for v in gd): rec[15] = [None if v is None else round(v / 10) for v in gd]
            lg15 = [num(g["pl"]["Blue"][p].get("golddiffat15")) for p in POS]
            if any(v is not None for v in lg15): rec[16] = [None if v is None else round(v / 10) for v in lg15]
            if num(B.get("gamelength")): rec[17] = round(num(B["gamelength"]) / 6) / 10
            out.append(rec)
        print(f"Oracle's Elixir {y}: {len(out)} new games", flush=True)
    return out

def update_meta(meta):
    try:
        v = get_json("https://ddragon.leagueoflegends.com/api/versions.json", {})[0]
        ko = get_json(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/ko_KR/champion.json", {})["data"]
        en = get_json(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/champion.json", {})["data"]
        meta["ddv"] = v
        meta["champs"] = [[ckey(c["name"]), c["name"], ko.get(i, c)["name"], i, c.get("tags", [])] for i, c in en.items()]
        print("Data Dragon", v, len(meta["champs"]), "champions", flush=True)
    except Exception as e: print("Data Dragon not updated:", e, flush=True); v = None
    try:   # traits: damage type, frontline, engage, skill poke, dive, peel, hypercarry (new champions and reworks included)
        if v and (meta.get("traits_v") != v or time.gmtime().tm_wday == 0):
            full = get_json(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/championFull.json", {})
            pg = get_json(WIKI, {"action": "query", "prop": "revisions", "titles": "Module:ChampionData/data", "rvprop": "content", "rvslots": "main", "format": "json"})
            lua = list(pg["query"]["pages"].values())[0]["revisions"][0]["slots"]["main"]["*"]
            T = champ_traits.build(champ_traits.lua_parse(lua), full)
            if champ_traits.sane(T):
                meta["traits"] = {k: [t[x] for x in champ_traits.ORDER] for k, t in T.items()}; meta["traits_v"] = v
                print("champion traits:", len(T), flush=True)
            else: print("champion traits not updated: the wiki data looks different now (kept the previous traits)", flush=True)
    except Exception as e: print("champion traits not updated:", e, flush=True)
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
    tn = lambda t: re.sub(r"[^a-z0-9]", "", str(t).lower())
    key = lambda g: (round(g[0] / 600), tuple(sorted([tn(g[5]), tn(g[6])])))
    # 1) Oracle's Elixir: richer records; they replace Leaguepedia copies of the same games
    mp = os.path.join(DATA, "meta.json")
    meta = json.load(open(mp)) if os.path.exists(mp) else {"pn_base": base.get("patches", [])}
    oe = fetch_oe(base["until"], set(meta.get("leagues", [])))
    if oe:
        ok = {key(g) for g in oe}
        ex["games"] = [g for g in ex["games"] if key(g) not in ok]
        ex["games"] += [g for g in oe]
    # 2) Leaguepedia: games after the newest one we already have
    last = max([base["until"]] + [g[0] for g in ex["games"]])
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last + 60))
    print("looking for games after", since, "UTC on Leaguepedia", flush=True)
    try: new = fetch_games(since)
    except Exception as e: print("games not updated today:", e, flush=True); new = []
    have = {key(g) for g in ex["games"]}
    added = 0
    for g in new:
        k = key(g)
        if k in have or g[0] <= base["until"]: continue
        have.add(k); ex["games"].append(g); added += 1
    ex["games"].sort(key=lambda g: g[0])
    ex["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(ex, open(ex_path, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"added {added} games, {len(ex['games'])} in total since the base data", flush=True)
    meta["leagues"] = sorted(set(meta.get("leagues", [])) | {g[1] for g in ex["games"] if g[8] == "lp"})
    meta["checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())   # changes every run: keeps the repository active so GitHub never pauses the schedule
    json.dump(update_meta(meta), open(mp, "w"), ensure_ascii=False, separators=(",", ":"))

if __name__ == "__main__":
    main()
