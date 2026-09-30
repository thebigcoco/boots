from __future__ import annotations

import html
import json
import random
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "cache"
OUT_DIR = BASE_DIR
WORK_DIR.mkdir(exist_ok=True)

JST = timezone(timedelta(hours=9))

CATEGORY_ID = "2084063128"
KEYWORDS = [
    "Lucchese 7D", "Lucchese 7E", "Lucchese 7.5D",
    "Alden 7D", "Alden 7E", "Alden 7.5D",
]
TARGET_SIZES = {"7D", "7E", "7.5D"}

JPY_TO_TWD = 0.1969

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

EXCLUDE_TERMS = [
    "バット",
    "ボール",
    "スパイク",
    "シューズ",
    "帽子",
    "キャップ",
    "ユニフォーム",
    "シャツ",
    "ウェア",
    "ジャージ",
    "バッグ",
    "袋",
    "ケース",
    "キーホルダー",
    "ステッカー",
    "カタログ",
    "カード",
    "Tシャツ",
    "shirt",
    "jersey",
    "cap",
    "bag",
]

TARGET_TERMS = ["lucchese", "ルケーシー", "alden", "オールデン"]
FOOTWEAR_TERMS = [
    "靴", "シューズ", "ブーツ", "スニーカー", "ローファー", "革靴",
    "shoe", "shoes", "boot", "boots", "loafer", "oxford", "derby",
    "moccasin", "chukka", "chelsea", "penny loafer", "tassel loafer",
]


def configure_console_io() -> None:
    # Avoid Windows console encoding crashes when progress logs include Japanese keywords.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def fetch(url: str, dest: Path) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    text = data.decode("utf-8", errors="replace")
    dest.write_text(text, encoding="utf-8")
    return text


def yen_int(text: str) -> int | None:
    m = re.search(r"([\d,]+)\s*円", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def product_type(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).lower()
    if any(term in normalized for term in ["ブーツ", "ブート", "boot", "boots", "chukka", "chelsea"]):
        return "靴子"
    if is_footwear(normalized):
        return "鞋子"
    return "其他"


def product_brand(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).lower()
    if "lucchese" in normalized or "ルケーシー" in normalized:
        return "Lucchese"
    if "alden" in normalized or "オールデン" in normalized:
        return "Alden"
    return "未明記"


def special_leather(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).lower()
    found = []
    if any(term in normalized for term in ["蜥蜴", "トカゲ", "リザード", "lizard"]):
        found.append("蜥蜴皮")
    if any(term in normalized for term in ["鱷魚", "ワニ", "クロコダイル", "crocodile", "alligator"]):
        found.append("鱷魚皮")
    if any(term in normalized for term in ["鴕鳥", "ダチョウ", "オーストリッチ", "ostrich"]):
        found.append("鴕鳥皮")
    return "、".join(found) if found else ""


def shoe_last(title: str) -> str:
    text = unicodedata.normalize("NFKC", title)
    match = re.search(r"\b(?:last)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9_-]{1,})", text, flags=re.I)
    if match:
        return match.group(1)
    match = re.search(r"([一-龠ぁ-んァ-ヶA-Za-z0-9・ー]{2,}ラスト)", text, flags=re.I)
    if match:
        return match.group(1)
    return "未明記"


def clean_model(value: str, strip_color_suffix: bool = False) -> str | None:
    value = unicodedata.normalize("NFKC", value).strip(" \t\r\n.,()[]「」")
    value = re.sub(r"^B-", "", value, flags=re.I)
    if strip_color_suffix:
        parts = value.split("-")
        if len(parts) > 1 and re.match(r"^(GR|GH)[A-Z0-9]+$", parts[0], flags=re.I):
            while len(parts) > 1 and re.match(r"^[A-Z]{1,4}$", parts[-1], flags=re.I):
                parts.pop()
            value = "-".join(parts)
    upper = value.upper()
    ignore = {
        "PROEDGE",
        "GRAPHIC",
        "BASEBALL",
        "RAWLINGS",
        "ASICS",
        "HOH",
        "MLB",
        "COLOR",
        "SYNC",
        "PREMIUM",
    }
    if upper in ignore:
        return None
    if re.search(r"^\d{5,}[-]?$", upper):
        return None
    if re.search(r"^SP\d+$", upper):
        return None
    if re.search(r"\d+\s*(CM|MM|INCH|インチ)$", upper):
        return None
    if re.search(r"^[WH]\d+(CM|MM)?$", upper):
        return None
    if re.search(r"^\d+(CM|MM)$", upper):
        return None
    if re.search(r"^\d+$", upper):
        return None
    return value


def model_from_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title)
    text = re.sub(r"(管理番号|識別番号|商品番号|出品番号)[:：]?\s*[A-Za-z0-9\-]+", " ", text, flags=re.I)
    explicit_hits = []
    for marker in ["品番", "型番", "メーカー品番", "商品コード"]:
        for match in re.finditer(marker + r"\s*[:：]?\s*([A-Z0-9][A-Z0-9\-]{3,})", text, flags=re.I):
            explicit_hits.append(match.group(1))
    patterns = [
        r"\bRGH-\d+[A-Z0-9]*\b",
        r"\bGR[A-Z0-9][A-Z0-9\-]{4,}\b",
        r"\bGR[A-Z0-9\-]{4,}\b",
        r"\bGH[A-Z0-9][A-Z0-9\-]{4,}\b",
        r"\bRPRO[A-Z0-9\-]{3,}\b",
        r"\bPRO[-A-Z0-9]{3,}\b",
        r"\bMLGR[A-Z0-9\-]{4,}\b",
        r"\bWGM[A-Z0-9\-]{3,}\b",
        r"\bRL\d+[A-Z0-9\-]*\b",
        r"\bRG[-]?\d+[A-Z0-9]*\b",
        r"\bR-[A-Z0-9]{3,}\b",
        r"\bXPG-\d+[A-Z0-9]*\b",
        r"\bBU-\d+[A-Z0-9]*\b",
        r"\bG-\d+[A-Z0-9]*\b",
        r"\b[A-Z]{1,3}\d{2,4}[A-Z0-9]*\b",
        r"\b[A-Z]{1,4}\d{1,3}[A-Z]{1,4}\b",
    ]
    hits: list[tuple[str, bool]] = []
    hits.extend((hit, True) for hit in explicit_hits)
    for pattern in patterns:
        hits.extend((hit, False) for hit in re.findall(pattern, text, flags=re.I))
    cleaned = []
    for hit, strip_color_suffix in hits:
        value = clean_model(hit, strip_color_suffix=strip_color_suffix)
        if not value:
            continue
        upper = value.upper()
        existing_upper = {x.upper() for x in cleaned}
        base = upper.split("-", 1)[0]
        if "-" in upper and base in existing_upper:
            continue
        if any(x.startswith(upper + "-") for x in existing_upper):
            continue
        if upper not in existing_upper:
            cleaned.append(value)
    return ", ".join(cleaned) if cleaned else "未明記"


def extract_item_text(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    parts = []
    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        parts.append(meta["content"])
    script = soup.select_one("script#__NEXT_DATA__")
    if script and script.string:
        try:
            data = json.loads(script.string)
            states = [
                data.get("props", {}).get("pageProps", {}).get("initialState", {}),
                data.get("props", {}).get("initialState", {}),
            ]
            for state in states:
                item = state.get("item", {}).get("detail", {}).get("item", {})
                desc = item.get("description")
                if isinstance(desc, list):
                    parts.append(" ".join(str(x) for x in desc))
                desc_html = item.get("descriptionHtml")
                if desc_html:
                    parts.append(BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True))
        except json.JSONDecodeError:
            pass
    return " ".join(parts)


def maybe_fetch_model_from_item(row: dict) -> str:
    if row["model"] != "未明記":
        return row["model"]
    auction_id = row["link"].rstrip("/").split("/")[-1]
    dest = WORK_DIR / "items" / f"{auction_id}.html"
    dest.parent.mkdir(exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        text = dest.read_text(encoding="utf-8", errors="replace")
    else:
        text = fetch(row["link"], dest)
        time.sleep(random.uniform(2.1, 3.8))
    combined = f"{row['title']} {extract_item_text(text)}"
    return model_from_title(combined)


SPECIAL_NOTE_PATTERN = re.compile(r"379\s*-?\s*X", re.I)


def mentions_special_note(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    return bool(SPECIAL_NOTE_PATTERN.search(normalized))


def fetch_item_detail_text(row: dict) -> str:
    auction_id = row["link"].rstrip("/").split("/")[-1]
    dest = WORK_DIR / "items" / f"{auction_id}.html"
    dest.parent.mkdir(exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        text = dest.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            text = fetch(row["link"], dest)
        except Exception as exc:
            print(f"detail fetch failed {auction_id}: {exc}")
            return ""
        time.sleep(random.uniform(2.1, 3.8))
    return extract_item_text(text)


def extract_size(text: str) -> str | None:
    text = unicodedata.normalize("NFKC", text).upper()
    patterns = [
        r"(?<![A-Z0-9])7\.5\s*D(?![A-Z0-9])",
        r"(?<![A-Z0-9])7\s*[DE](?![A-Z0-9])",
        r"(?<![A-Z0-9])(?:US|USA|JP|サイズ|SIZE)\s*[:：]?\s*(7\.5\s*D|7\s*[DE])(?![A-Z0-9])",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            value = re.sub(r"\s+", "", value).replace("７", "7")
            return value
    return None


def is_target(title: str) -> bool:
    lower = title.lower()
    return any(term.lower() in lower for term in TARGET_TERMS)


def is_footwear(text: str) -> bool:
    lower = unicodedata.normalize("NFKC", text).lower()
    return any(term.lower() in lower for term in FOOTWEAR_TERMS)


def auction_end_time(item) -> str:
    node = item.select_one("[data-auction-endtime]")
    if not node:
        return "未取得"
    try:
        ts = int(node.get("data-auction-endtime"))
    except (TypeError, ValueError):
        return "未取得"
    return datetime.fromtimestamp(ts, tz=JST).strftime("%Y-%m-%d %H:%M")


def parse_page(text: str, keyword: str) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(text, "html.parser")
    rows = []
    for item in soup.select("li.Product"):
        a = item.select_one("a.Product__titleLink")
        if not a:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        link = a.get("href", "").split("?")[0]
        if not link or not is_target(title):
            continue
        img = item.select_one("img.Product__imageData")
        thumbnail = img.get("src", "") if img else ""
        prices = []
        for price_node in item.select(".Product__price"):
            label = price_node.select_one(".Product__label")
            value = price_node.select_one(".Product__priceValue")
            label_text = label.get_text(" ", strip=True) if label else ""
            value_text = value.get_text(" ", strip=True) if value else price_node.get_text(" ", strip=True)
            amount = yen_int(value_text)
            if amount is not None:
                prices.append({"label": label_text or "価格", "jpy": amount})
        rows.append(
            {
                "keyword": keyword,
                "type": product_type(title),
                "brand": product_brand(title),
                "special_leather": special_leather(title),
                "last": shoe_last(title),
                "model": model_from_title(title),
                "size": extract_size(title),
                "end_time": auction_end_time(item),
                "title": title,
                "link": link,
                "thumbnail": thumbnail,
                "prices": prices,
            }
        )
    next_link = soup.select_one('link[rel="next"]')
    return rows, next_link.get("href") if next_link else None


def search_url(keyword: str) -> str:
    q = urllib.parse.quote(keyword)
    va = urllib.parse.quote_plus(keyword)
    return f"https://auctions.yahoo.co.jp/search/search?p={q}&va={va}&b=1&n=50"


def load_previous_links(output_date: str) -> set[str]:
    candidates = []
    for path in OUT_DIR.glob("yahoo_auction_lucchese_alden_*.json"):
        match = re.match(r"yahoo_auction_lucchese_alden_(\d{4}-\d{2}-\d{2})\.json$", path.name)
        if match and match.group(1) < output_date:
            candidates.append((match.group(1), path))
    if not candidates:
        return set()
    candidates.sort(key=lambda pair: pair[0])
    _, latest_path = candidates[-1]
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {row["link"] for row in data.get("rows", []) if row.get("link")}


def price_html(prices: list[dict]) -> str:
    if not prices:
        return "未取得"
    parts = []
    for price in prices:
        twd = round(price["jpy"] * JPY_TO_TWD)
        parts.append(f'{html.escape(price["label"])}: ¥{price["jpy"]:,} / NT${twd:,}')
    return "<br>".join(parts)


def main() -> None:
    configure_console_io()
    seen: dict[str, dict] = {}
    fetch_log = []

    for keyword_index, keyword in enumerate(KEYWORDS, start=1):
        url = search_url(keyword)
        page = 1
        while url:
            safe_kw = re.sub(r"[^A-Za-z0-9ぁ-んァ-ヶ一-龠]+", "_", keyword).strip("_")
            dest = WORK_DIR / f"search_{keyword_index:02d}_{safe_kw}_p{page:02d}.html"
            try:
                text = fetch(url, dest)
            except Exception as exc:
                fallback = keyword.split()[0]
                if page == 1 and fallback != keyword:
                    print(f"search failed {keyword} p{page}: {exc}; fallback={fallback}")
                    url = search_url(fallback)
                    try:
                        text = fetch(url, dest)
                    except Exception as fallback_exc:
                        print(f"fallback failed {fallback}: {fallback_exc}")
                        break
                else:
                    print(f"search failed {keyword} p{page}: {exc}")
                    break
            rows, next_url = parse_page(text, keyword)
            added = 0
            for row in rows:
                if row["link"] not in seen:
                    seen[row["link"]] = row
                    added += 1
                else:
                    existing = seen[row["link"]]
                    if keyword not in existing["keyword"].split(" / "):
                        existing["keyword"] += f" / {keyword}"
            fetch_log.append({"keyword": keyword, "page": page, "rows": len(rows), "new": added, "url": url})
            print(f"{keyword} p{page}: rows={len(rows)} new={added}")
            url = next_url
            page += 1
            time.sleep(random.uniform(1.7, 3.2))

    size_order = {"7D": 0, "7E": 1, "7.5D": 2}
    rows = sorted(seen.values(), key=lambda r: (r["brand"], size_order.get(r.get("size"), 9), r["model"], r["title"]))
    missing_before = sum(1 for row in rows if row["model"] == "未明記")
    for index, row in enumerate(rows, start=1):
        if False and row["model"] == "未明記":
            row["model"] = maybe_fetch_model_from_item(row)
            print(f"model supplement {index}/{len(rows)}: {row['model']}")
        if False and (not row.get("size") or not is_footwear(row["title"])):
            auction_id = row["link"].rstrip("/").split("/")[-1]
            dest = WORK_DIR / "items" / f"{auction_id}.html"
            dest.parent.mkdir(exist_ok=True)
            if dest.exists() and dest.stat().st_size > 0:
                item_text = extract_item_text(dest.read_text(encoding="utf-8", errors="replace"))
            else:
                try:
                    item_page = fetch(row["link"], dest)
                    item_text = extract_item_text(item_page)
                    time.sleep(random.uniform(2.1, 3.8))
                except Exception as exc:
                    print(f"size supplement failed {auction_id}: {exc}")
                    item_text = ""
            detail_text = item_text
            row["size"] = extract_size(f"{row['title']} {item_text}")
        else:
            detail_text = ""
        row["_footwear"] = is_footwear(f"{row['title']} {detail_text}")
    rows = [row for row in rows if row.get("size") in TARGET_SIZES and row.get("_footwear")]
    for row in rows:
        row.pop("_footwear", None)
    rows = sorted(rows, key=lambda r: (TARGET_SIZES.__contains__(r.get("size")), r.get("size") or "", r["model"], r["title"]))
    missing_after = sum(1 for row in rows if row["model"] == "未明記")
    for index, row in enumerate(rows, start=1):
        if row["brand"] == "Alden":
            detail_text = fetch_item_detail_text(row)
            row["mentions_379x"] = mentions_special_note(f"{row['title']} {detail_text}")
            print(f"379X check {index}/{len(rows)}: {row['mentions_379x']}")
        else:
            row["mentions_379x"] = False
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_date = datetime.now().strftime("%Y-%m-%d")
    previous_links = load_previous_links(output_date)
    for row in rows:
        row["is_new"] = row["link"] not in previous_links
    new_count = sum(1 for row in rows if row["is_new"])
    note_379x_count = sum(1 for row in rows if row["mentions_379x"])
    rendered_rows = []
    for row in rows:
        row_class = "data-row is-new" if row["is_new"] else "data-row"
        title_cell = html.escape(row["title"])
        badges = ""
        if row["is_new"]:
            badges += '<span class="badge-new">New!</span>'
        if row["mentions_379x"]:
            badges += '<span class="badge-379x">379X</span>'
        title_cell = badges + title_cell
        rendered_rows.append(
            f'<tr class="{row_class}" data-brand="{html.escape(row["brand"])}" data-size="{html.escape(row.get("size") or "")}" data-new="{"1" if row["is_new"] else "0"}">'
            f"<td>{html.escape(row['brand'])}</td>"
            f"<td>{html.escape(row['model'])}</td>"
            f"<td>{html.escape(row['size'] or '未明記')}</td>"
            f"<td>{html.escape(row.get('special_leather') or '—')}</td>"
            f"<td>{html.escape(row.get('last') or '未明記')}</td>"
            f"<td>{price_html(row['prices'])}</td>"
            f"<td>{html.escape(row.get('end_time') or '未取得')}</td>"
            f"<td>{('<img class=\"thumb\" src=\"' + html.escape(row.get('thumbnail', '')) + '\" alt=\"\">') if row.get('thumbnail') else ''}</td>"
            f"<td>{title_cell}</td>"
            f"<td><a href=\"{html.escape(row['link'])}\" target=\"_blank\" rel=\"noopener\">連結</a></td>"
            "</tr>"
        )
    html_rows = "\n".join(rendered_rows)
    key_html = ", ".join(html.escape(k) for k in KEYWORDS)
    doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yahoo!オークション Lucchese / Alden 尺寸搜尋結果</title>
<style>
body {{ font-family: Arial, "Microsoft JhengHei", sans-serif; margin: 16px; color: #222; }}
h1 {{ font-size: 20px; margin: 0 0 8px; }}
p {{ margin: 3px 0; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 14px; }}
th, td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
th {{ background: #f1f3f5; text-align: left; position: sticky; top: 0; }}
tr.data-row:nth-child(even) {{ background: #f8fafc; }}
tr.is-new {{ background: #fff8e1; }}
tr.is-new:nth-child(even) {{ background: #fff3cd; }}
.badge-new {{ display: inline-block; background: #ff5252; color: #fff; font-weight: bold; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-right: 6px; vertical-align: middle; }}
.badge-379x {{ display: inline-block; background: #5c6bc0; color: #fff; font-weight: bold; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-right: 6px; vertical-align: middle; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin: 12px 0; padding: 10px; background: #eef2ff; border: 1px solid #c7d2fe; }}
.filters label {{ font-weight: bold; }}
.filters select {{ padding: 5px 8px; min-width: 120px; }}
img.thumb {{ width: 90px; height: 90px; object-fit: contain; display: block; }}
.meta {{ background: #f7f7f7; padding: 8px 10px; border: 1px solid #ddd; margin: 8px 0; font-size: 13px; line-height: 1.35; }}
.meta .line {{ display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; }}
.meta .keywords {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; color: #555; }}
.small {{ font-size: 12px; color: #555; }}
a {{ color: #0645ad; }}
</style>
</head>
<body>
<h1>Yahoo!オークション Lucchese / Alden 商品搜尋結果</h1>
<div class="meta">
<div class="line">
<span>來源：Yahoo!オークション全站搜尋</span>
<span>產生：{html.escape(generated_at)}</span>
<span>匯率：1 JPY = {JPY_TO_TWD} TWD</span>
<span>結果：{len(rows)} 筆</span>
<span>新增：{new_count} 筆</span>
<span>提及 379X：{note_379x_count} 筆</span>
<span>尺寸：7D、7E、7.5D</span>
</div>
<div class="keywords" title="{key_html}">關鍵字：{key_html}</div>
</div>
<div class="filters">
<label for="brandFilter">品牌</label><select id="brandFilter"><option value="">全部品牌</option><option value="Alden">Alden</option><option value="Lucchese">Lucchese</option></select>
<label for="sizeFilter">尺寸</label><select id="sizeFilter"><option value="">全部尺寸</option><option value="7D">7D</option><option value="7E">7E</option><option value="7.5D">7.5D</option></select>
<label for="newFilter">New!</label><select id="newFilter"><option value="">全部</option><option value="1">只顯示 New!</option></select>
<span id="resultCount">顯示 {len(rows)} 筆</span>
</div>
<table id="resultsTable">
<thead><tr><th>品牌</th><th>產品型號</th><th>尺寸</th><th>特殊皮革</th><th>楦頭（Last）</th><th>價格（日幣 / 台幣）</th><th>結標時間</th><th>縮圖</th><th>產品 Title</th><th>連結</th></tr></thead>
<tbody>
{html_rows}
</tbody>
</table>
<script>
const brandFilter = document.getElementById('brandFilter');
const sizeFilter = document.getElementById('sizeFilter');
const newFilter = document.getElementById('newFilter');
const resultCount = document.getElementById('resultCount');
function applyFilters() {{
  const brand = brandFilter.value, size = sizeFilter.value, isNew = newFilter.value;
  let count = 0;
  document.querySelectorAll('#resultsTable tbody tr.data-row').forEach(row => {{
    const show = (!brand || row.dataset.brand === brand) && (!size || row.dataset.size === size) && (!isNew || row.dataset.new === isNew);
    row.style.display = show ? '' : 'none';
    if (show) count++;
  }});
  resultCount.textContent = `顯示 ${{count}} 筆`;
}}
brandFilter.addEventListener('change', applyFilters);
sizeFilter.addEventListener('change', applyFilters);
newFilter.addEventListener('change', applyFilters);
</script>
</body>
</html>
"""
    out_file = OUT_DIR / f"yahoo_auction_lucchese_alden_{output_date}.html"
    json_file = OUT_DIR / f"yahoo_auction_lucchese_alden_{output_date}.json"
    out_file.write_text(doc, encoding="utf-8")
    json_file.write_text(
        json.dumps({"rows": rows, "fetch_log": fetch_log, "rate": JPY_TO_TWD}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"HTML={out_file}")
    print(f"JSON={json_file}")
    print(f"COUNT={len(rows)}")


if __name__ == "__main__":
    main()
