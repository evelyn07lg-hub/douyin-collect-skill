"""Analyze saved public DOM cards; never claim complete history or transcript."""
import json
import re
from pathlib import Path


def parse_card(link):
    match = re.fullmatch(r"https://www\.douyin\.com/(video|note)/(\d+)/?(?:\?.*)?", link.get("url", ""))
    if not match:
        return None
    lines = link.get("text", "").strip().splitlines()
    while lines and lines[0].strip() in ("置顶", ""):
        lines.pop(0)
    display = lines.pop(0).strip() if lines else ""
    exact = int(display.replace(",", "")) if re.fullmatch(r"\d+(?:,\d{3})*", display) else None
    return {"id": match[2], "type": "image" if match[1] == "note" else "video",
        "url": link["url"], "likes_display": display, "likes_exact_display": exact,
        "description": "\n".join(lines).strip(), "transcript": None,
        "needs_detail_verification": True}


def analyze(directory):
    directory = Path(directory)
    rows, profiles = [], []
    for file in sorted(directory.glob("profile-*.json")):
        v = json.loads(file.read_text(encoding="utf-8"))
        expected = "https://www.douyin.com/user/" + v["sec_uid"]
        if v.get("actual_url", "").split("?")[0].rstrip("/") != expected:
            continue
        name = v["title"].removesuffix("的抖音 - 抖音")
        seen = set()
        for link in v.get("links", []):
            card = parse_card(link)
            if card is None or card["id"] in seen:
                continue
            seen.add(card["id"])
            card.update(account_id="douyin-public:" + v["sec_uid"], account_name=name,
                        source_file=str(file), observed_at=directory.name)
            rows.append(card)
        profiles.append({"name": name, "sec_uid": v["sec_uid"], "visible_works": len(seen)})
    return {"complete_history": False, "remote_archived": False, "profiles": profiles,
        "works": rows, "above_500_exact_display": [r for r in rows if r["likes_exact_display"] is not None and r["likes_exact_display"] > 500],
        "requires_count_review": [r for r in rows if r["likes_exact_display"] is None]}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8-sig"))
    data = root / config["data_dir"]
    directories = sorted(p for p in (data / "browser-probe").iterdir() if p.is_dir() and list(p.glob("profile-*.json")))
    if not directories:
        raise SystemExit("No saved profile evidence")
    result = analyze(directories[-1])
    destination = data / "public-candidates.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"profiles": result["profiles"], "visible_works": len(result["works"]),
        "above_500_exact_display": len(result["above_500_exact_display"]),
        "requires_count_review": len(result["requires_count_review"]), "output": str(destination)}, ensure_ascii=False))
