#!/usr/bin/env python3
"""
Maakt games.svg: één kaart met de uren van je gekozen games.

- Steam: telt de uren van alle accounts in games.json bij elkaar op,
  en voegt meerdere app-ids per game samen (bijv. GTA V Legacy + Enhanced).
- R6 Siege: haalt de uren op via de Arenyze/r6data API (R6_API_KEY).
  Lukt dat niet, dan gebruikt hij "manual_hours" uit games.json,
  of de waarde van de vorige keer (zodat de kaart nooit kapot gaat).

Secrets (env): STEAM_TOKEN, STEAM_ID_2 (optioneel), R6_API_KEY (optioneel)
Lokaal testen zonder internet:  python3 scripts/games_card.py --demo
"""
import base64, json, os, sys, urllib.parse, urllib.request
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "games.json")
CACHE = os.path.join(ROOT, ".games-cache.json")
OUT = os.path.join(ROOT, "games.svg")
IMG_URL = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{}/capsule_231x87.jpg"


def get(url, headers=None, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-games-card", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    return data if raw else json.loads(data)


def resolve_ids(cfg):
    ids = []
    for sid in cfg["steam_ids"]:
        if sid == "STEAM_ID_2":
            sid = os.environ.get("STEAM_ID_2", "").strip()
        if sid:
            ids.append(sid)
    return ids


def steam_minutes(key, steam_id):
    """{appid: minuten} voor één account."""
    q = urllib.parse.urlencode({"key": key, "steamid": steam_id, "include_played_free_games": 1,
                                "include_appinfo": 0, "format": "json"})
    data = get(f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?{q}")
    games = data.get("response", {}).get("games", [])
    if not games:
        print(f"! account {steam_id[-4:]}: geen games zichtbaar (staat 'Game details' op Public?)")
    return {g["appid"]: g.get("playtime_forever", 0) for g in games}


def r6_hours(r6, key):
    q = urllib.parse.urlencode({"nameOnPlatform": r6["ubisoft_name"], "platformType": r6["platform"]})
    data = get(f"https://public-api.arenyze.com/r6/api/v2/fullstats?{q}", headers={"api-key": key})

    def find(o):  # zoek "totalsHoursPlayed" waar die ook zit in het antwoord
        if isinstance(o, dict):
            if "totalsHoursPlayed" in o:
                return o["totalsHoursPlayed"]
            for v in o.values():
                r = find(v)
                if r is not None:
                    return r
        if isinstance(o, list):
            for v in o:
                r = find(v)
                if r is not None:
                    return r
        return None

    t = find(data)
    if not t:
        raise ValueError("geen totalsHoursPlayed in antwoord")
    return round(t.get("totalMs", 0) / 3_600_000) or t.get("hours", 0)


def image_data(appid):
    try:
        return "data:image/jpeg;base64," + base64.b64encode(get(IMG_URL.format(appid), raw=True)).decode()
    except Exception as e:
        print(f"! plaatje {appid} niet geladen: {e}")
        return None


def fmt(h):
    return f"{h:,}".replace(",", ".") + " h"


def render(rows, title):
    W, PAD, ROW, IMG_W, IMG_H = 720, 24, 64, 128, 48
    H = PAD + 40 + len(rows) * ROW + PAD - 8
    top = max([r["hours"] for r in rows] + [1])
    total = sum(r["hours"] for r in rows)
    bar_x, bar_w = PAD + IMG_W + 16, W - (PAD + IMG_W + 16) - PAD - 80

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}'
           '.t{font-size:15px;font-weight:600;fill:#e6edf3}.m{font-size:13px;fill:#8b949e}'
           '.n{font-size:14px;font-weight:600;fill:#e6edf3}.h{font-size:14px;font-weight:600;fill:#e6edf3}</style>',
           f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="8" fill="#0d1117" stroke="#30363d"/>',
           f'<text class="t" x="{PAD}" y="{PAD+14}">{escape(title)}</text>',
           f'<text class="m" x="{W-PAD}" y="{PAD+14}" text-anchor="end">{fmt(total)} total</text>']

    for i, r in enumerate(rows):
        y = PAD + 40 + i * ROW
        cid = f"c{i}"
        out.append(f'<clipPath id="{cid}"><rect x="{PAD}" y="{y}" width="{IMG_W}" height="{IMG_H}" rx="4"/></clipPath>')
        if r["img"]:
            out.append(f'<image href="{r["img"]}" x="{PAD}" y="{y}" width="{IMG_W}" height="{IMG_H}" '
                       f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{cid})"/>')
        else:
            out.append(f'<rect x="{PAD}" y="{y}" width="{IMG_W}" height="{IMG_H}" rx="4" fill="#161b22"/>')
        frac = r["hours"] / top
        out += [f'<text class="n" x="{bar_x}" y="{y+17}">{escape(r["name"])}</text>',
                f'<text class="m" x="{bar_x}" y="{y+34}" font-size="12">{escape(r["sub"])}</text>',
                f'<rect x="{bar_x}" y="{y+41}" width="{bar_w}" height="5" rx="2.5" fill="#21262d"/>',
                f'<rect x="{bar_x}" y="{y+41}" width="{max(bar_w*frac, 5):.1f}" height="5" rx="2.5" fill="#58a6ff"/>',
                f'<text class="h" x="{W-PAD}" y="{y+29}" text-anchor="end">{fmt(r["hours"])}</text>']
    out.append("</svg>")
    return "\n".join(out)


def main():
    demo = "--demo" in sys.argv
    cfg = json.load(open(CONFIG))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    rows = []

    # Steam
    per_app = {}
    if demo:
        per_app = {252490: 61200, 271590: 30000, 3240220: 9000, 1172620: 7200, 1144200: 4800}
    else:
        key, ids = os.environ["STEAM_TOKEN"], resolve_ids(cfg)
        print(f"Steam-accounts: {len(ids)}")
        for sid in ids:
            for app, mins in steam_minutes(key, sid).items():
                per_app[app] = per_app.get(app, 0) + mins
    for g in cfg["games"]:
        hours = round(sum(per_app.get(a, 0) for a in g["appids"]) / 60)
        rows.append({"name": g["name"], "hours": hours, "sub": "Steam",
                     "img": None if demo else image_data(g["image"])})

    # R6 Siege
    r6 = cfg.get("r6")
    if r6:
        hours, src = None, "Ubisoft Connect"
        if demo:
            hours = 1350
        elif os.environ.get("R6_API_KEY"):
            try:
                hours = r6_hours(r6, os.environ["R6_API_KEY"])
            except Exception as e:
                print(f"! R6 API faalde: {e}")
        if hours is None:
            hours = r6.get("manual_hours") or cache.get("r6_hours")
        if hours:
            cache["r6_hours"] = hours
            rows.append({"name": r6["name"], "hours": hours, "sub": src,
                         "img": None if demo else image_data(r6["image"])})

    rows = [r for r in rows if r["hours"] > 0]
    rows.sort(key=lambda r: r["hours"], reverse=True)
    for r in rows:
        print(f"  {r['name']:<22} {r['hours']:>6} h")
    open(OUT, "w").write(render(rows, cfg.get("title", "Hours played")))
    if not demo:
        json.dump(cache, open(CACHE, "w"))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
