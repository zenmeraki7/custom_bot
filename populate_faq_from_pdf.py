# """
# populate_faq_from_pdf.py
# ========================
# Pre-fills each shop's FAQ answers from the shop's uploaded PDF (shop_context.json)
# using semantic RAG (cosine similarity), with keyword fallback.

# For every question in your generic faq_templates/*_english.json + *_manglish.json
# files, it calls rag_answer(question, slug) to get a PDF-grounded answer, then
# saves it into shops/{slug}/shop_faq.json as the authoritative answer.

# Result: every FAQ answer reflects the actual shop's PDF — prices, hours, items —
# not generic template text.

# Usage:
#     python populate_faq_from_pdf.py --slug hey-foodie       # one shop
#     python populate_faq_from_pdf.py                         # all shops with PDF
#     python populate_faq_from_pdf.py --slug hey-foodie --dry-run  # preview
# """

# from __future__ import annotations
# import argparse
# import json
# import re
# import shutil
# import time
# from pathlib import Path

# SHOPS_DIR     = Path("shops")
# TEMPLATES_DIR = Path("faq_templates")

# # Auto-discovers all *_english.json and *_manglish.json pairs
# # Pair mapping: type_key -> (english_filename, manglish_filename)
# PAIR_MAP = {
#     "ac_service_center":                   ("AC_service_center_english.json", "AC_service_center_manglish.json"),
#     "adventure_tourism_faqs":              ("adventure_tourism_faqs_english.json", "adventure_tourism_faqs_manglish.json"),
#     "advertising_company":                 ("Advertising_Company_english.json", "Advertising_Company_manglish.json"),
#     "architecture":                        ("architecture_english.json", "architecture_manglish.json"),
#     "auditoriam":                          ("auditoriam_english.json", "auditoriam_manglish.json"),
#     "ayurvedic_clinic":                    ("Ayurvedic_clinc_english.json", "ayurvedic_clinic_manglish.json"),
#     "bakery":                              ("bakery_english.json", "bakery_manglish.json"),
#     "bank":                                ("bank_english.json", "bank_manglish.json"),
#     "beautyparlour":                       ("beautyparlour_english.json", "beautyparlour_manglish.json"),
#     "bike_showroom":                       ("bike_showroom_english.json", "bike_showroom_manglish.json"),
#     "book_store":                          ("book_store_english.json", "book_store_manglish.json"),
#     "ca_firm":                             ("ca_firm_english.json", "ca_firm_manglish.json"),
#     "car_rental":                          ("car_rental_english.json", "car rental_manglish.json"),
#     "catering_service":                    ("catering_service_english.json", "catering_service_manglish.json"),
#     "cleaning_service":                    ("Cleaning_service_english.json", "Cleaning_service_manglish.json"),
#     "coffee_shop":                         ("coffee_shop_english.json", "coffee_shop_manglish.json"),
#     "college":                             ("college_english.json", "college_manglish.json"),
#     "computer_shop":                       ("Computer_shop_english.json", "Computer_shop_manglish.json"),
#     "construction":                        ("construction_english.json", "construction_manglish.json"),
#     "courier_service":                     ("courier_service_english.json", "courier_service_manglish.json"),
#     "dance_academy":                       ("dance_academy_english.json", "dance_acadamy_manglish.json"),
#     "day_care":                            ("day_care_english.json", "day_care_manglish.json"),
#     "dental_clinic":                       ("dental_clinic_english.json", "dental_clinic_manglish.json"),
#     "drvingschool":                        ("drvingschool_english.json", "drvingschool_manglish.json"),
#     "electric_shop":                       ("electric_shop_english.json", "electric_shop_manglish.json"),
#     "electronic_products":                 ("electronic_products_english.json", "electronic_product_.manglish.json"),
#     "event_management":                    ("event_management_english.json", "event_management_manglish.json"),
#     "eye_clinic":                          ("eye_clinic_english.json", "eye_clinic_manglish.json"),
#     "fast_food_faqs":                      ("fast_food_faqs_english.json", "fast_food_faqs_manglish.json"),
#     "fish_shop":                           ("fish_shop_english.json", "fish_shop_manglish.json"),
#     "fitness_supplement_store":            ("fitness_supplement_store_english.json", "fitness_supplement_store_manglish.json"),
#     "footwear_shop":                       ("footwear_shop_english.json", "footwear_shop_manglish.json"),
#     "furniture_shop":                      ("furniture_shop_english.json", "furniture_shop_manglish.json"),
#     "gym":                                 ("gym_english.json", "gym_manglish.json"),
#     "hardware_store_faqs":                 ("hardware_store_faqs_english.json", "hardware_store_faqs_manglish.json"),
#     "home_appliances_store":               ("home_appliances_store_english.json", "home_appliances_store_manglish.json"),
#     "hospital":                            ("hospital_english.json", "hospital_manglish.json"),
#     "hostel":                              ("hostel_english.json", "hostel_manglish.json"),
#     "hotel":                               ("hotel_english.json", "hotel_manglish.json"),
#     "hr_consultant":                       ("HR_consultant_english.json", "HR_consultant_manglish.json"),
#     "immigration":                         ("immigration_english.json", "immigration_manglish.json"),
#     "interior_design":                     ("interior_design_english.json", "interior_design_manglish.json"),
#     "jwellery":                            ("jwellery_english.json", "jwellery_manglish.json"),
#     "kindergarden":                        ("kindergarden_english.json", "kindergarden_manglish.json"),
#     "laundry":                             ("laundry_english.json", "laundry_manglish.json"),
#     "law_firm":                            ("law_firm_english.json", "law_firm_manglish.json"),
#     "logistic":                            ("logistic_english.json", "logistic_manglish.json"),
#     "medical_lab_faqs":                    ("medical_lab_faqs_english.json", "medical_lab_faqs_manglish.json"),
#     "mobile_shop":                         ("mobile_shop_english.json", "mobile_shop_manglish.json"),
#     "opticals":                            ("opticals_english.json", "opticals_manglish.json"),
#     "overseas_education_consultancy_faqs": ("overseas_education_consultancy_faqs_english.json", "overseas_education_consultancy_faqs_manglish.json"),
#     "packers_and_movers":                  ("packers_and_movers_english.json", "packers_and_movers_manglish.json"),
#     "pet_shop":                            ("pet_shop_english.json", "pet_shop_manglish.json"),
#     "pharmacy":                            ("pharmacy_english.json", "pharmacy_manglish.json"),
#     "photography":                         ("photography_english.json", "photography_manglish.json"),
#     "physiotherapy_clinic_faqs":           ("physiotherapy_clinic_faqs_english.json", "physiotherapy_clinic_faqs_manglish.json"),
#     "printing_shop":                       ("printing_shop_english.json", "printing_shop_manglish.json"),
#     "real_estate":                         ("real_estate_english.json", "real_estate_manglish.json"),
#     "resorts":                             ("resorts_english.json", "resorts_manglish.json"),
#     "restaurent":                          ("restaurent_english.json", "restaurent_manglish.json"),
#     "salon":                               ("salon_english.json", "salon_manglish.json"),
#     "school":                              ("school_english.json", "scool_manglish.json"),
#     "skin_clinic_faqs":                    ("skin_clinic_faqs_english.json", "skin_clinic_faqs_manglish.json"),
#     "spa":                                 ("spa_english.json", "spa_manglish.json"),
#     "sports_shop":                         ("Sports_shop_english.json", "Sports_shop_manglish.json"),
#     "stationary_shop":                     ("stationary_shop_english.json", "stationary_shop_manglish.json"),
#     "supermarket":                         ("supermarket_english.json", "supermarket_manglish.json"),
#     "tatto_studio":                        ("tatto_studio_english.json", "tatto_studio_manglish.json"),
#     "taxi_sertvice":                       ("taxi_sertvice_english.json", "taxi_sertvice_manglish.json"),
#     "travelagency":                        ("travelagency_english.json", "travelagency_manglish.json"),
#     "tution":                              ("tution_english.json", "tution_manglish.json"),
#     "watch_shop_faqs":                     ("watch_shop_faqs_english.json", "watch_shop_faqs_manglish.json"),
# }

# # Aliases: old/alternate shop_type strings -> canonical PAIR_MAP key
# PAIR_MAP_ALIASES = {
#     "auditorium": "auditoriam",
#     "beauty_parlour": "beautyparlour",
#     "driving_school": "drvingschool",
#     "restaurant": "restaurent",
#     "taxi_service": "taxi_sertvice",
#     # canonical detection spelling -> (misspelled) PAIR_MAP key
#     "jewellery": "jwellery",
#     "jewelry": "jwellery",
#     "school": "school",
#     "electronics": "electronic_products",
#     "optical": "opticals",
#     "travel_agency": "travelagency",
#     "dance_academy": "dance_academy",
#     "tattoo_studio": "tatto_studio",
#     "ayurvedic_clinic": "ayurvedic_clinic",
#     "car_rental": "car_rental",
#     "cleaning_service": "cleaning_service",
# }


# # ─────────────────────────────────────────────────────────────────────────────
# #  Helpers
# # ─────────────────────────────────────────────────────────────────────────────

# def _load_json(path: Path) -> list:
#     try:
#         text = path.read_text(encoding="utf-8-sig")
#         text = re.sub(r",\s*([\}\]])", r"\1", text)
#         data = json.loads(text)
#         if isinstance(data, list):
#             return data
#         if isinstance(data, dict):
#             for k in ("faqs", "questions", "items", "data"):
#                 if k in data and isinstance(data[k], list):
#                     return data[k]
#     except Exception as e:
#         print(f"  ⚠  Could not load {path.name}: {e}")
#     return []


# def _get(faq: dict, *keys: str) -> str:
#     for k in keys:
#         v = faq.get(k, "")
#         if v and str(v).strip():
#             return str(v).strip()
#     return ""


# def _detect_shop_type(slug: str) -> str:
#     cfg_path = SHOPS_DIR / slug / "shop_config.json"
#     if cfg_path.exists():
#         try:
#             cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
#             return cfg.get("shop_type", "restaurant")
#         except Exception:
#             pass
#     return "restaurant"


# # ─────────────────────────────────────────────────────────────────────────────
# #  Core logic
# # ─────────────────────────────────────────────────────────────────────────────

# def _is_ollama_up() -> bool:
#     import ollama_client
#     return ollama_client.is_up()

# def _process_template(
#     template_path: Path,
#     lang: str,
#     slug: str,
#     existing_map: dict,
#     dry_run: bool,
#     rag_fn,
#     use_rag: bool = True,
# ) -> list[dict]:
#     """Process one template file — kept for backwards compat.
#     Paired processing is done in _process_paired_templates() below."""
#     faqs = _load_json(template_path)
#     if not faqs:
#         return []

#     results = []
#     for i, faq in enumerate(faqs):
#         q       = _get(faq, "question", "q", "Question")
#         generic = _get(faq, "answer", "a", "Answer")
#         if not q or not generic:
#             continue

#         cat = _get(faq, "category", "Category") or "general"
#         key = q.lower()[:60]

#         rag_ans = None
#         if not dry_run and use_rag:
#             try:
#                 rag_ans = rag_fn(q, slug, lang=lang)
#                 time.sleep(0.03)
#             except Exception as e:
#                 print(f"    ⚠  RAG error for '{q[:40]}': {e}")

#         final_en = rag_ans if (rag_ans and lang == "english") else generic
#         final_ml = rag_ans if (rag_ans and lang == "manglish") else None

#         status = "RAG ✓" if rag_ans else "generic"

#         if key in existing_map:
#             entry = existing_map[key]
#             if lang == "english":
#                 entry["a"] = final_en
#                 entry["source"] = "pdf_rag"
#             elif lang == "manglish" and final_ml:
#                 entry["a_ml"] = final_ml
#             results.append(entry)
#             print(f"    [{status}] update: {q[:50]}")
#         else:
#             entry = {
#                 "id":       f"{cat}_{re.sub(r'[^a-z0-9]', '_', q.lower()[:30])}_{i}",
#                 "q":        q,
#                 "variants": faq.get("question_variants", []),
#                 "a":        final_en,
#                 "category": cat,
#                 "section":  cat,
#                 "source":   "pdf_rag" if rag_ans else "template",
#                 "lang":     "english_manglish",
#             }
#             if final_ml:
#                 entry["a_ml"] = final_ml
#             results.append(entry)
#             print(f"    [{status}] new:    {q[:50]}")

#     return results


# def _process_paired_templates(
#     en_path: Path,
#     ml_path: Path | None,
#     slug: str,
#     existing_map: dict,
#     dry_run: bool,
#     rag_fn,
#     use_rag: bool = True,
# ) -> list[dict]:
#     """
#     Process English + Manglish templates TOGETHER, pairing by position.

#     Each index i in en_path matches index i in ml_path (files are authored
#     in parallel). Creates/updates ONE entry per FAQ with:
#         q     = English question
#         a     = English answer (RAG-grounded if Ollama is up)
#         q_ml  = Manglish question
#         a_ml  = Manglish answer (RAG-grounded if Ollama is up)

#     This is the correct design: shop_manager then indexes q with _qlang="en"
#     and q_ml with _qlang="ml", so Manglish queries never match English FAQs.
#     """
#     en_faqs = _load_json(en_path)
#     ml_faqs = _load_json(ml_path) if (ml_path and ml_path.exists()) else []

#     if not en_faqs:
#         return []

#     # Manglish answers are paired to English questions BY POSITION (ml_faqs[i]).
#     # If the two template files have different lengths, that pairing silently
#     # cross-wires (a Manglish answer about hours lands on a price question).
#     # Warn loudly so the misalignment is caught at generation, not by a
#     # customer getting a wrong-topic Manglish reply.
#     if ml_faqs and len(ml_faqs) != len(en_faqs):
#         print(f"    ⚠️  LENGTH MISMATCH: {en_path.name} has {len(en_faqs)} FAQs "
#               f"but {ml_path.name if ml_path else '?'} has {len(ml_faqs)}. "
#               f"Manglish answers may pair to the wrong questions. "
#               f"Only the first {min(len(en_faqs), len(ml_faqs))} align safely.")

#     results = []
#     for i, en_faq in enumerate(en_faqs):
#         en_q       = _get(en_faq, "question", "q", "Question")
#         en_generic = _get(en_faq, "answer", "a", "Answer")
#         if not en_q or not en_generic:
#             continue

#         cat = _get(en_faq, "category", "Category") or "general"
#         en_key = en_q.lower()[:60]

#         # Paired Manglish entry (same index)
#         ml_faq  = ml_faqs[i] if i < len(ml_faqs) else {}
#         ml_q    = _get(ml_faq, "question", "q", "Question")
#         ml_generic = _get(ml_faq, "answer", "a", "Answer")

#         # RAG-ground both languages
#         en_rag = None
#         ml_rag = None
#         if not dry_run and use_rag:
#             try:
#                 en_rag = rag_fn(en_q, slug, lang="english")
#                 time.sleep(0.02)
#             except Exception as e:
#                 print(f"    ⚠  RAG error (en) '{en_q[:40]}': {e}")
#             if ml_q:
#                 try:
#                     ml_rag = rag_fn(ml_q, slug, lang="manglish")
#                     time.sleep(0.02)
#                 except Exception as e:
#                     print(f"    ⚠  RAG error (ml) '{ml_q[:40]}': {e}")

#         final_en = en_rag or en_generic
#         final_ml = ml_rag or ml_generic

#         status = ("RAG ✓" if en_rag else "generic") + ("+" if ml_rag else "")

#         if en_key in existing_map:
#             entry = existing_map[en_key]
#             entry["a"] = final_en
#             entry["source"] = "pdf_rag" if en_rag else "template"
#             if ml_q:
#                 entry["q_ml"] = ml_q
#             if final_ml:
#                 entry["a_ml"] = final_ml
#             results.append(entry)
#             print(f"    [{status}] update: {en_q[:50]}")
#         else:
#             entry = {
#                 "id":       f"{cat}_{re.sub(r'[^a-z0-9]', '_', en_q.lower()[:30])}_{i}",
#                 "q":        en_q,
#                 "variants": en_faq.get("question_variants", []),
#                 "a":        final_en,
#                 "category": cat,
#                 "section":  cat,
#                 "source":   "pdf_rag" if en_rag else "template",
#                 "lang":     "english_manglish",
#             }
#             if ml_q:
#                 entry["q_ml"] = ml_q
#             if final_ml:
#                 entry["a_ml"] = final_ml
#             results.append(entry)
#             print(f"    [{status}] new:    {en_q[:50]}")

#     return results


# def run(slug: str, dry_run: bool = False) -> None:
#     from shop_rag import rag_answer

#     slug_dir = SHOPS_DIR / slug
#     ctx_path = slug_dir / "shop_context.json"
#     faq_path = slug_dir / "shop_faq.json"

#     if not slug_dir.exists():
#         print(f"  ❌  Shop dir not found: {slug_dir}")
#         return
#     if not ctx_path.exists():
#         print(f"  ⚠   No shop_context.json for '{slug}' — run PDF extraction first")
#         return

#     # Load existing shop_faq.json
#     existing: list[dict] = []
#     if faq_path.exists():
#         try:
#             existing = json.loads(faq_path.read_text(encoding="utf-8"))
#         except Exception:
#             pass

#     # Build lookup map: first_question_lower -> faq_entry
#     existing_map: dict[str, dict] = {}
#     for entry in existing:
#         q = (entry.get("q") or "").lower()[:60]
#         if q:
#             existing_map[q] = entry

#     shop_type = _detect_shop_type(slug)
#     shop_type = PAIR_MAP_ALIASES.get(shop_type, shop_type)  # normalize old/alt type strings
#     en_file, ml_file = PAIR_MAP.get(shop_type, (None, None))

#     new_entries: list[dict] = []

#     # Single upfront Ollama check — avoids 60s hang per FAQ when Ollama is down
#     use_rag = not dry_run and _is_ollama_up()
#     if not use_rag and not dry_run:
#         print(f"  ℹ️  Ollama not running — using template answers directly (no RAG grounding)")
#         print(f"  ℹ️  Start Ollama first for PDF-grounded answers: ollama serve")

#     # Process English + Manglish templates TOGETHER (paired by position).
#     # This creates one entry per FAQ with both q+a (English) and q_ml+a_ml (Manglish),
#     # so the embedding index can separate them by language at search time.
#     if en_file:
#         en_path = TEMPLATES_DIR / en_file
#         ml_path = (TEMPLATES_DIR / ml_file) if ml_file else None
#         if en_path.exists():
#             print(f"\n  Paired templates: {en_file}" + (f" + {ml_file}" if ml_file else ""))
#             new_entries.extend(
#                 _process_paired_templates(
#                     en_path, ml_path, slug, existing_map, dry_run, rag_answer, use_rag
#                 )
#             )
#         else:
#             print(f"  ⚠  English template not found: {en_path}")

#     # Merge new entries into existing (new first so embeddings prioritize them)
#     seen_keys: set[str] = set()
#     final: list[dict] = []
#     for entry in new_entries + existing:
#         key = (entry.get("q") or "").lower()[:60]
#         if key not in seen_keys:
#             seen_keys.add(key)
#             final.append(entry)

#     print(f"\n  Total FAQs: {len(existing)} → {len(final)}")

#     if dry_run:
#         print("  [DRY RUN] Nothing written.")
#         return

#     # Backup + write
#     if faq_path.exists():
#         shutil.copy(faq_path, faq_path.with_suffix(".json.bak"))
#     faq_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
#     print(f"  ✅  Written: {faq_path}")
#     print(f"\n  Next steps:")
#     print(f"  1. Restart uvicorn — shop_manager rebuilds embeddings automatically")
#     print(f"  2. Test: 'biriyani price ethra?', 'menu enthu und?'\n")


# # ─────────────────────────────────────────────────────────────────────────────
# #  Main
# # ─────────────────────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Pre-fill shop FAQs from PDF via RAG")
#     parser.add_argument("--slug",    help="Shop slug (e.g. hey-foodie). Omit for all shops.")
#     parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
#     args = parser.parse_args()

#     if args.slug:
#         slugs = [args.slug]
#     else:
#         slugs = [
#             d.name for d in sorted(SHOPS_DIR.iterdir())
#             if d.is_dir() and (d / "shop_context.json").exists()
#         ]
#         if not slugs:
#             print("No shops with shop_context.json found.")
#             raise SystemExit(0)

#     for sl in slugs:
#         print(f"\n{'='*55}")
#         print(f"  Shop: {sl}")
#         print(f"{'='*55}")
#         run(sl, dry_run=args.dry_run)





"""
populate_faq_from_pdf.py
========================
Pre-fills each shop's FAQ answers from the shop's uploaded PDF (shop_context.json)
using semantic RAG (cosine similarity), with keyword fallback.

For every question in your generic faq_templates/*_english.json + *_manglish.json
files, it calls rag_answer(question, slug) to get a PDF-grounded answer, then
saves it into shops/{slug}/shop_faq.json as the authoritative answer.

Result: every FAQ answer reflects the actual shop's PDF — prices, hours, items —
not generic template text.

Usage:
    python populate_faq_from_pdf.py --slug hey-foodie       # one shop
    python populate_faq_from_pdf.py                         # all shops with PDF
    python populate_faq_from_pdf.py --slug hey-foodie --dry-run  # preview
"""

from __future__ import annotations
import argparse
import json
import re
import shutil
import time
from pathlib import Path

SHOPS_DIR     = Path("shops")

# Previously this whitelist meant ~90% of categories (hours, location,
# policies, parking, wifi, offers) NEVER touched the shop's actual PDF --
# they shipped the generic hardcoded template verbatim in both languages
# no matter what the PDF said. "Reply with the shop's exact info" requires
# grounding every category, not just price/item ones. Speed is now
# controlled by the use_rag flag itself (run(..., use_rag_flag=False) /
# --fast), not by silently skipping categories.
def _needs_rag(category: str) -> bool:
    return True


# Reject obviously-broken Manglish so it never gets SAVED as answer_ml.
# Broken = mixed half-English verbs glued to Manglish, trailing fragments,
# or the tell-tale "X-inu ... cheyyum" mash. When rejected, we keep the
# clean hand-written template Manglish instead.
import re as _re_v
_BROKEN_ML = _re_v.compile(
    r"[—–-]\s*$"                               # trailing dash fragment
    r"|\b\w+-(inu|inte|il| inu)\s+\w+\s+(cheyyum|cheyyaam)\b"  # "customer-inu munpu cheyyum"
    r"|\b(provide|properly|professional|customer|service)\s+\w*\s*(cheyyum|cheyyaam|cheythu)\b",
    _re_v.IGNORECASE,
)

def _ml_is_clean(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 5:
        return False
    return not bool(_BROKEN_ML.search(t))
TEMPLATES_DIR = Path("faq_templates")

# Auto-discovers all *_english.json and *_manglish.json pairs
# Pair mapping: type_key -> (english_filename, manglish_filename)
PAIR_MAP = {
    "ac_service_center":                   ("AC_service_center_english.json", "AC_service_center_manglish.json"),
    "adventure_tourism_faqs":              ("adventure_tourism_faqs_english.json", "adventure_tourism_faqs_manglish.json"),
    "advertising_company":                 ("Advertising_Company_english.json", "Advertising_Company_manglish.json"),
    "architecture":                        ("architecture_english.json", "architecture_manglish.json"),
    "auditoriam":                          ("auditoriam_english.json", "auditoriam_manglish.json"),
    "ayurvedic_clinic":                    ("Ayurvedic_clinc_english.json", "ayurvedic_clinic_manglish.json"),
    "bakery":                              ("bakery_english.json", "bakery_manglish.json"),
    "bank":                                ("bank_english.json", "bank_manglish.json"),
    "beautyparlour":                       ("beautyparlour_english.json", "beautyparlour_manglish.json"),
    "bike_showroom":                       ("bike_showroom_english.json", "bike_showroom_manglish.json"),
    "book_store":                          ("book_store_english.json", "book_store_manglish.json"),
    "ca_firm":                             ("ca_firm_english.json", "ca_firm_manglish.json"),
    "car_rental":                          ("car_rental_english.json", "car rental_manglish.json"),
    "catering_service":                    ("catering_service_english.json", "catering_service_manglish.json"),
    "cleaning_service":                    ("Cleaning_service_english.json", "Cleaning_service_manglish.json"),
    "coffee_shop":                         ("coffee_shop_english.json", "coffee_shop_manglish.json"),
    "college":                             ("college_english.json", "college_manglish.json"),
    "computer_shop":                       ("Computer_shop_english.json", "Computer_shop_manglish.json"),
    "construction":                        ("construction_english.json", "construction_manglish.json"),
    "courier_service":                     ("courier_service_english.json", "courier_service_manglish.json"),
    "dance_academy":                       ("dance_academy_english.json", "dance_acadamy_manglish.json"),
    "day_care":                            ("day_care_english.json", "day_care_manglish.json"),
    "dental_clinic":                       ("dental_clinic_english.json", "dental_clinic_manglish.json"),
    "drvingschool":                        ("drvingschool_english.json", "drvingschool_manglish.json"),
    "electric_shop":                       ("electric_shop_english.json", "electric_shop_manglish.json"),
    "electronic_products":                 ("electronic_products_english.json", "electronic_product_.manglish.json"),
    "event_management":                    ("event_management_english.json", "event_management_manglish.json"),
    "eye_clinic":                          ("eye_clinic_english.json", "eye_clinic_manglish.json"),
    "fast_food_faqs":                      ("fast_food_faqs_english.json", "fast_food_faqs_manglish.json"),
    "fish_shop":                           ("fish_shop_english.json", "fish_shop_manglish.json"),
    "fitness_supplement_store":            ("fitness_supplement_store_english.json", "fitness_supplement_store_manglish.json"),
    "footwear_shop":                       ("footwear_shop_english.json", "footwear_shop_manglish.json"),
    "furniture_shop":                      ("furniture_shop_english.json", "furniture_shop_manglish.json"),
    "gym":                                 ("gym_english.json", "gym_manglish.json"),
    "hardware_store_faqs":                 ("hardware_store_faqs_english.json", "hardware_store_faqs_manglish.json"),
    "home_appliances_store":               ("home_appliances_store_english.json", "home_appliances_store_manglish.json"),
    "hospital":                            ("hospital_english.json", "hospital_manglish.json"),
    "hostel":                              ("hostel_english.json", "hostel_manglish.json"),
    "hotel":                               ("hotel_english.json", "hotel_manglish.json"),
    "hr_consultant":                       ("HR_consultant_english.json", "HR_consultant_manglish.json"),
    "immigration":                         ("immigration_english.json", "immigration_manglish.json"),
    "interior_design":                     ("interior_design_english.json", "interior_design_manglish.json"),
    "jwellery":                            ("jwellery_english.json", "jwellery_manglish.json"),
    "kindergarden":                        ("kindergarden_english.json", "kindergarden_manglish.json"),
    "laundry":                             ("laundry_english.json", "laundry_manglish.json"),
    "law_firm":                            ("law_firm_english.json", "law_firm_manglish.json"),
    "logistic":                            ("logistic_english.json", "logistic_manglish.json"),
    "medical_lab_faqs":                    ("medical_lab_faqs_english.json", "medical_lab_faqs_manglish.json"),
    "mobile_shop":                         ("mobile_shop_english.json", "mobile_shop_manglish.json"),
    "opticals":                            ("opticals_english.json", "opticals_manglish.json"),
    "overseas_education_consultancy_faqs": ("overseas_education_consultancy_faqs_english.json", "overseas_education_consultancy_faqs_manglish.json"),
    "packers_and_movers":                  ("packers_and_movers_english.json", "packers_and_movers_manglish.json"),
    "pet_shop":                            ("pet_shop_english.json", "pet_shop_manglish.json"),
    "pharmacy":                            ("pharmacy_english.json", "pharmacy_manglish.json"),
    "photography":                         ("photography_english.json", "photography_manglish.json"),
    "physiotherapy_clinic_faqs":           ("physiotherapy_clinic_faqs_english.json", "physiotherapy_clinic_faqs_manglish.json"),
    "printing_shop":                       ("printing_shop_english.json", "printing_shop_manglish.json"),
    "real_estate":                         ("real_estate_english.json", "real_estate_manglish.json"),
    "resorts":                             ("resorts_english.json", "resorts_manglish.json"),
    "restaurent":                          ("restaurent_english.json", "restaurent_manglish.json"),
    "salon":                               ("salon_english.json", "salon_manglish.json"),
    "school":                              ("school_english.json", "scool_manglish.json"),
    "skin_clinic_faqs":                    ("skin_clinic_faqs_english.json", "skin_clinic_faqs_manglish.json"),
    "spa":                                 ("spa_english.json", "spa_manglish.json"),
    "sports_shop":                         ("Sports_shop_english.json", "Sports_shop_manglish.json"),
    "stationary_shop":                     ("stationary_shop_english.json", "stationary_shop_manglish.json"),
    "supermarket":                         ("supermarket_english.json", "supermarket_manglish.json"),
    "tatto_studio":                        ("tatto_studio_english.json", "tatto_studio_manglish.json"),
    "taxi_sertvice":                       ("taxi_sertvice_english.json", "taxi_sertvice_manglish.json"),
    "travelagency":                        ("travelagency_english.json", "travelagency_manglish.json"),
    "tution":                              ("tution_english.json", "tution_manglish.json"),
    "watch_shop_faqs":                     ("watch_shop_faqs_english.json", "watch_shop_faqs_manglish.json"),
}

# Aliases: old/alternate shop_type strings -> canonical PAIR_MAP key
PAIR_MAP_ALIASES = {
    "auditorium": "auditoriam",
    "beauty_parlour": "beautyparlour",
    "driving_school": "drvingschool",
    "restaurant": "restaurent",
    "taxi_service": "taxi_sertvice",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> list:
    try:
        text = path.read_text(encoding="utf-8-sig")
        text = re.sub(r",\s*([\}\]])", r"\1", text)
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("faqs", "questions", "items", "data"):
                if k in data and isinstance(data[k], list):
                    return data[k]
    except Exception as e:
        print(f"  ⚠  Could not load {path.name}: {e}")
    return []


def _get(faq: dict, *keys: str) -> str:
    for k in keys:
        v = faq.get(k, "")
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _faq_key(entry: dict) -> str:
    """
    Dedup/lookup key for a FAQ entry, regardless of which generator wrote it.
    generate_shop.py writes {"question_variants": [...], "answer": ...} —
    NO "q" key at all. populate_faq_from_pdf.py's own template path writes
    {"q": ..., "a": ...}. Reading entry.get("q") unconditionally (the old
    code) returns "" for every generate_shop.py-authored entry, so every
    one of them collapses onto the same empty-string dict key and all but
    the last are silently dropped on merge. This is why a shop_faq.json
    built by /admin/generate-shop (question_variants schema) could lose
    ~230 of its 230 entries down to 1 the moment populate_faq_from_pdf.py
    touched it afterward.
    """
    variants = entry.get("question_variants")
    if isinstance(variants, list) and variants:
        return str(variants[0]).lower().strip()[:60]
    return _get(entry, "q", "question", "Question").lower()[:60]


def _detect_shop_type(slug: str) -> str:
    cfg_path = SHOPS_DIR / slug / "shop_config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg.get("shop_type", "restaurant")
        except Exception:
            pass
    return "restaurant"


# ─────────────────────────────────────────────────────────────────────────────
#  Core logic
# ─────────────────────────────────────────────────────────────────────────────

def _is_ollama_up() -> bool:
    import ollama_client
    return ollama_client.is_up()

def _process_template(
    template_path: Path,
    lang: str,
    slug: str,
    existing_map: dict,
    dry_run: bool,
    rag_fn,
    use_rag: bool = True,
) -> list[dict]:
    """Process one template file — kept for backwards compat.
    Paired processing is done in _process_paired_templates() below."""
    faqs = _load_json(template_path)
    if not faqs:
        return []

    results = []
    for i, faq in enumerate(faqs):
        q       = _get(faq, "question", "q", "Question")
        generic = _get(faq, "answer", "a", "Answer")
        if not q or not generic:
            continue

        cat = _get(faq, "category", "Category") or "general"
        key = q.lower()[:60]

        rag_ans = None
        if not dry_run and use_rag:
            try:
                rag_ans = rag_fn(q, slug, lang=lang)
                time.sleep(0.03)
            except Exception as e:
                print(f"    ⚠  RAG error for '{q[:40]}': {e}")

        final_en = rag_ans if (rag_ans and lang == "english") else generic
        final_ml = rag_ans if (rag_ans and lang == "manglish") else None

        status = "RAG ✓" if rag_ans else "generic"

        if key in existing_map:
            entry = existing_map[key]
            if lang == "english":
                entry["a"] = final_en
                entry["source"] = "pdf_rag"
            elif lang == "manglish" and final_ml:
                entry["a_ml"] = final_ml
            results.append(entry)
            print(f"    [{status}] update: {q[:50]}")
        else:
            entry = {
                "id":       f"{cat}_{re.sub(r'[^a-z0-9]', '_', q.lower()[:30])}_{i}",
                "q":        q,
                "variants": faq.get("question_variants", []),
                "a":        final_en,
                "category": cat,
                "section":  cat,
                "source":   "pdf_rag" if rag_ans else "template",
                "lang":     "english_manglish",
            }
            if final_ml:
                entry["a_ml"] = final_ml
            results.append(entry)
            print(f"    [{status}] new:    {q[:50]}")

    return results


def _process_paired_templates(
    en_path: Path,
    ml_path: Path | None,
    slug: str,
    existing_map: dict,
    dry_run: bool,
    rag_fn,
    use_rag: bool = True,
) -> list[dict]:
    """
    Process English + Manglish templates TOGETHER, pairing by CATEGORY.

    Both files share category strings even when list order/length drifts
    (independent edits over time). Each English question is paired with the
    next unused Manglish entry sharing its category, not by raw list index.
    Creates/updates ONE entry per FAQ with:
        q     = English question
        a     = English answer (RAG-grounded if Ollama is up)
        q_ml  = Manglish question
        a_ml  = Manglish answer (RAG-grounded if Ollama is up)

    This is the correct design: shop_manager then indexes q with _qlang="en"
    and q_ml with _qlang="ml", so Manglish queries never match English FAQs.
    """
    en_faqs = _load_json(en_path)
    ml_faqs = _load_json(ml_path) if (ml_path and ml_path.exists()) else []

    if not en_faqs:
        return []

    # Group Manglish entries by category and pop FIFO as we walk the English
    # list, instead of trusting raw list position. Two independently-edited
    # template files (someone added/reordered a question in one but not the
    # other) silently desyncs positional pairing -- e.g. the English question
    # for "group booking" ending up paired with the Manglish text for
    # "reschedule". Category is the one thing both files reliably share.
    from collections import defaultdict, deque
    _ml_by_cat: dict[str, deque] = defaultdict(deque)
    for _mf in ml_faqs:
        _mcat = (_get(_mf, "category", "Category") or "general").strip().lower()
        _ml_by_cat[_mcat].append(_mf)

    _pairing_warnings = 0

    results = []
    for i, en_faq in enumerate(en_faqs):
        en_q       = _get(en_faq, "question", "q", "Question")
        en_generic = _get(en_faq, "answer", "a", "Answer")
        if not en_q or not en_generic:
            continue

        cat = _get(en_faq, "category", "Category") or "general"
        en_key = en_q.lower()[:60]

        # Paired Manglish entry, matched by category (not list position)
        _cat_key = cat.strip().lower()
        if _ml_by_cat.get(_cat_key):
            ml_faq = _ml_by_cat[_cat_key].popleft()
        else:
            ml_faq = {}
            _pairing_warnings += 1
        ml_q    = _get(ml_faq, "question", "q", "Question")
        ml_generic = _get(ml_faq, "answer", "a", "Answer")

        # Ground every category against the shop's PDF by default (_needs_rag
        # always True now -- see its definition for why the old price/item-only
        # whitelist was removed). rag_answer() falls back to the clean generic
        # template answer on its own when the PDF has nothing relevant for a
        # category, so this doesn't risk inventing facts for uncovered topics.
        en_rag = None
        ml_rag = None
        if not dry_run and use_rag and _needs_rag(cat):
            # Retrieve ONCE and reuse for both languages. Retrieving separately
            # per language (using en_q for one call, ml_q for the other) risked
            # the two calls pulling different chunks -- since they're worded
            # differently -- and saving DIFFERENT facts (e.g. two different
            # prices) into a_ml vs a for what is supposed to be the same FAQ.
            shared_ctx = None
            try:
                from shop_rag import retrieve_shared_context
                shared_ctx = retrieve_shared_context(en_q, slug)
            except Exception as e:
                print(f"    ⚠  shared retrieval error '{en_q[:40]}': {e}")

            try:
                en_rag = rag_fn(en_q, slug, lang="english", shared=shared_ctx)
                time.sleep(0.02)
            except Exception as e:
                print(f"    ⚠  RAG error (en) '{en_q[:40]}': {e}")
            if ml_q:
                try:
                    _ml = rag_fn(ml_q, slug, lang="manglish", shared=shared_ctx)
                    # only accept RAG Manglish if it is CLEAN; else keep template
                    ml_rag = _ml if _ml_is_clean(_ml) else None
                    time.sleep(0.02)
                except Exception as e:
                    print(f"    ⚠  RAG error (ml) '{ml_q[:40]}': {e}")

        final_en = en_rag or en_generic
        # Validate the template Manglish too — broken source Manglish should NOT
        # ship. Prefer: clean RAG ml -> clean template ml -> clean English.
        _candidate_ml = ml_rag or ml_generic
        if _candidate_ml and _ml_is_clean(_candidate_ml):
            final_ml = _candidate_ml
        elif ml_generic and _ml_is_clean(ml_generic):
            final_ml = ml_generic
        else:
            # template Manglish is broken/missing — use clean English so the
            # customer gets a correct (if English) answer, never garble
            final_ml = None

        status = ("RAG ✓" if en_rag else "generic") + ("+" if ml_rag else "")

        if en_key in existing_map:
            entry = existing_map[en_key]
            # Write into whichever key this entry's generator already used.
            # faq_engine._get_answer() reads faq["answer"] BEFORE faq["a"] --
            # so on a question_variants-schema entry (generate_shop.py; has
            # "answer", no "a"), setting only entry["a"] here would leave the
            # grounded text saved but silently unreachable at chat time,
            # shadowed by the untouched stale "answer" value.
            if "answer" in entry:
                entry["answer"] = final_en
            else:
                entry["a"] = final_en
            entry["source"] = "pdf_rag" if en_rag else "template"
            if ml_q:
                entry["q_ml"] = ml_q
            if final_ml:
                entry["a_ml"] = final_ml
            else:
                entry.pop("a_ml", None)   # drop stale/broken Manglish answer
            results.append(entry)
            print(f"    [{status}] update: {en_q[:50]}")
        else:
            entry = {
                "id":       f"{cat}_{re.sub(r'[^a-z0-9]', '_', en_q.lower()[:30])}_{i}",
                "q":        en_q,
                "variants": en_faq.get("question_variants", []),
                "a":        final_en,
                "category": cat,
                "section":  cat,
                "source":   "pdf_rag" if en_rag else "template",
                "lang":     "english_manglish",
            }
            if ml_q:
                entry["q_ml"] = ml_q
            if final_ml:
                entry["a_ml"] = final_ml
            results.append(entry)
            print(f"    [{status}] new:    {en_q[:50]}")

    if _pairing_warnings:
        print(f"    ⚠️  {_pairing_warnings} English question(s) had no matching "
              f"Manglish entry for their category — kept English-only rather "
              f"than risk mispairing.")

    return results


def run(slug: str, dry_run: bool = False, use_rag_flag: bool = True) -> None:
    from shop_rag import rag_answer

    slug_dir = SHOPS_DIR / slug
    ctx_path = slug_dir / "shop_context.json"
    faq_path = slug_dir / "shop_faq.json"

    if not slug_dir.exists():
        print(f"  ❌  Shop dir not found: {slug_dir}")
        return
    if not ctx_path.exists():
        print(f"  ⚠   No shop_context.json for '{slug}' — run PDF extraction first")
        return

    # Load existing shop_faq.json
    existing: list[dict] = []
    if faq_path.exists():
        try:
            existing = json.loads(faq_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Build lookup map: first_question_lower -> faq_entry
    existing_map: dict[str, dict] = {}
    for entry in existing:
        q = _faq_key(entry)
        if q:
            existing_map[q] = entry

    shop_type = _detect_shop_type(slug)
    shop_type = PAIR_MAP_ALIASES.get(shop_type, shop_type)  # normalize old/alt type strings
    en_file, ml_file = PAIR_MAP.get(shop_type, (None, None))

    new_entries: list[dict] = []

    # Single upfront Ollama check — avoids 60s hang per FAQ when Ollama is down
    use_rag = use_rag_flag and not dry_run and _is_ollama_up()
    if not use_rag and not dry_run:
        if not use_rag_flag:
            print(f"  ⚡ --fast: using clean template answers + live item prices "
                  f"(no Ollama grounding). Omit --fast to ground against the PDF.")
        else:
            print(f"  ⚠  Ollama not reachable — falling back to generic template "
                  f"answers (unverified against this shop's PDF) + live item "
                  f"prices. Start Ollama and re-run for PDF-grounded answers.")

    # Process English + Manglish templates TOGETHER, paired by CATEGORY (not
    # raw list position -- see _process_paired_templates docstring for why).
    # This creates one entry per FAQ with both q+a (English) and q_ml+a_ml (Manglish),
    # so the embedding index can separate them by language at search time.
    if en_file:
        en_path = TEMPLATES_DIR / en_file
        ml_path = (TEMPLATES_DIR / ml_file) if ml_file else None
        if en_path.exists():
            print(f"\n  Paired templates: {en_file}" + (f" + {ml_file}" if ml_file else ""))
            new_entries.extend(
                _process_paired_templates(
                    en_path, ml_path, slug, existing_map, dry_run, rag_answer, use_rag
                )
            )
        else:
            print(f"  ⚠  English template not found: {en_path}")

    # Merge new entries into existing (new first so embeddings prioritize them)
    seen_keys: set[str] = set()
    final: list[dict] = []
    _no_key_count = 0
    for entry in new_entries + existing:
        key = _faq_key(entry)
        if not key:
            # Can't derive a dedup key (missing q/question_variants entirely)
            # -- keep it rather than silently merging it away against every
            # other keyless entry under the same "" bucket.
            final.append(entry)
            _no_key_count += 1
            continue
        if key not in seen_keys:
            seen_keys.add(key)
            final.append(entry)
    if _no_key_count:
        print(f"  ⚠  {_no_key_count} entr{'y' if _no_key_count == 1 else 'ies'} had no "
              f"derivable question text (missing q/question_variants) — kept as-is, "
              f"not deduped.")

    print(f"\n  Total FAQs: {len(existing)} → {len(final)}")

    if dry_run:
        print("  [DRY RUN] Nothing written.")
        return

    # Backup + write
    if faq_path.exists():
        shutil.copy(faq_path, faq_path.with_suffix(".json.bak"))
    faq_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅  Written: {faq_path}")
    print(f"\n  Next steps:")
    print(f"  1. Restart uvicorn — shop_manager rebuilds embeddings automatically")
    print(f"  2. Test: 'biriyani price ethra?', 'menu enthu und?'\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-fill shop FAQs from PDF via RAG")
    parser.add_argument("--slug",    help="Shop slug (e.g. hey-foodie). Omit for all shops.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--fast",    action="store_true",
                        help="Skip Ollama grounding (FAST but generic): every "
                             "category ships the hardcoded template answer "
                             "verbatim instead of being checked against the "
                             "shop's actual PDF. Grounding is ON by default.")
    args = parser.parse_args()

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = [
            d.name for d in sorted(SHOPS_DIR.iterdir())
            if d.is_dir() and (d / "shop_context.json").exists()
        ]
        if not slugs:
            print("No shops with shop_context.json found.")
            raise SystemExit(0)

    for sl in slugs:
        print(f"\n{'='*55}")
        print(f"  Shop: {sl}")
        print(f"{'='*55}")
        run(sl, dry_run=args.dry_run, use_rag_flag=not args.fast)