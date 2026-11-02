import json
import re
from pathlib import Path

from .effects import REGISTRY, make
from .gpu import DATA, ROOT

PRESETS = ROOT / "presets"
USER = DATA / "presets" / "user"
RESERVED = ("styles", "transform", "settings")  # settings files that share the folder with presets


def builtin():
    return json.loads((PRESETS / "builtin.json").read_text(encoding="utf-8"))


def load_all():
    """Built-in presets first, then user presets (presets/user/*.json)."""
    out = builtin()
    for f in sorted(USER.glob("*.json")):
        if f.stem not in RESERVED:
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def build(preset):
    return [make(s["type"], s.get("params"), s.get("enabled", True)) for s in preset["steps"]]


def to_preset(name, steps):
    return {"name": name, "steps": [e.to_json() for e in steps]}


def save(name, steps):
    return write(to_preset(name, steps))


def export_file(preset, path):
    """Write one preset to a shareable file, along with any of the user's own styles for its effects."""
    all_styles = json.loads(USER_STYLES.read_text(encoding="utf-8")) if USER_STYLES.exists() else {}
    used = {s["type"] for s in preset["steps"]}
    out = {**preset, "user_styles": {k: v for k, v in all_styles.items() if k in used}}
    Path(path).write_text(json.dumps(out, indent=1), encoding="utf-8")


def import_file(path):
    """Add a preset file to the user's presets and return its name. Names are kept unique so nothing is overwritten."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(d, dict) or "name" not in d or "steps" not in d:
        raise ValueError(f"{Path(path).name} isn't a BadCamera preset")
    unknown = {s["type"] for s in d["steps"]} - set(REGISTRY)
    if unknown:
        raise ValueError(f"{Path(path).name} needs effects this version doesn't have: {', '.join(sorted(unknown))}")
    extra = d.pop("user_styles", {})
    if extra:
        user = json.loads(USER_STYLES.read_text(encoding="utf-8")) if USER_STYLES.exists() else {}
        for k, v in extra.items():
            user[k] = {**v, **user.get(k, {})}  # the user's own version of a same-named style wins
        USER_STYLES.parent.mkdir(parents=True, exist_ok=True)
        USER_STYLES.write_text(json.dumps(user, indent=1), encoding="utf-8")
    names, base, i = {p["name"] for p in load_all()}, d["name"], 2
    while d["name"] in names:
        d["name"], i = f"{base} {i}", i + 1
    write(d)
    return d["name"]


def write(preset):
    slug = re.sub(r"[^a-z0-9]+", "_", preset["name"].lower()).strip("_") or "preset"
    path = USER / f"{slug + '_preset' if slug in RESERVED else slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preset, indent=1), encoding="utf-8")
    return path


def uses_old_vhs(preset):
    return any(s["type"] == "vhs" for s in preset["steps"])


def upgrade_copy(preset):
    """Copy a preset as '<name> (New Tape)' with the old vhs step swapped for the signal-based tape step. The original stays."""
    steps = []
    for s in preset["steps"]:
        if s["type"] != "vhs":
            steps.append(s)
            continue
        v = {**REGISTRY["vhs"](**s.get("params", {})).v}
        steps.append({"type": "tape", "enabled": s.get("enabled", True), "params": {
            "format": "VHS SP" if v["lines"] >= 400 else "VHS EP", "standard": "NTSC", "noise": min(v["noise"] * 8, 1.0), "tracking": v["tracking"],
            "dropouts": v["dropouts"], "jitter": min(v["wobble"] / 2, 2.0), "saturation": v["saturation"]}})
    name, names, i = f"{preset['name']} (New Tape)", {p["name"] for p in load_all()}, 2
    while name in names:
        name, i = f"{preset['name']} (New Tape {i})", i + 1
    write({"name": name, "steps": steps})
    return name


def process(g, steps, tex):
    for e in steps:
        if e.enabled and not e.error:
            try:
                tex = e.apply(g, tex)
            except Exception as ex:  # a broken step is shown in the UI and skipped, not fatal
                e.error = str(ex)
                print(f"[{e.type}] {ex}")
    return tex


USER_STYLES = USER / "styles.json"


def styles(type):
    """Built-in styles for an effect type, then the user's saved ones."""
    user = json.loads(USER_STYLES.read_text(encoding="utf-8")) if USER_STYLES.exists() else {}
    return {**REGISTRY[type].styles, **user.get(type, {})}


def save_style(effect, name):
    user = json.loads(USER_STYLES.read_text(encoding="utf-8")) if USER_STYLES.exists() else {}
    user.setdefault(effect.type, {})[name] = effect.v
    USER_STYLES.parent.mkdir(parents=True, exist_ok=True)
    USER_STYLES.write_text(json.dumps(user, indent=1), encoding="utf-8")
