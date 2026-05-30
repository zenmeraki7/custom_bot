# """
# fix_and_convert.py
# ==================
# Step 1: Scans all faq_templates/ JSON files, fixes common syntax errors
# Step 2: Converts them all to faqs/types/{type}_faq.json

# Fixes handled:
# - UTF-8 BOM encoding
# - Missing closing ] and }
# - Trailing commas
# - Single quotes instead of double quotes
# - Truncated/incomplete files

# Run:
#     python fix_and_convert.py
# """

# import json
# import re
# import shutil
# from pathlib import Path

# TEMPLATES_DIR = Path("faq_templates")
# OUT_DIR       = Path("faqs/types")
# BACKUP_DIR    = Path("faq_templates_backup")

# PAIR_MAP = {
#     "bakery":              ("bakery_english.json",              "bakery_manglish.json"),
#     "beauty_parlour":      ("beautyparlour_english.json",       "beautyparlour_manglish.json"),
#     "ca_firm":             ("ca_firm_english.json",             "ca_firm_manglish.json"),
#     "dental_clinic":       ("dental_clinic_english.json",       "dental_clinic_manglish.json"),
#     "electronic_products": ("electronic_products_english.json", "electronic_product_.manglish.json"),
#     "gym":                 ("gym_english.json",                 "gym_manglish.json"),
#     "hospital":            ("hospital_english.json",            "hospital_manglish.json"),
#     "hotel":               ("hotel_english.json",               "hotel_manglish.json"),
#     "hr_consultant":       ("HR_consultant_english.json",       "HR_consultfaqs_manglish.json"),
#     "jwellery":            ("jwellery_english.json",            "jwellery_manglish.json"),
#     "law_firm":            ("law_firm_english.json",            "law_firm_manglish.json"),
#     "opticals":            ("opticals_english.json",            "opticals_manglish.json"),
#     "pharmacy":            ("pharmacy_english.json",            "pharmacy_manglish.json"),
#     "real_estate":         ("real_estate_english.json",         "real_estate_manglish.json"),
#     "restaurant":          ("resaturent_english.json",          "restaurent_manglish.json"),
#     "school":              ("school_english.json",              "scool_manglish.json"),
#     "supermarket":         ("supermarket_english.json",         "supermarket_manglish.json"),
#     "travel_agency":       ("travelagency_english.json",        "travelagency_manglish.json"),
# }


# # ── JSON repair ───────────────────────────────────────────────────────────────

# def _read_raw(path: Path) -> str:
#     """Read raw text, trying common encodings."""
#     for enc in ("utf-8-sig", "utf-8", "latin-1"):
#         try:
#             return path.read_text(encoding=enc)
#         except Exception:
#             continue
#     return ""


# def _repair_json(text: str) -> str:
#     """Apply heuristic repairs to broken JSON text."""

#     # Remove BOM if present
#     text = text.lstrip("\ufeff")

#     # Replace smart quotes
#     text = text.replace("\u201c", '"').replace("\u201d", '"')
#     text = text.replace("\u2018", "'").replace("\u2019", "'")

#     # Remove trailing commas before } or ]
#     text = re.sub(r",\s*([\}\]])", r"\1", text)

#     # Try parsing as-is first
#     try:
#         json.loads(text)
#         return text
#     except json.JSONDecodeError as e:
#         # "Extra data" = multiple JSON objects concatenated, not wrapped in array
#         if "Extra data" in str(e):
#             objects = _parse_concatenated(text)
#             if objects:
#                 return json.dumps(objects, ensure_ascii=False)

#     # Count open vs close braces/brackets
#     open_curly   = text.count("{")
#     close_curly  = text.count("}")
#     open_square  = text.count("[")
#     close_square = text.count("]")

#     # Strip trailing whitespace/comma before appending closers
#     text = text.rstrip().rstrip(",").rstrip()

#     # Append missing closers
#     missing_curly  = open_curly  - close_curly
#     missing_square = open_square - close_square

#     # Add them in the right order (innermost first)
#     for _ in range(max(0, missing_curly)):
#         text += "\n}"
#     for _ in range(max(0, missing_square)):
#         text += "\n]"

#     # Try again
#     try:
#         json.loads(text)
#         return text
#     except json.JSONDecodeError:
#         pass

#     # Last resort: wrap bare array items in outer object
#     stripped = text.strip()
#     if stripped.startswith("["):
#         try:
#             json.loads('{"faqs":' + stripped + "}")
#             return '{"faqs":' + stripped + "}"
#         except Exception:
#             pass

#     return text  # return best-effort even if still broken


# def _parse_concatenated(text: str) -> list:
#     """Parse multiple concatenated JSON objects/arrays into a flat list."""
#     items = []
#     decoder = json.JSONDecoder()
#     text = text.strip()
#     pos = 0
#     while pos < len(text):
#         text_from = text[pos:].lstrip()
#         skipped = len(text[pos:]) - len(text_from)
#         pos += skipped
#         if pos >= len(text):
#             break
#         try:
#             obj, end_pos = decoder.raw_decode(text, pos)
#             if isinstance(obj, list):
#                 items.extend(obj)
#             elif isinstance(obj, dict):
#                 items.append(obj)
#             pos += end_pos - pos
#         except json.JSONDecodeError:
#             break
#     return items


# def _parse_fixed(path: Path):
#     """Read, repair, and parse a JSON file. Returns (list_of_faqs, was_repaired)."""
#     raw = _read_raw(path)
#     if not raw.strip():
#         return [], False

#     # Try direct parse first
#     try:
#         data = json.loads(raw.lstrip("\ufeff"))
#     except json.JSONDecodeError:
#         repaired = _repair_json(raw)
#         try:
#             data = json.loads(repaired)
#             # Save repaired file back
#             path.write_text(repaired, encoding="utf-8")
#             return _extract_list(data), True
#         except json.JSONDecodeError as e:
#             print(f"    ✗ Could not repair {path.name}: {e}")
#             return [], False

#     return _extract_list(data), False


# def _extract_list(data) -> list:
#     if isinstance(data, list):
#         return data
#     if isinstance(data, dict):
#         for key in ("faqs", "questions", "items", "data"):
#             if key in data and isinstance(data[key], list):
#                 return data[key]
#     return []


# def _get(faq: dict, *keys) -> str:
#     for k in keys:
#         v = faq.get(k, "")
#         if v:
#             return str(v).strip()
#     return ""


# # ── Main ──────────────────────────────────────────────────────────────────────

# def fix_and_convert():
#     OUT_DIR.mkdir(parents=True, exist_ok=True)

#     # Backup originals once
#     if not BACKUP_DIR.exists():
#         shutil.copytree(TEMPLATES_DIR, BACKUP_DIR)
#         print(f"📦  Backed up originals to {BACKUP_DIR}/\n")

#     total_ok = total_skip = total_repaired = 0

#     print(f"{'Type':<25} {'EN FAQs':>8} {'ML FAQs':>8}  {'Status'}")
#     print("─" * 65)

#     for shop_type, (en_file, ml_file) in PAIR_MAP.items():
#         en_path = TEMPLATES_DIR / en_file if en_file else None
#         ml_path = TEMPLATES_DIR / ml_file if ml_file else None

#         en_faqs, en_repaired = [], False
#         ml_faqs, ml_repaired = [], False

#         if en_path and en_path.exists():
#             en_faqs, en_repaired = _parse_fixed(en_path)
#         elif en_path:
#             print(f"  {'⚠'} {en_file} not found")

#         if ml_path and ml_path.exists():
#             ml_faqs, ml_repaired = _parse_fixed(ml_path)
#         elif ml_path:
#             print(f"  {'⚠'} {ml_file} not found")

#         if en_repaired or ml_repaired:
#             total_repaired += 1

#         if not en_faqs and not ml_faqs:
#             print(f"  {'❌'} {shop_type:<23} {'—':>8} {'—':>8}  no FAQs, skipped")
#             total_skip += 1
#             continue

#         # Build manglish lookup
#         ml_by_pos = {i: f for i, f in enumerate(ml_faqs)}
#         ml_by_cat = {_get(f, "category"): f for f in ml_faqs if _get(f, "category")}

#         source = en_faqs if en_faqs else ml_faqs
#         unified = []

#         for i, faq in enumerate(source):
#             en_q = _get(faq, "question", "q", "Question")
#             en_a = _get(faq, "answer",   "a", "Answer")
#             cat  = _get(faq, "category", "Category") or "general"

#             if not en_q and not en_a:
#                 continue

#             ml_faq = ml_by_pos.get(i) or ml_by_cat.get(cat, {})
#             ml_q   = _get(ml_faq, "question", "q") or en_q
#             ml_a   = _get(ml_faq, "answer",   "a")

#             if not en_faqs:           # manglish-only shop
#                 en_q, ml_q = ml_q, en_q
#                 en_a, ml_a = ml_a, en_a

#             unified.append({
#                 "id":                f"{shop_type}_{cat}_{i}",
#                 "category":          cat,
#                 "question_variants": list(dict.fromkeys(filter(None, [en_q, ml_q]))),
#                 "answer":            en_a,
#                 "answer_ml":         ml_a,
#                 "lang":              "english_manglish",
#                 "tier":              "type",
#             })

#         if not unified:
#             print(f"  {'⚠'} {shop_type:<23} {len(en_faqs):>8} {len(ml_faqs):>8}  0 valid FAQs, skipped")
#             total_skip += 1
#             continue

#         out_path = OUT_DIR / f"{shop_type}_faq.json"
#         out_path.write_text(json.dumps(unified, ensure_ascii=False, indent=2), encoding="utf-8")

#         repaired_note = " (repaired)" if (en_repaired or ml_repaired) else ""
#         print(f"  {'✅'} {shop_type:<23} {len(en_faqs):>8} {len(ml_faqs):>8}  {len(unified)} FAQs written{repaired_note}")
#         total_ok += 1

#     print("─" * 65)
#     print(f"\n  ✅ {total_ok} types converted   🔧 {total_repaired} files auto-repaired   ❌ {total_skip} skipped")
#     print(f"\n  Next steps:")
#     print(f"  1. Restart uvicorn")
#     print(f"  2. Run generate-shop for your shop")
#     print(f"  3. Check terminal for faqs=101+\n")


# if __name__ == "__main__":
#     print(f"\n📂  Templates : {TEMPLATES_DIR}/")
#     print(f"📂  Output    : {OUT_DIR}/\n")
#     fix_and_convert()





import json
import re
from pathlib import Path

FILE = Path("faq_templates/HR_consultant_english.json")

text = FILE.read_text(encoding="utf-8-sig")

# Find every "faqs" block
blocks = re.findall(
    r'\{\s*"faqs"\s*:\s*\[(.*?)\]\s*\}',
    text,
    flags=re.DOTALL
)

if not blocks:
    print("❌ No FAQ blocks found")
    exit()

all_items = []

decoder = json.JSONDecoder()

for block in blocks:
    pos = 0

    while pos < len(block):
        while pos < len(block) and block[pos] in " \t\r\n,":
            pos += 1

        if pos >= len(block):
            break

        try:
            obj, end = decoder.raw_decode(block, pos)

            if isinstance(obj, dict):
                all_items.append(obj)

            pos = end

        except Exception:
            pos += 1

fixed = {
    "faqs": all_items
}

FILE.write_text(
    json.dumps(fixed, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"✅ Fixed successfully")
print(f"✅ Total FAQs: {len(all_items)}")

# Verify
try:
    json.loads(FILE.read_text(encoding="utf-8"))
    print("✅ JSON validation passed")
except Exception as e:
    print("❌ Validation failed:", e)