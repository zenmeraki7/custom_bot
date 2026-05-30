"""
convert_templates.py
====================
One-time converter: reads your existing faq_templates/ split files
and writes unified faqs/types/{type}_faq.json that shop_manager loads.

Run once:
    python convert_templates.py

After this, all your hand-written English + Manglish FAQs are active.
"""

import json
from pathlib import Path

TEMPLATES_DIR = Path("faq_templates")
OUT_DIR       = Path("faqs/types")


def _read_json(path: Path) -> list | dict:
    """Read JSON file handling both utf-8 and utf-8-sig (BOM) encodings."""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            raw = json.loads(path.read_text(encoding=encoding))
            return raw
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"Could not decode {path.name}")


def convert_all():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    en_files = sorted(TEMPLATES_DIR.glob("*_english.json"))
    if not en_files:
        print("❌  No *_english.json files found in faq_templates/")
        return

    for en_path in en_files:
        shop_type = en_path.stem.replace("_english", "")
        ml_path   = TEMPLATES_DIR / f"{shop_type}_manglish.json"

        try:
            en_raw  = _read_json(en_path)
            en_faqs = en_raw.get("faqs", en_raw) if isinstance(en_raw, dict) else en_raw
        except Exception as e:
            print(f"  ❌  {en_path.name}: {e}")
            continue

        ml_faqs = []
        if ml_path.exists():
            try:
                ml_raw  = _read_json(ml_path)
                ml_faqs = ml_raw.get("faqs", ml_raw) if isinstance(ml_raw, dict) else ml_raw
            except Exception as e:
                print(f"  ⚠️   {ml_path.name}: {e} — Manglish answers will be empty")

        ml_by_pos = {i: f for i, f in enumerate(ml_faqs)}
        ml_by_cat = {}
        for f in ml_faqs:
            cat = f.get("category", "")
            if cat:
                ml_by_cat[cat] = f

        unified = []
        for i, en_faq in enumerate(en_faqs):
            en_q = (en_faq.get("question") or en_faq.get("q") or "").strip()
            en_a = (en_faq.get("answer")   or en_faq.get("a") or "").strip()
            cat  = en_faq.get("category", "general")

            if not en_q or not en_a:
                continue

            ml_faq = ml_by_pos.get(i) or ml_by_cat.get(cat, {})
            ml_q   = (ml_faq.get("question") or ml_faq.get("q") or en_q).strip()
            ml_a   = (ml_faq.get("answer")   or ml_faq.get("a") or "").strip()

            unified.append({
                "id":                f"{shop_type}_{cat}_{i}",
                "category":          cat,
                "question_variants": [en_q, ml_q],
                "answer":            en_a,
                "answer_ml":         ml_a,
                "lang":              "english_manglish",
                "tier":              "type",
            })

        if not unified:
            print(f"  ⚠️   {shop_type}: no valid FAQs found, skipping")
            continue

        out_path = OUT_DIR / f"{shop_type}_faq.json"
        out_path.write_text(
            json.dumps(unified, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"  ✅  {shop_type:<30} {len(unified)} FAQs → {out_path}")

    print(f"\n✅  Done. Restart uvicorn to load the new type packs.")


if __name__ == "__main__":
    print(f"\n📂  Reading from:  {TEMPLATES_DIR}/")
    print(f"📂  Writing to:    {OUT_DIR}/\n")
    convert_all()