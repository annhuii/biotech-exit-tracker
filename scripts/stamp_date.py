"""Update the as_of date in every data/*.json and in each HTML 'updated' span."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = date.today().isoformat()


def stamp_json(path: Path) -> None:
    data = json.loads(path.read_text())
    if "as_of" in data:
        data["as_of"] = TODAY
        path.write_text(json.dumps(data, indent=2))
        print(f"  {path.name}: as_of -> {TODAY}")


def stamp_html(path: Path) -> None:
    text = path.read_text()
    new = re.sub(
        r'(<div class="updated">Updated )\d{4}-\d{2}-\d{2}(</div>)',
        rf"\g<1>{TODAY}\g<2>",
        text,
    )
    if new != text:
        path.write_text(new)
        print(f"  {path.name}: stamped")


def main() -> None:
    for p in (ROOT / "data").glob("*.json"):
        stamp_json(p)
    for p in ROOT.glob("*.html"):
        stamp_html(p)


if __name__ == "__main__":
    main()
