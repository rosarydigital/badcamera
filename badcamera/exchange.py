"""Timeline exchange: EDL for quick conform, FCPXML and OpenTimelineIO for a fuller cut that opens in Resolve."""
import json
from pathlib import Path
from xml.sax.saxutils import quoteattr


def tc(seconds, fps):
    f = int(round(seconds * round(fps)))
    n = round(fps)
    return f"{f // (3600 * n):02d}:{f // (60 * n) % 60:02d}:{f // n % 60:02d}:{f % n:02d}"


def export_edl(tl, path):
    """CMX3600: cuts on the main track only, which is all the format can carry."""
    _, fps = tl.format()
    rows = [f"TITLE: {Path(path).stem}", "FCM: NON-DROP FRAME", ""]
    for i, (c, a, b) in enumerate(tl.layout(), 1):
        rows += [f"{i:03d}  AX       AA/V  C        {tc(c.start, fps)} {tc(c.end, fps)} {tc(a, fps)} {tc(b, fps)}", f"* FROM CLIP NAME: {c.name}", f"* SOURCE FILE: {c.path}", ""]
    Path(path).write_text("\n".join(rows), encoding="utf-8")
    return path


def rate(fps):
    """FCPXML frame duration as a fraction string."""
    if abs(fps - 30000 / 1001) < 0.01:
        return 1001, 30000
    if abs(fps - 24000 / 1001) < 0.01:
        return 1001, 24000
    return 100, int(round(fps * 100))


def t_(seconds, fps):
    a, b = rate(fps)
    return f"{int(round(seconds * b / a)) * a}/{b}s"


def export_fcpxml(tl, path):
    (w, h), fps = tl.format()
    a_, b_ = rate(fps)
    assets, seen = [], {}
    everything = tl.clips + tl.overlays + tl.sounds
    for c in everything:
        if c.path not in seen:
            seen[c.path] = f"r{len(seen) + 2}"
            video = "1" if c.info.get("size") else "0"
            assets.append(f'    <asset id="{seen[c.path]}" name={quoteattr(c.name)} src={quoteattr(Path(c.path).resolve().as_uri())} start="0s" duration="{t_(c.info["duration"], fps)}" '
                          f'hasVideo="{video}" hasAudio="1" format="r1" audioSources="1" audioChannels="2" audioRate="48000"/>')
    spine = []
    for c, a, b in tl.layout():
        inner = []
        for o in tl.overlays:
            if a <= o.at < b:
                inner.append(f'        <asset-clip ref="{seen[o.path]}" lane="1" offset="{t_(c.start + o.at - a, fps)}" start="{t_(o.start, fps)}" duration="{t_(o.length, fps)}" name={quoteattr(o.name)}/>')
        for s in tl.sounds:
            if a <= s.at < b:
                inner.append(f'        <asset-clip ref="{seen[s.path]}" lane="-{s.track + 1}" offset="{t_(c.start + s.at - a, fps)}" start="{t_(s.start, fps)}" duration="{t_(s.length, fps)}" name={quoteattr(s.name)}/>')
        body = "\n".join(inner)
        attrs = f'ref="{seen[c.path]}" offset="{t_(a, fps)}" start="{t_(c.start, fps)}" duration="{t_(c.length, fps)}" name={quoteattr(c.name)}'
        spine.append(f"      <asset-clip {attrs}>\n{body}\n      </asset-clip>" if body else f"      <asset-clip {attrs}/>")
    Path(path).write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    <format id="r1" frameDuration="{a_}/{b_}s" width="{w}" height="{h}"/>
{chr(10).join(assets)}
  </resources>
  <library>
    <event name="BadCamera">
      <project name={quoteattr(Path(path).stem)}>
        <sequence format="r1" duration="{t_(tl.duration, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
{chr(10).join(spine)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
""", encoding="utf-8")
    return path


def export_otio(tl, path):
    _, fps = tl.format()

    def rt(v):
        return {"OTIO_SCHEMA": "RationalTime.1", "rate": fps, "value": round(v * fps)}

    def rng(start, dur):
        return {"OTIO_SCHEMA": "TimeRange.1", "start_time": rt(start), "duration": rt(dur)}

    def clip(c):
        return {"OTIO_SCHEMA": "Clip.1", "name": c.name, "source_range": rng(c.start, c.length), "effects": [], "markers": [], "metadata": {},
                "media_reference": {"OTIO_SCHEMA": "ExternalReference.1", "target_url": Path(c.path).resolve().as_uri(), "available_range": rng(0, c.info["duration"]), "metadata": {}}}

    def gap(d):
        return {"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": rng(0, d), "effects": [], "markers": [], "metadata": {}}

    def track(name, kind, items):
        kids, at = [], 0.0
        for i in sorted(items, key=lambda c: c.at):
            if i.at > at:
                kids.append(gap(i.at - at))
            kids.append(clip(i))
            at = i.at + i.length
        return {"OTIO_SCHEMA": "Track.1", "name": name, "kind": kind, "children": kids, "effects": [], "markers": [], "metadata": {}, "source_range": None}

    main = {"OTIO_SCHEMA": "Track.1", "name": "V1", "kind": "Video", "children": [clip(c) for c, _, _ in tl.layout()], "effects": [], "markers": [], "metadata": {}, "source_range": None}
    tracks = [main]
    if tl.overlays:
        tracks.append(track("V2", "Video", tl.overlays))
    for i in sorted({s.track for s in tl.sounds}):
        tracks.append(track(f"A{i + 1}", "Audio", [s for s in tl.sounds if s.track == i]))
    doc = {"OTIO_SCHEMA": "Timeline.1", "name": Path(path).stem, "metadata": {}, "global_start_time": None,
           "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": tracks, "effects": [], "markers": [], "metadata": {}, "source_range": None}}
    Path(path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path
