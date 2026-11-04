"""Champion traits for the team-composition part of the next ban/pick model (Python standard library only).
Every trait is 0..1:
  ap     share of damage that is magic (damage type in the LoL client tags; "Mixed" = 0.5)
  dmg    how much damage the champion brings (LoL Wiki damage rating 1-3)
  front  frontline (Wiki toughness rating, lifted for the Vanguard / Warden / Juggernaut classes)
  eng    hard engage (Initiator tag or Vanguard class = 1; catchers, divers and follow-up wardens 0.6; marksmen 0.3)
  poke   skill poke: Artillery class or "Long Range" tag, else the longest damaging non-dash Q/W/E in Data Dragon
         (basic-attack range does not count)
  dive   Diver / Assassin class or Dive tag (very mobile champions 0.5)
  peel   Enchanter / Warden class or "Ally Protection" tag
  carry  "Hypercarry" tag
Sources: LoL Wiki Module:ChampionData/data (Riot's champion classes, ratings and client tags) and Riot Data Dragon
championFull.json (skill ranges and descriptions). Both are read again by the daily update, so new champions and reworks
get traits without hand edits."""
import re

ORDER = ["ap", "dmg", "front", "eng", "poke", "dive", "peel", "carry"]
SPECIAL = {"nunuwillump": "nunu", "monkeyking": "wukong", "renataglasc": "renata"}
def ckey(n):
    k = re.sub(r"[^a-z0-9]", "", str(n or "").lower()); return SPECIAL.get(k, k)

# ---- Lua data tables (LoL Wiki modules) ----
TOK = re.compile(r'\s+|--[^\n]*|\[\[.*?\]\]|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|[A-Za-z_][A-Za-z_0-9]*|[{}\[\]=,;+*/()-]', re.S)
def lua_parse(s):
    s = s[s.index("{"):]
    toks, i = [], 0
    while i < len(s):
        m = TOK.match(s, i)
        if not m: raise ValueError("bad token at %d" % i)
        t = m.group(0); i = m.end()
        if not (t.isspace() or t.startswith("--")): toks.append(t)
    pos = [0]
    def peek(): return toks[pos[0]]
    def nxt(): t = toks[pos[0]]; pos[0] += 1; return t
    def val():
        v = atom()
        while isinstance(v, (int, float)) and peek() in ("+", "-", "*", "/"):
            op = nxt(); w = atom()
            v = v + w if op == "+" else v - w if op == "-" else v * w if op == "*" else v / w
        return v
    def atom():
        t = nxt()
        if t == "(":
            v = val(); nxt(); return v
        if t == "-": return -atom()
        if t == "{": return table()
        if t[0] in "\"'": return t[1:-1]
        if t in ("true", "false"): return t == "true"
        if t == "nil": return None
        try: return int(t)
        except ValueError:
            try: return float(t)
            except ValueError: return t
    def table():
        d, arr = {}, []
        while peek() != "}":
            if peek() == "[":
                nxt(); k = val(); nxt(); nxt(); d[k] = val()
            elif pos[0] + 1 < len(toks) and toks[pos[0] + 1] == "=" and re.match(r"[A-Za-z_]", peek()):
                k = nxt(); nxt(); d[k] = val()
            else: arr.append(val())
            if peek() in (",", ";"): nxt()
        nxt()
        if arr and not d: return arr
        if arr: d.update({j + 1: v for j, v in enumerate(arr)})
        return d
    nxt()
    return table()

# ---- skill poke range from Data Dragon ----
DASH = re.compile(r"\b(dash(es|ing)?|leaps?|lunges?|jumps?|launch(es)? (him|her|it)self|pulls? (him|her)self|carrying (him|her) forward|runs down|blinks?|teleports?|charges? (forward|at|toward|towards|into)|pounces?|vaults?|flies|soars?|propels? (him|her)self|rushes|drags? (him|her)self|hooks?|grapples?)\b", re.I)
SHOT = re.compile(r"\b(fires?|throws?|launch(es)?|sends?|shoots?|hurls?|flings?|toss(es)?|lobs?|projectile|missile|bolts?|orbs?|beams?|javelins?|arrows?|bombs?|blasts?|spears?|daggers?|bullets?|shells?|rockets?|lasers?|artillery|volley|barrage|wave|unleash(es)?|shots?|cannon)\b", re.I)
FIX_POKE = {"Jayce": 1300, "Varus": 1600, "Xerath": 1450, "Corki": 1300, "Zoe": 1200, "Hwei": 1200, "Ziggs": 1400, "Nidalee": 1500, "Karma": 1150}   # cannon Q, charged Q, Missile Barrage, Mantra Q ...
def skill_poke(c):
    poke = 0
    for i, s in enumerate(c.get("spells", [])[:3]):
        txt = re.sub(r"<[^>]+>", " ", s.get("description") or "")
        first = re.split(r"(?<=[.!?])\s", txt)[0]
        rng = max([v for v in s.get("range", []) if isinstance(v, (int, float)) and v < 5000] or [0])
        if not DASH.search(first) and SHOT.search(txt) and re.search(r"damag", txt, re.I): poke = max(poke, rng)
    return max(poke, FIX_POKE.get(c.get("id"), 0))

AP_FIX = {"corki": 0.6, "kaisa": 0.4}   # the client's damage type disagrees with how pros build them
def clip(x): return max(0.0, min(1.0, x))
def build(wiki, ddfull):
    """wiki: parsed Module:ChampionData/data; ddfull: Data Dragon championFull.json -> {key: {trait: value}}"""
    dd = {ckey(c["name"]): skill_poke(c) for c in ddfull.get("data", {}).values()}
    out = {}
    for name, w in wiki.items():
        k = ckey(name)
        if not isinstance(w, dict) or k == "meganar": continue
        role, tags = set(w.get("role") or []), {str(t).strip() for t in (w.get("client_tags") or [])}
        r = lambda f, d=2: (w.get(f) if isinstance(w.get(f), (int, float)) else d)
        ap = 1.0 if "Magic" in tags else 0.0 if "Physical" in tags else 0.5 if "Mixed" in tags else 1.0 if w.get("adaptivetype") == "Magic" else 0.0
        ap = AP_FIX.get(k, ap)
        front = clip((r("toughness") - 1) / 2)
        if role & {"Vanguard", "Warden"}: front = max(front, 1.0)
        if "Juggernaut" in role or "Durable" in tags: front = max(front, 0.75)
        eng = (1.0 if ("Initiator" in tags or "Vanguard" in role) else 0.3 if "Marksman" in role else 0.6 if ("Catcher" in role or "Diver" in role or "Dive" in tags) else 0.0)
        if not eng and "Warden" in role and r("control") >= 3 and r("mobility") >= 2: eng = 0.6   # follow-up engage (Galio, K'Sante)
        poke = clip((dd.get(k, 0) - 900) / 500)
        if w.get("rangetype") == "Melee" or r("damage") < 2 or eng >= 1: poke = 0.0   # hooks, melee spells, utility supports
        if "Marksman" in role: poke = min(poke, 0.7)
        if "Artillery" in role or "Long Range" in tags: poke = 1.0
        dive = 1.0 if (role & {"Diver", "Assassin"} or "Dive" in tags) else 0.5 if r("mobility") >= 3 else 0.0
        peel = 1.0 if (role & {"Enchanter", "Warden"} or "Ally Protection" in tags) else 0.0
        out[k] = {"ap": ap, "dmg": round(clip((r("damage") - 1) / 2) * 0.8 + 0.2, 2), "front": round(front, 2), "eng": eng, "poke": round(poke, 2),
                  "dive": dive, "peel": peel, "carry": 1.0 if "Hypercarry" in tags else 0.0}
    return out
def sane(T):
    """guard against a changed wiki format: known champions must still look like themselves"""
    try:
        return (len(T) >= 150 and T["jayce"]["poke"] >= 0.5 and T["malphite"]["front"] >= 0.75 and T["malphite"]["eng"] >= 1
                and T["xerath"]["ap"] == 1 and T["caitlyn"]["ap"] == 0 and T["lulu"]["peel"] == 1 and T["vi"]["dive"] == 1)
    except KeyError: return False
