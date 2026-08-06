# """
# pdf_extract_v2.py — Shop PDF Extractor (standalone script)
# ============================================================
# Extracted & fixed from pdf_extract_v2.ipynb.

# Usage:
#     pip install pdfplumber pypdf
#     python pdf_extract_v2.py your_shop.pdf
#     python pdf_extract_v2.py your_shop.pdf --out shop_info.json

# Output:
#     shop_info.json  → ready to feed into generate_shop.py or extractor.py

# Sections:
#     1. Install / imports
#     2. Raw text + table extraction (pdfplumber, pypdf fallback)
#     3. Table-based item detection
#     4. Regex-based item detection
#     5. Regex metadata detection (shop_name, phone, hours, payment, etc.)
#     6. Manual fix section (edit MANUAL_OVERRIDES below)
#     7. Save shop_info.json
# """

# import re
# import json
# import sys
# import argparse
# from pathlib import Path
# from collections import defaultdict

# # ── Optional imports (installed at runtime) ───────────────────────────────────
# try:
#     import pdfplumber
# except ImportError:
#     pdfplumber = None

# try:
#     from pypdf import PdfReader # pyright: ignore[reportMissingImports]
# except ImportError:
#     PdfReader = None


# # ══════════════════════════════════════════════════════════════════════════════
# #  MANUAL OVERRIDES
# #  Fill in anything the auto-detection misses, then re-run.
# # ══════════════════════════════════════════════════════════════════════════════

# MANUAL_OVERRIDES = {
#     # 'bot_name':       'MyBot',
#     # 'location':       'MG Road, Ernakulam, Kerala - 682001',
#     # 'city':           'Ernakulam',
#     # 'hours_sunday':   'Sunday 10AM–6PM',
#     # 'whatsapp':       '+91 98765 43210',
#     # 'phone':          '+91 98765 43210',
#     # 'services':       ['Root Canal', 'Braces', 'Implants'],
#     # 'offer_code':     'FIRSTVISIT',
#     # 'offer_desc':     'Free first consultation',
# }


# # ══════════════════════════════════════════════════════════════════════════════
# #  1. NUMBER & PRICE HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def parse_indian_number(s: str):
#     """'3,500' → 3500 | '2,50,000' → 250000"""
#     s = s.strip().replace(',', '')
#     try:
#         return int(s)
#     except ValueError:
#         return None


# def extract_prices(raw: str):
#     """
#     Given a raw price cell like 'Rs. 3,500' or 'Rs. 40,000 - Rs. 80,000'
#     return (price, price_min, price_max).
#     """
#     price = price_min = price_max = None
#     if not raw:
#         return price, price_min, price_max

#     cleaned = re.sub(r'[₹]|Rs\.?', '', raw, flags=re.IGNORECASE).strip()
#     tokens = re.findall(r'\d[\d,]*', cleaned)
#     nums = [v for t in tokens if (v := parse_indian_number(t)) and v > 0]

#     range_match = re.search(r'(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)', cleaned)
#     if range_match:
#         a = parse_indian_number(range_match.group(1))
#         b = parse_indian_number(range_match.group(2))
#         if a and b and a != b:
#             price_min, price_max = min(a, b), max(a, b)
#             return price, price_min, price_max

#     if len(nums) == 1:
#         price = nums[0]
#     elif len(nums) >= 2:
#         if nums[0] < nums[1]:
#             price_min, price_max = nums[0], nums[1]
#         else:
#             price = nums[0]

#     return price, price_min, price_max


# # ══════════════════════════════════════════════════════════════════════════════
# #  2. PDF EXTRACTION
# # ══════════════════════════════════════════════════════════════════════════════

# def extract_pdf(pdf_path: str) -> tuple[list, list, str]:
#     """
#     Returns:
#         all_pages  : list of {page, text}
#         all_tables : list of {page, rows}
#         full_text  : concatenated text string
#     """
#     all_pages: list = []
#     all_tables: list = []
#     full_text = ''

#     if pdfplumber is None and PdfReader is None:
#         print('❌ Neither pdfplumber nor pypdf is installed.')
#         print('   Run: pip install pdfplumber pypdf')
#         sys.exit(1)

#     print(f'\n📄 Extracting: {pdf_path}')
#     print('=' * 60)

#     try:
#         if pdfplumber is None:
#             raise ImportError('pdfplumber not available')

#         with pdfplumber.open(pdf_path) as pdf:
#             print(f'Total pages: {len(pdf.pages)}\n')
#             for pn, page in enumerate(pdf.pages, 1):
#                 text = page.extract_text(x_tolerance=3, y_tolerance=3) or ''
#                 text = text.strip()

#                 page_tables = []
#                 for tbl in page.extract_tables() or []:
#                     clean = []
#                     for row in tbl:
#                         cells = [str(c).strip() if c else '' for c in row]
#                         if any(c for c in cells):
#                             clean.append(cells)
#                     if clean:
#                         page_tables.append(clean)
#                         all_tables.append({'page': pn, 'rows': clean})
#                         tbl_text = '\n'.join(' | '.join(r) for r in clean)
#                         text += '\n\n[TABLE]\n' + tbl_text

#                 if text:
#                     all_pages.append({'page': pn, 'text': text})
#                     full_text += f'\n\n[PAGE {pn}]\n' + text

#                 print(f'── PAGE {pn} ────────────────────────────────────────')
#                 print(text[:600] if text else '(no text)')
#                 if page_tables:
#                     print(f'\n  [{len(page_tables)} table(s) on this page]')
#                 print()

#     except Exception as e:
#         print(f'pdfplumber error: {e} — trying pypdf fallback...')
#         if PdfReader is None:
#             print('❌ pypdf not installed either. Exiting.')
#             sys.exit(1)
#         reader = PdfReader(pdf_path)
#         for i, pg in enumerate(reader.pages, 1):
#             t = pg.extract_text() or ''
#             if t.strip():
#                 all_pages.append({'page': i, 'text': t.strip()})
#                 full_text += f'\n\n[PAGE {i}]\n{t.strip()}'
#                 print(f'── PAGE {i} ────────────────────────────────────────')
#                 print(t[:400])
#                 print()

#     print('=' * 60)
#     print(f'\n✅ Extracted {len(all_pages)} pages | {len(all_tables)} tables | {len(full_text):,} total chars')

#     if not full_text.strip():
#         print('\n⚠️  No text found — PDF may be scanned/image-based.')
#         print('   Fix: Upload to https://www.ilovepdf.com/ocr-pdf first, then retry.')

#     return all_pages, all_tables, full_text


# # ══════════════════════════════════════════════════════════════════════════════
# #  3. TABLE-BASED ITEM DETECTION
# # ══════════════════════════════════════════════════════════════════════════════

# # FIX: added hyphen and comma to the allowed character class --
# # real-world section headers commonly include them ("HAIR
# # SERVICES - COMPLETE MENU", "WAXING, THREADING & HAIR REMOVAL").
# # Without this, those headers silently fail to match, and every
# # item table that follows inherits whatever the LAST matching
# # header was -- mis-tagging dozens of real items with the wrong
# # category for the rest of the document. Max length also raised
# # slightly (50 -> 60) for longer subtitled headers.
# SECTION_HEADER_RE = re.compile(r'^\s*([A-Z][A-Z\s&\/\(\)\-,]{3,60})\s*$')

# # ── Junk item filter ──────────────────────────────────────────────────────────
# # Patterns that look like prices but are NOT sellable items
# _JUNK_ITEM_RE = re.compile(
#     r'^('
#     r'gst\s*(no\.?|number)?'           # GST No.
#     r'|~?\d+\s*g\)?'                   # ~250g)
#     r'|pieces?\)?'                     # pieces)
#     r'|traditional\s+recipe'           # description fragment
#     r'|pickle\s*\+'                    # meal description fragment
#     r'|free\s+delivery'                # delivery rule
#     r'|delivery\s+(charge|time|zone|areas?|below|above)'  # delivery metadata
#     r'|minimum\s+order'                # order rule
#     r'|order\s+via'                    # ordering info
#     r'|loyalty\s+card'                 # loyalty programme
#     r'|offer\s+code'                   # offer metadata
#     r'|happy\s+hours?'                 # offer metadata
#     r'|family\s+pack'                  # combo deal label
#     r'|opening\s+hours?'               # hours metadata
#     r'|last\s+order'                   # timing metadata
#     r'|home\s+delivery\s+hours'        # delivery hours
#     r'|breakfast\s+\('                 # weekend breakfast note
#     r'|payment\s+mode'                 # payment metadata
#     r'|catering\s+(?:available|service|for)'  # catering note
#     r')',
#     re.IGNORECASE,
# )

# _MIN_ITEM_NAME_LEN = 3   # skip single-char / two-char fragments
# _MAX_ITEM_NAME_LEN = 80  # skip overly long strings (likely paragraphs)


# def is_valid_item(name: str) -> bool:
#     """
#     Returns True if the name looks like a real sellable item.
#     Filters junk rows that pdf extraction picks up as items.
#     """
#     name = name.strip()
#     if len(name) < _MIN_ITEM_NAME_LEN or len(name) > _MAX_ITEM_NAME_LEN:
#         return False
#     # starts with punctuation / number / bracket — fragment
#     if name[0] in ('~', '(', ')', '+', '-', '.', ',', '#'):
#         return False
#     # purely numeric
#     if re.match(r'^\d[\d\s,\.]*$', name):
#         return False
#     # matches known junk patterns
#     if _JUNK_ITEM_RE.match(name):
#         return False
#     return True


# # Rows that are metadata, not sellable items — skip them
# META_SKIP_RE = re.compile(
#     r'^(Registration\s*No\.?|Address|Phone(?:\s*\(.*?\))?|Emergency\s*Phone|WhatsApp(?:\s*Order)?|'
#     r'Monday|Sunday|Emergency|EMI|Kids\s*Special|Senior\s*Citizen|'
#     r'Payment\s*Modes?|Health\s*Insurance|Free\s*Consultation|'
#     r'FSSAI\s*License|GSTIN?(?:\s*No\.?)?|Zomato|Swiggy|AC\s*Available|Private\s*Dining|'
#     r'Owner(?:\s*/\s*Director)?|Head\s*Chef|Cuisine|Seating\s*(?:Capacity)?|Landmark|'
#     r'Last\s*Order|Home\s*Delivery\s*Hours|Breakfast(?:\s*\(.*?\))?|'
#     r'Free\s*Delivery\s*(?:Above|Below)?|Delivery\s*(?:Charge|Time|Zone|Areas?)|'
#     r'Minimum\s*Order|Order\s*via|Catering|Bulk\s*Order|'
#     r'Offer\s*Code.*|Happy\s*Hours?\s*Offer|Family\s*Pack|Loyalty\s*Card|'
#     r'Weekend\s*Breakfast|Restaurant\s*Name|Equipment|Sterilisation|Parking|'
#     r'Salon\s*Name|Clinic\s*Name|Shop\s*Name|Alternate\s*Phone|'
#     r'Instagram|Facebook|Accessibility|Lift\s*Available)$',
#     re.IGNORECASE
# )


# # ── Section-level catalogue gate (shop-type-agnostic) ───────────────────────
# # META_SKIP_RE above catches specific known ROW labels ("Address", "FSSAI
# # License", "Salon Name", ...) but that list has to be hand-extended every
# # time a new shop TYPE introduces its own admin-row vocabulary -- a pharmacy
# # PDF's "License No." / "Drug Lic. No." / "Public Holidays" / "Night
# # Emergency" / "Net Banking" rows all slipped through this way, because the
# # regex had only ever been tested against restaurant/salon-style PDFs.
# #
# # Rather than keep enumerating labels per industry forever, this reads the
# # table's own SECTION HEADER (already tracked as `current_category`, e.g.
# # "SHOP INFORMATION" / "WORKING HOURS" / "PAYMENT OPTIONS" vs "COMPLETE
# # PRODUCT & SERVICES CATALOGUE") to decide whether the section is even the
# # kind of section that COULD contain sellable items, for any shop type.
# _CATALOG_SECTION_RE = re.compile(
#     r'\b(PRODUCTS?|CATALOGUE|CATALOG|MENU|SERVICES?|TREATMENTS?|'
#     r'PRICE\s*LIST|PRICING|TARIFF|ITEMS?)\b',
#     re.IGNORECASE,
# )
# _NON_CATALOG_SECTION_RE = re.compile(
#     r'\b(INFORMATION|HOURS|TIMING|PAYMENT|DELIVERY|POLICY|POLICIES|'
#     r'OFFERS?|LOYALTY|STAFF|EXPERTISE|CONTACT|ABOUT|LICEN[CS]E|'
#     r'REGISTRATION|TERMS|FAQ)\b',
#     re.IGNORECASE,
# )


# def _section_looks_administrative(category: str) -> bool:
#     """True if this section header reads as shop info/hours/payment/policy
#     content rather than a sellable product/service catalogue. A section that
#     matches BOTH patterns (e.g. "SERVICE INFORMATION & PRICING") is treated
#     as a real catalogue -- the catalogue signal wins on ambiguity, since
#     wrongly dropping a real item is worse than wrongly keeping a borderline
#     admin row (META_SKIP_RE / is_valid_item / the price checks below still
#     get a chance to catch it either way)."""
#     if not category:
#         return False
#     if _CATALOG_SECTION_RE.search(category):
#         return False
#     return bool(_NON_CATALOG_SECTION_RE.search(category))


# def detect_items_from_tables(tables: list) -> tuple[list, list]:
#     items = []
#     extra_facts: list = []
#     seen: set = set()
#     current_category = 'General'

#     for tbl in tables:
#         rows = tbl['rows']
#         if not rows:
#             continue

#         # Single-row table: a pure "Label | Value" fact pair
#         # (e.g. "Loyalty Card | Visit 10 times..."), not a
#         # header+data table. pdfplumber often extracts these as
#         # their own 1-row table -- capture directly as an
#         # extra_fact since there is no header row to consume.
#         if len(rows) == 1 and len(rows[0]) >= 2:
#             label = rows[0][0].strip()
#             detail = next((c.strip() for c in rows[0][1:] if c.strip()), "")
#             if label and detail and len(label) <= 60:
#                 extra_facts.append({"label": label, "detail": detail})
#             continue

#         # Detect single-cell all-caps section header as first row
#         non_empty = [c for c in rows[0] if c.strip()]
#         if len(non_empty) == 1 and SECTION_HEADER_RE.match(non_empty[0]):
#             current_category = non_empty[0].strip()
#             rows = rows[1:]
#             if not rows:
#                 continue

#         header = rows[0]
#         name_col, price_col, desc_col = 0, -1, -1

#         for ci, cell in enumerate(header):
#             cl = cell.lower()
#             if any(k in cl for k in ('name', 'item', 'dish', 'product', 'service', 'treatment', 'type', 'particulars')):
#                 name_col = ci
#             elif any(k in cl for k in ('price', 'rate', 'amount', 'cost', 'fee', 'charge', 'tariff', '₹', 'rs.')):
#                 price_col = ci
#             elif any(k in cl for k in ('description', 'detail', 'desc', 'notes', 'includes', 'inclusion', 'inclusions', 'duration', 'time', 'hrs', 'min')):
#                 desc_col = ci

#         # Auto-detect price column by content if not found in header.
#         # Prefer Rs./₹ columns; skip duration columns (e.g. "1.5 hrs").
#         DURATION_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:hrs?|min(?:utes?)?|hour)', re.IGNORECASE)
#         RS_RE       = re.compile(r'(?:Rs\.?|₹)\s*\d', re.IGNORECASE)

#         if price_col == -1:
#             # First pass: explicit Rs./₹ symbol in values
#             for ci in range(len(header) - 1, 0, -1):
#                 col_vals = [r[ci] for r in rows[1:] if ci < len(r)]
#                 rs_hits  = sum(1 for v in col_vals if RS_RE.search(v))
#                 if col_vals and rs_hits >= max(1, len(col_vals) * 0.3):
#                     price_col = ci
#                     break

#         if price_col == -1:
#             # Second pass: numeric-heavy column, skip duration columns
#             for ci in range(len(header) - 1, 0, -1):
#                 col_vals = [r[ci] for r in rows[1:] if ci < len(r)]
#                 if not col_vals:
#                     continue
#                 if sum(1 for v in col_vals if DURATION_RE.search(v)) > len(col_vals) * 0.4:
#                     continue
#                 if sum(1 for v in col_vals if re.search(r'\d{2,}', v)) > len(col_vals) * 0.4:
#                     price_col = ci
#                     break

#         data_rows = rows[1:] if any(re.search(r'[a-zA-Z]{3,}', c) for c in header) else rows

#         for row in data_rows:
#             if not row or name_col >= len(row):
#                 continue
#             name = row[name_col].strip()
#             if not name or len(name) < 2:
#                 continue

#             # Section header embedded inside table
#             if SECTION_HEADER_RE.match(name) and not any(
#                 re.search(r'\d{2,}', row[ci]) for ci in range(len(row)) if ci != name_col
#             ):
#                 current_category = name.strip()
#                 continue

#             if META_SKIP_RE.match(name):
#                 # Correctly excluded from the item catalogue (not a
#                 # sellable dish/service) -- but capture it as an
#                 # EXTRA FACT instead of silently dropping it, so
#                 # loyalty programmes, offer codes, happy-hour deals,
#                 # combo packs etc. are still available to ground
#                 # the bot's answers instead of vanishing entirely.
#                 fact_value = None
#                 for ci, cell in enumerate(row):
#                     if ci != name_col and cell.strip():
#                         fact_value = cell.strip()
#                         break
#                 if fact_value:
#                     extra_facts.append({"label": name, "detail": fact_value})
#                 continue

#             # ── Section-level catalogue gate (shop-type-agnostic) ────────
#             # Backstop for META_SKIP_RE: even when a row's own label isn't
#             # on the known-metadata list (new shop type, new label we've
#             # never seen), a row sitting under a clearly non-catalogue
#             # section header ("SHOP INFORMATION", "WORKING HOURS", "PAYMENT
#             # OPTIONS", ...) still shouldn't become a sellable item just
#             # because some unrelated number appears in the row.
#             if _section_looks_administrative(current_category):
#                 fact_value = None
#                 for ci, cell in enumerate(row):
#                     if ci != name_col and cell.strip():
#                         fact_value = cell.strip()
#                         break
#                 if fact_value:
#                     extra_facts.append({"label": name, "detail": fact_value})
#                 continue

#             # ── Junk item guard (FIX 1) ──────────────────────────────────
#             if not is_valid_item(name):
#                 continue

#             price = price_min = price_max = None

#             if price_col != -1 and price_col < len(row):
#                 price, price_min, price_max = extract_prices(row[price_col])

#             # Scan all non-name cells if still nothing
#             if not price and not price_min:
#                 for ci, cell in enumerate(row):
#                     if ci == name_col:
#                         continue
#                     p, pn, px = extract_prices(cell)
#                     if pn and px:
#                         price_min, price_max = pn, px
#                         break
#                     if p and p >= 5:
#                         price = p

#             if not price and not price_min:
#                 continue

#             # Skip implausibly small values (phone/address noise)
#             if price and price < 10:
#                 continue
#             if price_min and price_min < 10 and (not price_max or price_max < 100):
#                 continue

#             key = name.lower().strip()
#             if key in seen:
#                 continue
#             seen.add(key)

#             item = {'name': name, 'category': current_category, '_source': 'table'}
#             if desc_col != -1 and desc_col < len(row):
#                 desc = row[desc_col].strip()
#                 if desc and desc.lower() not in ('description', 'details', 'desc', ''):
#                     item['description'] = desc

#             if price_min and price_max and price_min != price_max:
#                 item['price_min'] = price_min
#                 item['price_max'] = price_max
#             elif price:
#                 item['price'] = price
#             elif price_min:
#                 item['price'] = price_min

#             items.append(item)

#     return items, extra_facts


# # ══════════════════════════════════════════════════════════════════════════════
# #  4. REGEX-BASED ITEM DETECTION (from plain text lines)
# # ══════════════════════════════════════════════════════════════════════════════

# PRICE_PATTERNS = [
#     r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s+[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*(?:\/\-|\/-)?$',
#     r'^(.+?)\s*[|\t]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*$',
#     r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s*[₹]\s*(\d[\d,]{1,9})',
# ]

# RANGE_PATTERNS = [
#     r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s+[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*[-–]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})',
#     r'^(.+?)\s*[|\t]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*[-–]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})',
# ]

# HEADER_RE = re.compile(
#     r'^\s*([A-Z][A-Z\s&\/]{3,35}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s*[:\-]?\s*$'
# )


# def _is_junk_item(name, price=None) -> bool:
#     """Generic PDF-extraction junk detector (any shop type). Rejects
#     description fragments mis-parsed as items, and discount % rows stored
#     as tiny prices. No shop-specific words — works for beauty, food,
#     pharmacy, dental, etc."""
#     import re as _re
#     n = (name or "").strip()
#     if not n:
#         return True
#     if n[0].islower():                              # fragment continuation
#         return True
#     if "+" in n or _re.search(r"\(\d+\s*members?\)", n, _re.I):
#         return True
#     if _re.match(r"^(and|with|plus|including|reception|lashes)\b", n, _re.I):
#         return True
#     if price is not None and isinstance(price, (int, float)) and price <= 20:
#         if _re.search(r"discount|loyalty|referral|programme|program|offer|%|percent",
#                       n, _re.I):
#             return True
#     return False


# def detect_items_regex(text: str) -> list:
#     items = []
#     current_category = 'General'
#     seen_names: set = set()

#     for line in text.splitlines():
#         line = line.strip()
#         if not line or len(line) < 4:
#             continue

#         hm = HEADER_RE.match(line)
#         if hm and len(line) < 50 and not re.search(r'\d{3,}', line):
#             current_category = line.strip(':').strip()
#             continue

#         matched = False
#         for pat in RANGE_PATTERNS:
#             m = re.match(pat, line, re.IGNORECASE)
#             if m:
#                 name = m.group(1).strip().strip('|-').strip()
#                 pmin = parse_indian_number(m.group(2))
#                 pmax = parse_indian_number(m.group(3))
#                 if pmin and pmax and 1 <= pmin <= 9_999_999 and pmin < pmax:
#                     key = name.lower()
#                     if key not in seen_names and len(name) >= 3 and is_valid_item(name):
#                         seen_names.add(key)
#                         items.append({
#                             'name': name,
#                             'price_min': pmin,
#                             'price_max': pmax,
#                             'category': current_category,
#                             '_source': 'regex_range',
#                         })
#                         matched = True
#                         break

#         if matched:
#             continue

#         for pat in PRICE_PATTERNS:
#             m = re.match(pat, line, re.IGNORECASE)
#             if m:
#                 name = re.sub(r'\s*\|.*$', '', m.group(1).strip()).strip()
#                 price = parse_indian_number(m.group(2))
#                 if price and 5 <= price <= 9_999_999:
#                     key = re.sub(r'\s*\(.*?\)\s*$', '', name).lower().strip()
#                     if key not in seen_names and len(name) >= 3 and is_valid_item(name):
#                         seen_names.add(key)
#                         items.append({
#                             'name': name,
#                             'price': price,
#                             'category': current_category,
#                             '_source': 'regex',
#                         })
#                         break

#     return items


# # ══════════════════════════════════════════════════════════════════════════════
# #  5. METADATA DETECTION
# # ══════════════════════════════════════════════════════════════════════════════

# def detect_metadata_regex(text: str) -> dict:
#     meta: dict = {
#         'shop_name': None, 'shop_type': None, 'tagline': None,
#         'location': None, 'city': None, 'state': None,
#         'phone': None, 'whatsapp': None, 'email': None, 'website': None,
#         'hours_weekdays': None, 'hours_sunday': None,
#         'payment': [], 'services': [],
#         'delivery_free': None, 'delivery_charge': None,
#         'delivery_days': None, 'delivery_areas': None,
#         'offer_code': None, 'offer_desc': None,
#     }

#     # Phone numbers
#     phone_raw = re.findall(r'(?:\+91|\b0)?[\s\-]?[6-9][\d\s\-]{9,14}', text)

#     def clean_phone(p: str) -> str:
#         digits = re.sub(r'[^\d]', '', p)
#         if digits.startswith('91') and len(digits) == 12:
#             return '+91 ' + digits[2:7] + ' ' + digits[7:]
#         if len(digits) == 10:
#             return '+91 ' + digits[:5] + ' ' + digits[5:]
#         return p.strip()

#     cleaned_phones = []
#     seen_ph: set = set()
#     for p in phone_raw:
#         digits = re.sub(r'[^\d]', '', p)
#         if len(digits) >= 10 and digits[-10] in '6789':
#             key = digits[-10:]
#             if key not in seen_ph:
#                 seen_ph.add(key)
#                 cleaned_phones.append(clean_phone(p))
#     if cleaned_phones:
#         meta['phone'] = cleaned_phones[0]
#         meta['whatsapp'] = cleaned_phones[0]

#     # Email
#     emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', text)
#     if emails:
#         meta['email'] = emails[0]

#     # Website
#     websites = re.findall(r'(?:https?://|www\.)[\w\.-]+\.[a-z]{2,}', text)
#     if websites:
#         meta['website'] = websites[0]

#     # Hours
#     hours = re.findall(
#         r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
#         r'[\s\-–]+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?'
#         r'[\s:]+\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)',
#         text, re.IGNORECASE
#     )
#     if hours:
#         for h in hours:
#             line_match = re.search(re.escape(h) + r'.*?(\d{1,2}(?::\d{2})?\s*(?:AM|PM))', text, re.IGNORECASE)
#             if line_match and line_match.group(1).lower() not in h.lower():
#                 meta['hours_weekdays'] = h + ' - ' + line_match.group(1)
#                 break
#         else:
#             meta['hours_weekdays'] = hours[0]

#     time_ranges = re.findall(
#         r'\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)',
#         text
#     )
#     if time_ranges and not meta['hours_weekdays']:
#         meta['hours_weekdays'] = time_ranges[0]

#     sun_match = re.search(r'Sunday[\s:]+(.{5,50}?(?:AM|PM).*?)(?:\n|$)', text, re.IGNORECASE)
#     if sun_match:
#         meta['hours_sunday'] = 'Sunday: ' + sun_match.group(1).strip()

#     # Location (pincode-based)
#     joined_text = re.sub(r'\n', ' ', text)
#     addr_match = re.search(r'([A-Za-z0-9][A-Za-z0-9 ,\.\-/#]{10,200}?\b(\d{6})\b)', joined_text)
#     if addr_match:
#         meta['location'] = re.sub(r'\s+', ' ', addr_match.group(1)).strip()

#     # City
#     city_match = re.search(
#         r'\b(Thrissur|Kochi|Trivandrum|Thiruvananthapuram|Kozhikode|Calicut|'
#         r'Kollam|Palakkad|Alappuzha|Kannur|Malappuram|Ernakulam|'
#         r'Mumbai|Delhi|Bangalore|Chennai|Hyderabad|Pune|Kolkata|'
#         r'Ahmedabad|Surat|Jaipur|Lucknow|Nagpur|Indore|Bhopal|'
#         r'Patna|Vadodara|Coimbatore|Madurai|Agra|Nashik|Faridabad|'
#         r'Meerut|Rajkot|Varanasi|Srinagar|Aurangabad|Dhanbad|Amritsar|'
#         r'Navi Mumbai|Allahabad|Prayagraj|Ranchi|Howrah|Jabalpur|Gwalior|'
#         r'Vijayawada|Jodhpur|Raipur|Kota|Guwahati|Chandigarh|Solapur|'
#         r'Hubli|Tiruchirappalli|Bareilly|Mysore|Tiruppur|Gurgaon|Gurugram|'
#         r'Mangalore|Belgaum|Gulbarga|Udupi|Manipal)\b',
#         text
#     )
#     if city_match:
#         meta['city'] = city_match.group(1)

#     # State
#     state_match = re.search(
#         r'\b(Kerala|Karnataka|Tamil Nadu|Tamilnadu|Maharashtra|Gujarat|'
#         r'Rajasthan|Uttar Pradesh|Madhya Pradesh|West Bengal|Bihar|'
#         r'Andhra Pradesh|Telangana|Odisha|Punjab|Haryana|Jharkhand|'
#         r'Uttarakhand|Assam|Himachal Pradesh|Goa|Chhattisgarh|Delhi)\b',
#         text
#     )
#     if state_match:
#         meta['state'] = state_match.group(1)

#     # Payment methods
#     pay_keywords = {
#         'UPI': r'\bUPI\b', 'GPay': r'\bGPay\b|Google Pay',
#         'PhonePe': r'\bPhonePe\b', 'Cash': r'\bCash\b',
#         'Cards': r'\bCard\b|Credit Card|Debit Card',
#         'Paytm': r'\bPaytm\b', 'NetBanking': r'Net Banking|NEFT|RTGS',
#         'Cheque': r'\bCheque\b|\bCheck\b',
#     }
#     for method, pat in pay_keywords.items():
#         if re.search(pat, text, re.IGNORECASE):
#             meta['payment'].append(method)

#     # Shop type detection
#     TYPE_KW = {
#         'restaurant':    ['menu', 'biriyani', 'curry', 'dosa', 'restaurant', 'cafe', 'food', 'dining'],
#         'clothing':      ['shirt', 'saree', 'kurta', 'dress', 'garment', 'fashion', 'wear', 'textile'],
#         'dental_clinic': ['dental', 'dentist', 'tooth', 'teeth', 'root canal', 'braces', 'clinic'],
#         'beauty_parlour': ['salon', 'parlour', 'makeup', 'facial', 'bridal', 'spa', 'beauty'],
#         'jewellery':     ['gold', 'silver', 'diamond', 'jewel', 'necklace', 'ring', 'jewellery'],
#         'gym':           ['gym', 'fitness', 'workout', 'membership', 'trainer', 'yoga'],
#         'hospital':      ['hospital', 'doctor', 'ward', 'surgery', 'opd', 'patient', 'medical'],
#         'pharmacy':      ['pharmacy', 'medicine', 'drug', 'tablet', 'prescription', 'chemist'],
#         'optical':       ['optical', 'spectacle', 'glasses', 'lens', 'eye test', 'frame'],
#         'electronics':   ['mobile', 'laptop', 'phone', 'television', 'electronics', 'gadget'],
#         'supermarket':   ['supermarket', 'grocery', 'vegetables', 'fruits', 'mart', 'kirana'],
#         'bakery':        ['bakery', 'cake', 'bread', 'pastry', 'bake', 'cookie'],
#         'hotel':         ['hotel', 'room', 'check-in', 'accommodation', 'resort', 'suite', 'tariff'],
#         'travel_agency': ['tour', 'travel', 'package', 'visa', 'itinerary', 'holiday', 'tourism'],
#         'real_estate':   ['property', 'flat', 'apartment', 'plot', 'villa', 'rent', 'sqft', 'bhk'],
#         'law_firm':      ['lawyer', 'advocate', 'legal', 'court', 'law firm', 'attorney'],
#         'ca_firm':       ['chartered', 'accountant', 'gst', 'income tax', 'audit', 'tds', 'itr'],
#         'school':        ['school', 'college', 'admission', 'student', 'class', 'education'],
#     }
#     tl = text.lower()
#     scores = {t: sum(1 for kw in kws if kw in tl) for t, kws in TYPE_KW.items()}
#     best = max(scores, key=lambda t: scores[t])
#     meta['shop_type'] = best if scores[best] > 0 else 'general'

#     # ── Universal offer extraction (any shop type) ──────────────────────────
#     # Finds an UPPERCASE promo code near "offer/code/coupon/promo" plus the
#     # description after it. Works for FIRSTGLAM (beauty), FIRSTVISIT (dental),
#     # HUNGRY50 (restaurant) — no shop-specific words. A missing offer stays
#     # None (never faked), so the bot uses RAG/handoff instead of inventing one.
#     _offer_re = re.compile(
#         r"(?:offer\s+code|code|coupon|promo)\s+"
#         r"([A-Z][A-Z0-9]{3,15})"
#         r"\s*[-\u2013\u2014:]?\s*"
#         r"([^.\n]{5,80})",
#         re.IGNORECASE,
#     )
#     # code-first format, e.g. "HEALTH5 - 5% off..." (code must contain a digit)
#     _offer_re2 = re.compile(
#         r"(?:^|\n)\s*"
#         r"([A-Z][A-Z0-9]{2,14}\d[A-Z0-9]*|\b[A-Z]{4,}\d{1,3})"
#         r"\s*[-\u2013\u2014:]\s*"
#         r"(\d{1,3}\s*%|\bRs|\bflat|[^.\n]{0,5}off[^.\n]{0,60})",
#         re.IGNORECASE,
#     )
#     _om = _offer_re.search(text)
#     if _om and (_om.group(1).strip().isupper() or any(c.isdigit() for c in _om.group(1))):
#         meta['offer_code'] = _om.group(1).strip()
#         meta['offer_desc'] = _om.group(2).strip().rstrip("-\u2013\u2014: ")
#     else:
#         _om2 = _offer_re2.search(text)
#         if _om2 and any(c.isdigit() for c in _om2.group(1)):
#             meta['offer_code'] = _om2.group(1).strip()
#             meta['offer_desc'] = _om2.group(2).strip()

#     # Shop name from first few clean lines
#     lines = [l.strip() for l in text.splitlines() if l.strip()]
#     for line in lines[:8]:
#         if re.search(r'\d{7,}|@|www\.|http', line):
#             continue
#         if 5 < len(line) < 60 and not line.startswith('['):
#             meta['shop_name'] = line
#             break

#     # Delivery fields -- these dict keys existed above but were never
#     # actually populated by any regex. Restaurant/food-service PDFs
#     # commonly state these as "Free Delivery Above Rs. X",
#     # "Delivery Charge Below Rs.X Rs. Y flat", "Delivery Zone ...",
#     # "Delivery Time ... minutes".
#     _free_above = re.search(
#         r'Free\s+Delivery\s+Above\s+Rs\.?\s*([\d,]+)', text, re.IGNORECASE)
#     if _free_above:
#         meta['delivery_free'] = f"₹{_free_above.group(1)}"

#     _charge = re.search(
#         r'Delivery\s+Charge\s+Below\s+Rs\.?\s*[\d,]+\s+Rs\.?\s*([\d,]+)',
#         text, re.IGNORECASE)
#     if _charge:
#         meta['delivery_charge'] = f"₹{_charge.group(1)} flat"

#     _days = re.search(
#         r'Delivery\s+Time\s+([^\n]{3,60})', text, re.IGNORECASE)
#     if _days:
#         meta['delivery_days'] = _days.group(1).strip().rstrip('.')

#     _areas = re.search(
#         r'Delivery\s+Zone\s+([^\n]{3,150}(?:\n[^\n]{3,80})?)',
#         text, re.IGNORECASE)
#     if _areas:
#         meta['delivery_areas'] = re.sub(r'\s*\n\s*', ' ', _areas.group(1).strip()).rstrip('.')

#     return meta


# # ══════════════════════════════════════════════════════════════════════════════
# #  6. MERGE & BUILD shop_info
# # ══════════════════════════════════════════════════════════════════════════════

# def llm_extract_items(raw_text: str, shop_type: str = "general",
#                       min_needed: int = 5) -> list:
#     """LLM fallback for UNSTRUCTURED PDFs. When table+regex extraction is thin
#     (a real shop owner pasted prose, a flyer, or a non-tabular layout), regex
#     finds almost nothing. This sends the raw text to Ollama and asks for a
#     structured item list. Returns [] on any failure (Ollama down, bad JSON) so
#     the caller safely keeps whatever regex did find. Costs nothing on clean
#     PDFs because the caller only invokes it when regex came back short."""
#     import json as _json
#     import re as _re
#     try:
#         import ollama_client
#     except Exception:
#         return []
#     if not ollama_client.is_up():
#         print("[pdf] LLM fallback skipped — Ollama not running")
#         return []

#     snippet = (raw_text or "")[:4000]
#     if len(snippet.strip()) < 40:
#         return []

#     prompt = (
#         "You are a data extraction tool. Read the shop document below and "
#         "extract every product or service with its price.\n\n"
#         f"SHOP TYPE: {shop_type}\n\n"
#         "OUTPUT FORMAT - return ONLY a JSON array, no other text:\n"
#         '[{"name": "Item Name", "price": 500, "category": "general"}]\n\n'
#         "RULES:\n"
#         "- Extract the item/service NAME and its PRICE as a number (no symbol).\n"
#         "- If a price is a range or 'from X', use the lower number.\n"
#         "- If an item has no price, skip it.\n"
#         "- Use a short category if obvious, else 'general'.\n"
#         "- Do NOT invent items. Only extract what is written.\n"
#         "- Return ONLY the JSON array.\n\n"
#         f"DOCUMENT:\n{snippet}\n\nJSON array:"
#     )

#     try:
#         reply, ok = ollama_client.generate(
#             prompt, temperature=0.1, num_predict=800, lang="english",
#         )
#     except Exception as e:
#         print(f"[pdf] LLM extraction error: {e}")
#         return []
#     if not ok or not reply:
#         return []

#     reply = _re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=_re.M).strip()
#     m = _re.search(r"\[.*\]", reply, _re.S)
#     if not m:
#         return []
#     try:
#         data = _json.loads(m.group(0))
#     except _json.JSONDecodeError:
#         return []

#     items = []
#     seen = set()
#     for d in (data if isinstance(data, list) else []):
#         if not isinstance(d, dict):
#             continue
#         name = str(d.get("name", "")).strip()
#         price = d.get("price")
#         if not name or price is None:
#             continue
#         try:
#             price = int(float(price))
#         except (ValueError, TypeError):
#             continue
#         if price <= 0 or _is_junk_item(name, price):
#             continue
#         key = name.lower()
#         if key in seen:
#             continue
#         seen.add(key)
#         items.append({
#             "name": name,
#             "price": price,
#             "category": str(d.get("category", "general")).strip() or "general",
#             "_source": "llm",
#         })
#     print(f"[pdf] LLM fallback extracted {len(items)} items from unstructured text")
#     return items


# def build_shop_info(auto_meta: dict, table_items: list, regex_items: list,
#                      extra_facts: list | None = None) -> dict:
#     # Merge items (table first — more reliable), deduplicate
#     all_items: list = []
#     seen_names: set = set()
#     for item in table_items + regex_items:
#         clean_name = re.sub(r'\s*\|.*$', '', item['name']).strip()
#         _price = item.get('price') or item.get('price_min')
#         if _is_junk_item(clean_name, _price):
#             continue
#         key = re.sub(r'\s*\(.*?\)\s*$', '', clean_name).lower().strip()
#         if key not in seen_names:
#             seen_names.add(key)
#             all_items.append(item)

#     # Build SHOP_INFO with auto-detected values, override with MANUAL_OVERRIDES
#     shop_info = {
#         # Identity
#         'bot_name':       auto_meta.get('shop_name', '').split()[0][:10] if auto_meta.get('shop_name') else None,
#         'shop_name':      auto_meta.get('shop_name'),
#         'shop_type':      auto_meta.get('shop_type', 'general'),
#         'tagline':        auto_meta.get('tagline'),
#         'description':    None,
#         # Location
#         'location':       auto_meta.get('location'),
#         'city':           auto_meta.get('city'),
#         'state':          auto_meta.get('state', 'Kerala'),
#         # Hours
#         'hours_weekdays': auto_meta.get('hours_weekdays'),
#         'hours_sunday':   auto_meta.get('hours_sunday'),
#         'hours_holiday':  'Check WhatsApp for holiday hours',
#         # Contact
#         'whatsapp':       auto_meta.get('whatsapp'),
#         'phone':          auto_meta.get('phone'),
#         'email':          auto_meta.get('email'),
#         'website':        auto_meta.get('website'),
#         # Payment & Services
#         'payment':        auto_meta.get('payment') or ['UPI', 'Cash', 'Cards'],
#         'services':       [],
#         # Delivery
#         'delivery_areas': auto_meta.get('delivery_areas'),
#         'delivery_free':  auto_meta.get('delivery_free'),
#         'delivery_charge': auto_meta.get('delivery_charge'),
#         'delivery_days':  auto_meta.get('delivery_days'),
#         # Returns
#         'return_days':    0,
#         'return_condition': None,
#         'refund_days':    None,
#         # Offers
#         'offer_code':     auto_meta.get('offer_code'),
#         'offer_desc':     auto_meta.get('offer_desc'),
#         # Escalation
#         'escalate_whatsapp': auto_meta.get('whatsapp'),
#         'escalate_email':    auto_meta.get('email'),
#         # Items (strip internal _source/_line keys before use in generate_shop.py)
#         'shop_items': [
#             {k: v for k, v in item.items() if not k.startswith('_')}
#             for item in all_items
#             if is_valid_item(item.get('name', ''))   # FIX 1: final junk guard
#         ],
#         # Promotional/programme facts correctly excluded from
#         # shop_items (not sellable dishes) but still real, useful
#         # facts -- loyalty cards, offer codes, happy-hour deals,
#         # combo packs. Without this they vanish entirely instead
#         # of being available to ground the bot's answers.
#         'extra_facts': extra_facts or [],
#     }

#     # Apply manual overrides
#     for k, v in MANUAL_OVERRIDES.items():
#         if v is not None:
#             shop_info[k] = v

#     return shop_info


# # ══════════════════════════════════════════════════════════════════════════════
# #  7. PRINT SUMMARY
# # ══════════════════════════════════════════════════════════════════════════════

# OPTIONAL_FIELDS = {
#     'tagline', 'description', 'offer_code', 'offer_desc',
#     'refund_days', 'return_condition', 'delivery_areas',
#     'delivery_free', 'delivery_days', 'delivery_charge',
#     'hours_holiday', 'escalate_whatsapp', 'escalate_email', 'website',
# }

# KEY_FIELDS = [
#     'location', 'city', 'hours_sunday', 'whatsapp', 'phone', 'services',
# ]


# def print_summary(shop_info: dict):
#     print('\n📦 Final shop_info summary:')
#     print('=' * 55)
#     for k, v in shop_info.items():
#         if k == 'shop_items':
#             print(f'  shop_items          : {len(v)} items')
#         elif v and v not in ([], {}, ''):
#             print(f'  ✅ {k:20s}: {str(v)[:50]}')
#         else:
#             print(f'  ⚠️  {k:20s}: MISSING')

#     missing = [
#         k for k, v in shop_info.items()
#         if k not in ('shop_items', 'return_days') and not v and k not in OPTIONAL_FIELDS
#     ]
#     if missing:
#         print(f'\n⚠️  Fields to fill manually: {missing}')
#         print('   Edit MANUAL_OVERRIDES at top of script and re-run')
#     else:
#         print('\n✅ All key fields filled!')


# # ══════════════════════════════════════════════════════════════════════════════
# #  MAIN
# # ══════════════════════════════════════════════════════════════════════════════

# def main():
#     parser = argparse.ArgumentParser(
#         description='Extract shop info from a PDF and output shop_info.json'
#     )
#     parser.add_argument('pdf', help='Path to shop PDF file')
#     parser.add_argument('--out', default='shop_info.json', help='Output JSON file (default: shop_info.json)')
#     args = parser.parse_args()

#     if not Path(args.pdf).exists():
#         print(f'❌ File not found: {args.pdf}')
#         sys.exit(1)

#     # Step 1 — Extract PDF
#     all_pages, all_tables, full_text = extract_pdf(args.pdf)

#     if not full_text.strip():
#         print('No text to process. Exiting.')
#         sys.exit(1)

#     # Step 2 — Print table summary
#     print(f'\n\n{"=" * 60}')
#     print(f'TABLE SUMMARY  ({len(all_tables)} tables found)')
#     print('=' * 60)
#     for ti, tbl in enumerate(all_tables, 1):
#         rows = tbl['rows']
#         print(f'\n┌── Table {ti}  (page {tbl["page"]}, {len(rows)} rows) ──────────────────')
#         for row in rows:
#             truncated = [c[:32] for c in row if c.strip()]
#             if truncated:
#                 print('│ ' + ' │ '.join(truncated))

#     # Step 3 — Detect items
#     print(f'\n\n{"=" * 60}')
#     print('ITEM DETECTION')
#     print('=' * 60)
#     table_items, extra_facts = detect_items_from_tables(all_tables)
#     regex_items = detect_items_regex(full_text)

#     # LLM FALLBACK for unstructured PDFs: if table+regex extraction is thin
#     # (prose menus, flyers, non-tabular layouts a real shop owner uploads),
#     # ask Ollama to read the raw text and extract structured items. Only runs
#     # when needed, so clean tabular PDFs pay zero cost.
#     _MIN_ITEMS = 5
#     if len(table_items) + len(regex_items) < _MIN_ITEMS:
#         _stype = detect_metadata_regex(full_text).get('shop_type', 'general')
#         print(f"\n⚠️  Only {len(table_items)+len(regex_items)} items from regex — "
#               f"trying LLM extraction for this unstructured PDF...")
#         _llm_items = llm_extract_items(full_text, _stype, _MIN_ITEMS)
#         regex_items = regex_items + _llm_items

#     # Quick merge just for count display
#     all_merged: list = []
#     seen_tmp: set = set()
#     for item in table_items + regex_items:
#         key = re.sub(r'\s*\(.*?\)\s*$', '', item['name']).lower().strip()
#         if key not in seen_tmp:
#             seen_tmp.add(key)
#             all_merged.append(item)

#     print(f'✅ Auto-detected {len(all_merged)} items')
#     print(f'   From tables : {len(table_items)}')
#     print(f'   From text   : {len([i for i in all_merged if i.get("_source") == "regex"])}')

#     print('\n📋 All detected items:')
#     print('-' * 80)
#     print(f'{"#":3} {"Src":6} {"Category":22} {"Name":30} {"Price"}')
#     print('-' * 80)
#     for i, item in enumerate(all_merged, 1):
#         src  = item.get('_source', '?')[:5]
#         cat  = item.get('category', '?')[:21]
#         name = item['name'][:29]
#         if 'price' in item:
#             price_str = f"₹{item['price']:,}"
#         elif 'price_min' in item:
#             price_str = f"₹{item['price_min']:,}–{item['price_max']:,}"
#         else:
#             price_str = '?'
#         print(f'{i:3} [{src:5}] {cat:22} {name:30} {price_str}')

#     # Step 4 — Detect metadata
#     print(f'\n\n{"=" * 60}')
#     print('METADATA DETECTION')
#     print('=' * 60)
#     auto_meta = detect_metadata_regex(full_text)
#     for k, v in auto_meta.items():
#         if v and v not in ([],):
#             print(f'  ✅ {k:20s}: {v}')
#         else:
#             print(f'  ❌ {k:20s}: (not found — fill in MANUAL_OVERRIDES)')

#     print('\n⚠️  Review carefully! Regex detection is approximate.')

#     # Step 5 — Build and save shop_info
#     shop_info = build_shop_info(auto_meta, table_items, regex_items, extra_facts)
#     print_summary(shop_info)

#     out_path = args.out
#     with open(out_path, 'w', encoding='utf-8') as f:
#         json.dump(shop_info, f, ensure_ascii=False, indent=2)
#     print(f'\n✅ {out_path} saved ({Path(out_path).stat().st_size:,} bytes)')
#     print(f'   {len(shop_info["shop_items"])} items inside')

#     print('''
# 📌 Next steps:
# ─────────────────────────────────────────
# Option A — Feed JSON directly into generate_shop.py:
#   1. Open generate_shop.py
#   2. Replace SHOP_INFO = { ... } with the contents of shop_info.json
#   3. python generate_shop.py

# Option B — Use extractor.py (Ollama fills missing fields automatically):
#   python extractor.py --pdf your_menu.pdf
#   python extractor.py --url https://yourshop.com
#   python extractor.py --url https://yourshop.com --pdf menu.pdf
# ''')


# if __name__ == '__main__':
#     main()






# """
# pdf_extract_v2.py — Shop PDF Extractor (standalone script)
# ============================================================
# Extracted & fixed from pdf_extract_v2.ipynb.

# Usage:
#     pip install pdfplumber pypdf
#     python pdf_extract_v2.py your_shop.pdf
#     python pdf_extract_v2.py your_shop.pdf --out shop_info.json

# Output:
#     shop_info.json  → ready to feed into generate_shop.py or extractor.py

# Sections:
#     1. Install / imports
#     2. Raw text + table extraction (pdfplumber, pypdf fallback)
#     3. Table-based item detection
#     4. Regex-based item detection
#     5. Regex metadata detection (shop_name, phone, hours, payment, etc.)
#     6. Manual fix section (edit MANUAL_OVERRIDES below)
#     7. Save shop_info.json
# """

# import re
# import json
# import sys
# import argparse
# from pathlib import Path
# from collections import defaultdict

# # ── Optional imports (installed at runtime) ───────────────────────────────────
# try:
#     import pdfplumber
# except ImportError:
#     pdfplumber = None

# try:
#     from pypdf import PdfReader # pyright: ignore[reportMissingImports]
# except ImportError:
#     PdfReader = None


# # ══════════════════════════════════════════════════════════════════════════════
# #  MANUAL OVERRIDES
# #  Fill in anything the auto-detection misses, then re-run.
# # ══════════════════════════════════════════════════════════════════════════════

# MANUAL_OVERRIDES = {
#     # 'bot_name':       'MyBot',
#     # 'location':       'MG Road, Ernakulam, Kerala - 682001',
#     # 'city':           'Ernakulam',
#     # 'hours_sunday':   'Sunday 10AM–6PM',
#     # 'whatsapp':       '+91 98765 43210',
#     # 'phone':          '+91 98765 43210',
#     # 'services':       ['Root Canal', 'Braces', 'Implants'],
#     # 'offer_code':     'FIRSTVISIT',
#     # 'offer_desc':     'Free first consultation',
# }


# # ══════════════════════════════════════════════════════════════════════════════
# #  1. NUMBER & PRICE HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def parse_indian_number(s: str):
#     """'3,500' → 3500 | '2,50,000' → 250000"""
#     s = s.strip().replace(',', '')
#     try:
#         return int(s)
#     except ValueError:
#         return None


# def extract_prices(raw: str):
#     """
#     Given a raw price cell like 'Rs. 3,500' or 'Rs. 40,000 - Rs. 80,000'
#     return (price, price_min, price_max).
#     """
#     price = price_min = price_max = None
#     if not raw:
#         return price, price_min, price_max

#     cleaned = re.sub(r'[₹]|Rs\.?', '', raw, flags=re.IGNORECASE).strip()
#     tokens = re.findall(r'\d[\d,]*', cleaned)
#     nums = [v for t in tokens if (v := parse_indian_number(t)) and v > 0]

#     range_match = re.search(r'(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)', cleaned)
#     if range_match:
#         a = parse_indian_number(range_match.group(1))
#         b = parse_indian_number(range_match.group(2))
#         if a and b and a != b:
#             price_min, price_max = min(a, b), max(a, b)
#             return price, price_min, price_max

#     if len(nums) == 1:
#         price = nums[0]
#     elif len(nums) >= 2:
#         if nums[0] < nums[1]:
#             price_min, price_max = nums[0], nums[1]
#         else:
#             price = nums[0]

#     return price, price_min, price_max


# # ══════════════════════════════════════════════════════════════════════════════
# #  2. PDF EXTRACTION
# # ══════════════════════════════════════════════════════════════════════════════

# def extract_pdf(pdf_path: str) -> tuple[list, list, str]:
#     """
#     Returns:
#         all_pages  : list of {page, text}
#         all_tables : list of {page, rows}
#         full_text  : concatenated text string
#     """
#     all_pages: list = []
#     all_tables: list = []
#     full_text = ''

#     if pdfplumber is None and PdfReader is None:
#         print('❌ Neither pdfplumber nor pypdf is installed.')
#         print('   Run: pip install pdfplumber pypdf')
#         sys.exit(1)

#     print(f'\n📄 Extracting: {pdf_path}')
#     print('=' * 60)

#     try:
#         if pdfplumber is None:
#             raise ImportError('pdfplumber not available')

#         with pdfplumber.open(pdf_path) as pdf:
#             print(f'Total pages: {len(pdf.pages)}\n')
#             for pn, page in enumerate(pdf.pages, 1):
#                 text = page.extract_text(x_tolerance=3, y_tolerance=3) or ''
#                 text = text.strip()

#                 page_tables = []
#                 for tbl in page.extract_tables() or []:
#                     clean = []
#                     for row in tbl:
#                         cells = [str(c).strip() if c else '' for c in row]
#                         if any(c for c in cells):
#                             clean.append(cells)
#                     if clean:
#                         page_tables.append(clean)
#                         all_tables.append({'page': pn, 'rows': clean})
#                         tbl_text = '\n'.join(' | '.join(r) for r in clean)
#                         text += '\n\n[TABLE]\n' + tbl_text

#                 if text:
#                     all_pages.append({'page': pn, 'text': text})
#                     full_text += f'\n\n[PAGE {pn}]\n' + text

#                 print(f'── PAGE {pn} ────────────────────────────────────────')
#                 print(text[:600] if text else '(no text)')
#                 if page_tables:
#                     print(f'\n  [{len(page_tables)} table(s) on this page]')
#                 print()

#     except Exception as e:
#         print(f'pdfplumber error: {e} — trying pypdf fallback...')
#         if PdfReader is None:
#             print('❌ pypdf not installed either. Exiting.')
#             sys.exit(1)
#         reader = PdfReader(pdf_path)
#         for i, pg in enumerate(reader.pages, 1):
#             t = pg.extract_text() or ''
#             if t.strip():
#                 all_pages.append({'page': i, 'text': t.strip()})
#                 full_text += f'\n\n[PAGE {i}]\n{t.strip()}'
#                 print(f'── PAGE {i} ────────────────────────────────────────')
#                 print(t[:400])
#                 print()

#     print('=' * 60)
#     print(f'\n✅ Extracted {len(all_pages)} pages | {len(all_tables)} tables | {len(full_text):,} total chars')

#     if not full_text.strip():
#         print('\n⚠️  No text found — PDF may be scanned/image-based.')
#         print('   Fix: Upload to https://www.ilovepdf.com/ocr-pdf first, then retry.')

#     return all_pages, all_tables, full_text


# # ══════════════════════════════════════════════════════════════════════════════
# #  3. TABLE-BASED ITEM DETECTION
# # ══════════════════════════════════════════════════════════════════════════════

# # FIX: added hyphen and comma to the allowed character class --
# # real-world section headers commonly include them ("HAIR
# # SERVICES - COMPLETE MENU", "WAXING, THREADING & HAIR REMOVAL").
# # Without this, those headers silently fail to match, and every
# # item table that follows inherits whatever the LAST matching
# # header was -- mis-tagging dozens of real items with the wrong
# # category for the rest of the document. Max length also raised
# # slightly (50 -> 60) for longer subtitled headers.
# SECTION_HEADER_RE = re.compile(r'^\s*([A-Z][A-Z\s&\/\(\)\-,]{3,60})\s*$')

# # ── Junk item filter ──────────────────────────────────────────────────────────
# # Patterns that look like prices but are NOT sellable items
# _JUNK_ITEM_RE = re.compile(
#     r'^('
#     r'gst\s*(no\.?|number)?'           # GST No.
#     r'|~?\d+\s*g\)?'                   # ~250g)
#     r'|pieces?\)?'                     # pieces)
#     r'|traditional\s+recipe'           # description fragment
#     r'|pickle\s*\+'                    # meal description fragment
#     r'|free\s+delivery'                # delivery rule
#     r'|delivery\s+(charge|time|zone|areas?|below|above)'  # delivery metadata
#     r'|minimum\s+order'                # order rule
#     r'|order\s+via'                    # ordering info
#     r'|loyalty\s+card'                 # loyalty programme
#     r'|offer\s+code'                   # offer metadata
#     r'|happy\s+hours?'                 # offer metadata
#     r'|family\s+pack'                  # combo deal label
#     r'|opening\s+hours?'               # hours metadata
#     r'|last\s+order'                   # timing metadata
#     r'|home\s+delivery\s+hours'        # delivery hours
#     r'|breakfast\s+\('                 # weekend breakfast note
#     r'|payment\s+mode'                 # payment metadata
#     r'|catering\s+(?:available|service|for)'  # catering note
#     r')',
#     re.IGNORECASE,
# )

# _MIN_ITEM_NAME_LEN = 3   # skip single-char / two-char fragments
# _MAX_ITEM_NAME_LEN = 80  # skip overly long strings (likely paragraphs)


# def is_valid_item(name: str) -> bool:
#     """
#     Returns True if the name looks like a real sellable item.
#     Filters junk rows that pdf extraction picks up as items.
#     """
#     name = name.strip()
#     if len(name) < _MIN_ITEM_NAME_LEN or len(name) > _MAX_ITEM_NAME_LEN:
#         return False
#     # starts with punctuation / number / bracket — fragment
#     if name[0] in ('~', '(', ')', '+', '-', '.', ',', '#'):
#         return False
#     # purely numeric
#     if re.match(r'^\d[\d\s,\.]*$', name):
#         return False
#     # matches known junk patterns
#     if _JUNK_ITEM_RE.match(name):
#         return False
#     return True


# # Rows that are metadata, not sellable items — skip them
# META_SKIP_RE = re.compile(
#     r'^(Registration\s*No\.?|Address|Phone(?:\s*\(.*?\))?|Emergency\s*Phone|WhatsApp(?:\s*Order)?|'
#     r'Monday|Sunday|Emergency|EMI|Kids\s*Special|Senior\s*Citizen|'
#     r'Payment\s*Modes?|Health\s*Insurance|Free\s*Consultation|'
#     r'FSSAI\s*License|GSTIN?(?:\s*No\.?)?|Zomato|Swiggy|AC\s*Available|Private\s*Dining|'
#     r'Owner(?:\s*/\s*Director)?|Head\s*Chef|Cuisine|Seating\s*(?:Capacity)?|Landmark|'
#     r'Last\s*Order|Home\s*Delivery\s*Hours|Breakfast(?:\s*\(.*?\))?|'
#     r'Free\s*Delivery\s*(?:Above|Below)?|Delivery\s*(?:Charge|Time|Zone|Areas?)|'
#     r'Minimum\s*Order|Order\s*via|Catering|Bulk\s*Order|'
#     r'Offer\s*Code.*|Happy\s*Hours?\s*Offer|Family\s*Pack|Loyalty\s*Card|'
#     r'Weekend\s*Breakfast|Restaurant\s*Name|Equipment|Sterilisation|Parking|'
#     r'Salon\s*Name|Clinic\s*Name|Shop\s*Name|Alternate\s*Phone|'
#     r'Instagram|Facebook|Accessibility|Lift\s*Available)$',
#     re.IGNORECASE
# )


# def detect_items_from_tables(tables: list) -> tuple[list, list]:
#     items = []
#     extra_facts: list = []
#     seen: set = set()
#     current_category = 'General'

#     for tbl in tables:
#         rows = tbl['rows']
#         if not rows:
#             continue

#         # Single-row table: a pure "Label | Value" fact pair
#         # (e.g. "Loyalty Card | Visit 10 times..."), not a
#         # header+data table. pdfplumber often extracts these as
#         # their own 1-row table -- capture directly as an
#         # extra_fact since there is no header row to consume.
#         if len(rows) == 1 and len(rows[0]) >= 2:
#             label = rows[0][0].strip()
#             detail = next((c.strip() for c in rows[0][1:] if c.strip()), "")
#             if label and detail and len(label) <= 60:
#                 extra_facts.append({"label": label, "detail": detail})
#             continue

#         # Detect single-cell all-caps section header as first row
#         non_empty = [c for c in rows[0] if c.strip()]
#         if len(non_empty) == 1 and SECTION_HEADER_RE.match(non_empty[0]):
#             current_category = non_empty[0].strip()
#             rows = rows[1:]
#             if not rows:
#                 continue

#         header = rows[0]
#         name_col, price_col, desc_col = 0, -1, -1

#         for ci, cell in enumerate(header):
#             cl = cell.lower()
#             if any(k in cl for k in ('name', 'item', 'dish', 'product', 'service', 'treatment', 'type', 'particulars')):
#                 name_col = ci
#             elif any(k in cl for k in ('price', 'rate', 'amount', 'cost', 'fee', 'charge', 'tariff', '₹', 'rs.')):
#                 price_col = ci
#             elif any(k in cl for k in ('description', 'detail', 'desc', 'notes', 'includes', 'inclusion', 'inclusions', 'duration', 'time', 'hrs', 'min')):
#                 desc_col = ci

#         # Auto-detect price column by content if not found in header.
#         # Prefer Rs./₹ columns; skip duration columns (e.g. "1.5 hrs").
#         DURATION_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:hrs?|min(?:utes?)?|hour)', re.IGNORECASE)
#         RS_RE       = re.compile(r'(?:Rs\.?|₹)\s*\d', re.IGNORECASE)

#         if price_col == -1:
#             # First pass: explicit Rs./₹ symbol in values
#             for ci in range(len(header) - 1, 0, -1):
#                 col_vals = [r[ci] for r in rows[1:] if ci < len(r)]
#                 rs_hits  = sum(1 for v in col_vals if RS_RE.search(v))
#                 if col_vals and rs_hits >= max(1, len(col_vals) * 0.3):
#                     price_col = ci
#                     break

#         if price_col == -1:
#             # Second pass: numeric-heavy column, skip duration columns
#             for ci in range(len(header) - 1, 0, -1):
#                 col_vals = [r[ci] for r in rows[1:] if ci < len(r)]
#                 if not col_vals:
#                     continue
#                 if sum(1 for v in col_vals if DURATION_RE.search(v)) > len(col_vals) * 0.4:
#                     continue
#                 if sum(1 for v in col_vals if re.search(r'\d{2,}', v)) > len(col_vals) * 0.4:
#                     price_col = ci
#                     break

#         data_rows = rows[1:] if any(re.search(r'[a-zA-Z]{3,}', c) for c in header) else rows

#         for row in data_rows:
#             if not row or name_col >= len(row):
#                 continue
#             name = row[name_col].strip()
#             if not name or len(name) < 2:
#                 continue

#             # Section header embedded inside table
#             if SECTION_HEADER_RE.match(name) and not any(
#                 re.search(r'\d{2,}', row[ci]) for ci in range(len(row)) if ci != name_col
#             ):
#                 current_category = name.strip()
#                 continue

#             if META_SKIP_RE.match(name):
#                 # Correctly excluded from the item catalogue (not a
#                 # sellable dish/service) -- but capture it as an
#                 # EXTRA FACT instead of silently dropping it, so
#                 # loyalty programmes, offer codes, happy-hour deals,
#                 # combo packs etc. are still available to ground
#                 # the bot's answers instead of vanishing entirely.
#                 fact_value = None
#                 for ci, cell in enumerate(row):
#                     if ci != name_col and cell.strip():
#                         fact_value = cell.strip()
#                         break
#                 if fact_value:
#                     extra_facts.append({"label": name, "detail": fact_value})
#                 continue

#             # ── Junk item guard (FIX 1) ──────────────────────────────────
#             if not is_valid_item(name):
#                 continue

#             price = price_min = price_max = None

#             if price_col != -1 and price_col < len(row):
#                 price, price_min, price_max = extract_prices(row[price_col])

#             # Scan all non-name cells if still nothing
#             if not price and not price_min:
#                 for ci, cell in enumerate(row):
#                     if ci == name_col:
#                         continue
#                     p, pn, px = extract_prices(cell)
#                     if pn and px:
#                         price_min, price_max = pn, px
#                         break
#                     if p and p >= 5:
#                         price = p

#             if not price and not price_min:
#                 continue

#             # Skip implausibly small values (phone/address noise)
#             if price and price < 10:
#                 continue
#             if price_min and price_min < 10 and (not price_max or price_max < 100):
#                 continue

#             key = name.lower().strip()
#             if key in seen:
#                 continue
#             seen.add(key)

#             item = {'name': name, 'category': current_category, '_source': 'table'}
#             if desc_col != -1 and desc_col < len(row):
#                 desc = row[desc_col].strip()
#                 if desc and desc.lower() not in ('description', 'details', 'desc', ''):
#                     item['description'] = desc

#             if price_min and price_max and price_min != price_max:
#                 item['price_min'] = price_min
#                 item['price_max'] = price_max
#             elif price:
#                 item['price'] = price
#             elif price_min:
#                 item['price'] = price_min

#             items.append(item)

#     return items, extra_facts


# # ══════════════════════════════════════════════════════════════════════════════
# #  4. REGEX-BASED ITEM DETECTION (from plain text lines)
# # ══════════════════════════════════════════════════════════════════════════════

# PRICE_PATTERNS = [
#     r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s+[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*(?:\/\-|\/-)?$',
#     r'^(.+?)\s*[|\t]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*$',
#     r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s*[₹]\s*(\d[\d,]{1,9})',
# ]

# RANGE_PATTERNS = [
#     r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s+[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*[-–]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})',
#     r'^(.+?)\s*[|\t]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*[-–]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})',
# ]

# HEADER_RE = re.compile(
#     r'^\s*([A-Z][A-Z\s&\/]{3,35}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s*[:\-]?\s*$'
# )


# def detect_items_regex(text: str) -> list:
#     items = []
#     current_category = 'General'
#     seen_names: set = set()

#     for line in text.splitlines():
#         line = line.strip()
#         if not line or len(line) < 4:
#             continue

#         hm = HEADER_RE.match(line)
#         if hm and len(line) < 50 and not re.search(r'\d{3,}', line):
#             current_category = line.strip(':').strip()
#             continue

#         matched = False
#         for pat in RANGE_PATTERNS:
#             m = re.match(pat, line, re.IGNORECASE)
#             if m:
#                 name = m.group(1).strip().strip('|-').strip()
#                 pmin = parse_indian_number(m.group(2))
#                 pmax = parse_indian_number(m.group(3))
#                 if pmin and pmax and 1 <= pmin <= 9_999_999 and pmin < pmax:
#                     key = name.lower()
#                     if key not in seen_names and len(name) >= 3 and is_valid_item(name):
#                         seen_names.add(key)
#                         items.append({
#                             'name': name,
#                             'price_min': pmin,
#                             'price_max': pmax,
#                             'category': current_category,
#                             '_source': 'regex_range',
#                         })
#                         matched = True
#                         break

#         if matched:
#             continue

#         for pat in PRICE_PATTERNS:
#             m = re.match(pat, line, re.IGNORECASE)
#             if m:
#                 name = re.sub(r'\s*\|.*$', '', m.group(1).strip()).strip()
#                 price = parse_indian_number(m.group(2))
#                 if price and 5 <= price <= 9_999_999:
#                     key = re.sub(r'\s*\(.*?\)\s*$', '', name).lower().strip()
#                     if key not in seen_names and len(name) >= 3 and is_valid_item(name):
#                         seen_names.add(key)
#                         items.append({
#                             'name': name,
#                             'price': price,
#                             'category': current_category,
#                             '_source': 'regex',
#                         })
#                         break

#     return items


# # ══════════════════════════════════════════════════════════════════════════════
# #  5. METADATA DETECTION
# # ══════════════════════════════════════════════════════════════════════════════

# def detect_metadata_regex(text: str) -> dict:
#     meta: dict = {
#         'shop_name': None, 'shop_type': None, 'tagline': None,
#         'location': None, 'city': None, 'state': None,
#         'phone': None, 'whatsapp': None, 'email': None, 'website': None,
#         'hours_weekdays': None, 'hours_sunday': None,
#         'payment': [], 'services': [],
#         'delivery_free': None, 'delivery_charge': None,
#         'delivery_days': None, 'delivery_areas': None,
#         'offer_code': None, 'offer_desc': None,
#     }

#     # Phone numbers
#     phone_raw = re.findall(r'(?:\+91|\b0)?[\s\-]?[6-9][\d\s\-]{9,14}', text)

#     def clean_phone(p: str) -> str:
#         digits = re.sub(r'[^\d]', '', p)
#         if digits.startswith('91') and len(digits) == 12:
#             return '+91 ' + digits[2:7] + ' ' + digits[7:]
#         if len(digits) == 10:
#             return '+91 ' + digits[:5] + ' ' + digits[5:]
#         return p.strip()

#     cleaned_phones = []
#     seen_ph: set = set()
#     for p in phone_raw:
#         digits = re.sub(r'[^\d]', '', p)
#         if len(digits) >= 10 and digits[-10] in '6789':
#             key = digits[-10:]
#             if key not in seen_ph:
#                 seen_ph.add(key)
#                 cleaned_phones.append(clean_phone(p))
#     if cleaned_phones:
#         meta['phone'] = cleaned_phones[0]
#         meta['whatsapp'] = cleaned_phones[0]

#     # Email
#     emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', text)
#     if emails:
#         meta['email'] = emails[0]

#     # Website
#     websites = re.findall(r'(?:https?://|www\.)[\w\.-]+\.[a-z]{2,}', text)
#     if websites:
#         meta['website'] = websites[0]

#     # Hours
#     hours = re.findall(
#         r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
#         r'[\s\-–]+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?'
#         r'[\s:]+\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)',
#         text, re.IGNORECASE
#     )
#     if hours:
#         for h in hours:
#             line_match = re.search(re.escape(h) + r'.*?(\d{1,2}(?::\d{2})?\s*(?:AM|PM))', text, re.IGNORECASE)
#             if line_match and line_match.group(1).lower() not in h.lower():
#                 meta['hours_weekdays'] = h + ' - ' + line_match.group(1)
#                 break
#         else:
#             meta['hours_weekdays'] = hours[0]

#     time_ranges = re.findall(
#         r'\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)',
#         text
#     )
#     if time_ranges and not meta['hours_weekdays']:
#         meta['hours_weekdays'] = time_ranges[0]

#     sun_match = re.search(r'Sunday[\s:]+(.{5,50}?(?:AM|PM).*?)(?:\n|$)', text, re.IGNORECASE)
#     if sun_match:
#         meta['hours_sunday'] = 'Sunday: ' + sun_match.group(1).strip()

#     # Location (pincode-based)
#     joined_text = re.sub(r'\n', ' ', text)
#     addr_match = re.search(r'([A-Za-z0-9][A-Za-z0-9 ,\.\-/#]{10,200}?\b(\d{6})\b)', joined_text)
#     if addr_match:
#         meta['location'] = re.sub(r'\s+', ' ', addr_match.group(1)).strip()

#     # City
#     city_match = re.search(
#         r'\b(Thrissur|Kochi|Trivandrum|Thiruvananthapuram|Kozhikode|Calicut|'
#         r'Kollam|Palakkad|Alappuzha|Kannur|Malappuram|Ernakulam|'
#         r'Mumbai|Delhi|Bangalore|Chennai|Hyderabad|Pune|Kolkata|'
#         r'Ahmedabad|Surat|Jaipur|Lucknow|Nagpur|Indore|Bhopal|'
#         r'Patna|Vadodara|Coimbatore|Madurai|Agra|Nashik|Faridabad|'
#         r'Meerut|Rajkot|Varanasi|Srinagar|Aurangabad|Dhanbad|Amritsar|'
#         r'Navi Mumbai|Allahabad|Prayagraj|Ranchi|Howrah|Jabalpur|Gwalior|'
#         r'Vijayawada|Jodhpur|Raipur|Kota|Guwahati|Chandigarh|Solapur|'
#         r'Hubli|Tiruchirappalli|Bareilly|Mysore|Tiruppur|Gurgaon|Gurugram|'
#         r'Mangalore|Belgaum|Gulbarga|Udupi|Manipal)\b',
#         text
#     )
#     if city_match:
#         meta['city'] = city_match.group(1)

#     # State
#     state_match = re.search(
#         r'\b(Kerala|Karnataka|Tamil Nadu|Tamilnadu|Maharashtra|Gujarat|'
#         r'Rajasthan|Uttar Pradesh|Madhya Pradesh|West Bengal|Bihar|'
#         r'Andhra Pradesh|Telangana|Odisha|Punjab|Haryana|Jharkhand|'
#         r'Uttarakhand|Assam|Himachal Pradesh|Goa|Chhattisgarh|Delhi)\b',
#         text
#     )
#     if state_match:
#         meta['state'] = state_match.group(1)

#     # Payment methods
#     pay_keywords = {
#         'UPI': r'\bUPI\b', 'GPay': r'\bGPay\b|Google Pay',
#         'PhonePe': r'\bPhonePe\b', 'Cash': r'\bCash\b',
#         'Cards': r'\bCard\b|Credit Card|Debit Card',
#         'Paytm': r'\bPaytm\b', 'NetBanking': r'Net Banking|NEFT|RTGS',
#         'Cheque': r'\bCheque\b|\bCheck\b',
#     }
#     for method, pat in pay_keywords.items():
#         if re.search(pat, text, re.IGNORECASE):
#             meta['payment'].append(method)

#     # Shop type detection
#     TYPE_KW = {
#         'restaurant':    ['menu', 'biriyani', 'curry', 'dosa', 'restaurant', 'cafe', 'food', 'dining'],
#         'clothing':      ['shirt', 'saree', 'kurta', 'dress', 'garment', 'fashion', 'wear', 'textile'],
#         'dental_clinic': ['dental', 'dentist', 'tooth', 'teeth', 'root canal', 'braces', 'clinic'],
#         'beauty_parlour': ['salon', 'parlour', 'makeup', 'facial', 'bridal', 'spa', 'beauty'],
#         'jewellery':     ['gold', 'silver', 'diamond', 'jewel', 'necklace', 'ring', 'jewellery'],
#         'gym':           ['gym', 'fitness', 'workout', 'membership', 'trainer', 'yoga'],
#         'hospital':      ['hospital', 'doctor', 'ward', 'surgery', 'opd', 'patient', 'medical'],
#         'pharmacy':      ['pharmacy', 'medicine', 'drug', 'tablet', 'prescription', 'chemist'],
#         'optical':       ['optical', 'spectacle', 'glasses', 'lens', 'eye test', 'frame'],
#         'electronics':   ['mobile', 'laptop', 'phone', 'television', 'electronics', 'gadget'],
#         'supermarket':   ['supermarket', 'grocery', 'vegetables', 'fruits', 'mart', 'kirana'],
#         'bakery':        ['bakery', 'cake', 'bread', 'pastry', 'bake', 'cookie'],
#         'hotel':         ['hotel', 'room', 'check-in', 'accommodation', 'resort', 'suite', 'tariff'],
#         'travel_agency': ['tour', 'travel', 'package', 'visa', 'itinerary', 'holiday', 'tourism'],
#         'real_estate':   ['property', 'flat', 'apartment', 'plot', 'villa', 'rent', 'sqft', 'bhk'],
#         'law_firm':      ['lawyer', 'advocate', 'legal', 'court', 'law firm', 'attorney'],
#         'ca_firm':       ['chartered', 'accountant', 'gst', 'income tax', 'audit', 'tds', 'itr'],
#         'school':        ['school', 'college', 'admission', 'student', 'class', 'education'],
#     }
#     tl = text.lower()
#     scores = {t: sum(1 for kw in kws if kw in tl) for t, kws in TYPE_KW.items()}
#     best = max(scores, key=scores.get)
#     meta['shop_type'] = best if scores[best] > 0 else 'general'

#     # Shop name from first few clean lines
#     lines = [l.strip() for l in text.splitlines() if l.strip()]
#     for line in lines[:8]:
#         if re.search(r'\d{7,}|@|www\.|http', line):
#             continue
#         if 5 < len(line) < 60 and not line.startswith('['):
#             meta['shop_name'] = line
#             break

#     return meta


# # ══════════════════════════════════════════════════════════════════════════════
# #  6. MERGE & BUILD shop_info
# # ══════════════════════════════════════════════════════════════════════════════

# def build_shop_info(auto_meta: dict, table_items: list, regex_items: list,
#                      extra_facts: list | None = None) -> dict:
#     # Merge items (table first — more reliable), deduplicate
#     all_items: list = []
#     seen_names: set = set()
#     for item in table_items + regex_items:
#         clean_name = re.sub(r'\s*\|.*$', '', item['name']).strip()
#         key = re.sub(r'\s*\(.*?\)\s*$', '', clean_name).lower().strip()
#         if key not in seen_names:
#             seen_names.add(key)
#             all_items.append(item)

#     # Build SHOP_INFO with auto-detected values, override with MANUAL_OVERRIDES
#     shop_info = {
#         # Identity
#         'bot_name':       auto_meta.get('shop_name', '').split()[0][:10] if auto_meta.get('shop_name') else None,
#         'shop_name':      auto_meta.get('shop_name'),
#         'shop_type':      auto_meta.get('shop_type', 'general'),
#         'tagline':        auto_meta.get('tagline'),
#         'description':    None,
#         # Location
#         'location':       auto_meta.get('location'),
#         'city':           auto_meta.get('city'),
#         'state':          auto_meta.get('state', 'Kerala'),
#         # Hours
#         'hours_weekdays': auto_meta.get('hours_weekdays'),
#         'hours_sunday':   auto_meta.get('hours_sunday'),
#         'hours_holiday':  'Check WhatsApp for holiday hours',
#         # Contact
#         'whatsapp':       auto_meta.get('whatsapp'),
#         'phone':          auto_meta.get('phone'),
#         'email':          auto_meta.get('email'),
#         'website':        auto_meta.get('website'),
#         # Payment & Services
#         'payment':        auto_meta.get('payment') or ['UPI', 'Cash', 'Cards'],
#         'services':       [],
#         # Delivery
#         'delivery_areas': auto_meta.get('delivery_areas'),
#         'delivery_free':  auto_meta.get('delivery_free'),
#         'delivery_charge': auto_meta.get('delivery_charge'),
#         'delivery_days':  auto_meta.get('delivery_days'),
#         # Returns
#         'return_days':    0,
#         'return_condition': None,
#         'refund_days':    None,
#         # Offers
#         'offer_code':     auto_meta.get('offer_code'),
#         'offer_desc':     auto_meta.get('offer_desc'),
#         # Escalation
#         'escalate_whatsapp': auto_meta.get('whatsapp'),
#         'escalate_email':    auto_meta.get('email'),
#         # Items (strip internal _source/_line keys before use in generate_shop.py)
#         'shop_items': [
#             {k: v for k, v in item.items() if not k.startswith('_')}
#             for item in all_items
#             if is_valid_item(item.get('name', ''))   # FIX 1: final junk guard
#         ],
#         # Promotional/programme facts correctly excluded from
#         # shop_items (not sellable dishes) but still real, useful
#         # facts -- loyalty cards, offer codes, happy-hour deals,
#         # combo packs. Without this they vanish entirely instead
#         # of being available to ground the bot's answers.
#         'extra_facts': extra_facts or [],
#     }

#     # Apply manual overrides
#     for k, v in MANUAL_OVERRIDES.items():
#         if v is not None:
#             shop_info[k] = v

#     return shop_info


# # ══════════════════════════════════════════════════════════════════════════════
# #  7. PRINT SUMMARY
# # ══════════════════════════════════════════════════════════════════════════════

# OPTIONAL_FIELDS = {
#     'tagline', 'description', 'offer_code', 'offer_desc',
#     'refund_days', 'return_condition', 'delivery_areas',
#     'delivery_free', 'delivery_days', 'delivery_charge',
#     'hours_holiday', 'escalate_whatsapp', 'escalate_email', 'website',
# }

# KEY_FIELDS = [
#     'location', 'city', 'hours_sunday', 'whatsapp', 'phone', 'services',
# ]


# def print_summary(shop_info: dict):
#     print('\n📦 Final shop_info summary:')
#     print('=' * 55)
#     for k, v in shop_info.items():
#         if k == 'shop_items':
#             print(f'  shop_items          : {len(v)} items')
#         elif v and v not in ([], {}, ''):
#             print(f'  ✅ {k:20s}: {str(v)[:50]}')
#         else:
#             print(f'  ⚠️  {k:20s}: MISSING')

#     missing = [
#         k for k, v in shop_info.items()
#         if k not in ('shop_items', 'return_days') and not v and k not in OPTIONAL_FIELDS
#     ]
#     if missing:
#         print(f'\n⚠️  Fields to fill manually: {missing}')
#         print('   Edit MANUAL_OVERRIDES at top of script and re-run')
#     else:
#         print('\n✅ All key fields filled!')


# # ══════════════════════════════════════════════════════════════════════════════
# #  MAIN
# # ══════════════════════════════════════════════════════════════════════════════

# def main():
#     parser = argparse.ArgumentParser(
#         description='Extract shop info from a PDF and output shop_info.json'
#     )
#     parser.add_argument('pdf', help='Path to shop PDF file')
#     parser.add_argument('--out', default='shop_info.json', help='Output JSON file (default: shop_info.json)')
#     args = parser.parse_args()

#     if not Path(args.pdf).exists():
#         print(f'❌ File not found: {args.pdf}')
#         sys.exit(1)

#     # Step 1 — Extract PDF
#     all_pages, all_tables, full_text = extract_pdf(args.pdf)

#     if not full_text.strip():
#         print('No text to process. Exiting.')
#         sys.exit(1)

#     # Step 2 — Print table summary
#     print(f'\n\n{"=" * 60}')
#     print(f'TABLE SUMMARY  ({len(all_tables)} tables found)')
#     print('=' * 60)
#     for ti, tbl in enumerate(all_tables, 1):
#         rows = tbl['rows']
#         print(f'\n┌── Table {ti}  (page {tbl["page"]}, {len(rows)} rows) ──────────────────')
#         for row in rows:
#             truncated = [c[:32] for c in row if c.strip()]
#             if truncated:
#                 print('│ ' + ' │ '.join(truncated))

#     # Step 3 — Detect items
#     print(f'\n\n{"=" * 60}')
#     print('ITEM DETECTION')
#     print('=' * 60)
#     table_items, extra_facts = detect_items_from_tables(all_tables)
#     regex_items = detect_items_regex(full_text)

#     # Quick merge just for count display
#     all_merged: list = []
#     seen_tmp: set = set()
#     for item in table_items + regex_items:
#         key = re.sub(r'\s*\(.*?\)\s*$', '', item['name']).lower().strip()
#         if key not in seen_tmp:
#             seen_tmp.add(key)
#             all_merged.append(item)

#     print(f'✅ Auto-detected {len(all_merged)} items')
#     print(f'   From tables : {len(table_items)}')
#     print(f'   From text   : {len([i for i in all_merged if i.get("_source") == "regex"])}')

#     print('\n📋 All detected items:')
#     print('-' * 80)
#     print(f'{"#":3} {"Src":6} {"Category":22} {"Name":30} {"Price"}')
#     print('-' * 80)
#     for i, item in enumerate(all_merged, 1):
#         src  = item.get('_source', '?')[:5]
#         cat  = item.get('category', '?')[:21]
#         name = item['name'][:29]
#         if 'price' in item:
#             price_str = f"₹{item['price']:,}"
#         elif 'price_min' in item:
#             price_str = f"₹{item['price_min']:,}–{item['price_max']:,}"
#         else:
#             price_str = '?'
#         print(f'{i:3} [{src:5}] {cat:22} {name:30} {price_str}')

#     # Step 4 — Detect metadata
#     print(f'\n\n{"=" * 60}')
#     print('METADATA DETECTION')
#     print('=' * 60)
#     auto_meta = detect_metadata_regex(full_text)
#     for k, v in auto_meta.items():
#         if v and v not in ([],):
#             print(f'  ✅ {k:20s}: {v}')
#         else:
#             print(f'  ❌ {k:20s}: (not found — fill in MANUAL_OVERRIDES)')

#     print('\n⚠️  Review carefully! Regex detection is approximate.')

#     # Step 5 — Build and save shop_info
#     shop_info = build_shop_info(auto_meta, table_items, regex_items, extra_facts)
#     print_summary(shop_info)

#     out_path = args.out
#     with open(out_path, 'w', encoding='utf-8') as f:
#         json.dump(shop_info, f, ensure_ascii=False, indent=2)
#     print(f'\n✅ {out_path} saved ({Path(out_path).stat().st_size:,} bytes)')
#     print(f'   {len(shop_info["shop_items"])} items inside')

#     print('''
# 📌 Next steps:
# ─────────────────────────────────────────
# Option A — Feed JSON directly into generate_shop.py:
#   1. Open generate_shop.py
#   2. Replace SHOP_INFO = { ... } with the contents of shop_info.json
#   3. python generate_shop.py

# Option B — Use extractor.py (Ollama fills missing fields automatically):
#   python extractor.py --pdf your_menu.pdf
#   python extractor.py --url https://yourshop.com
#   python extractor.py --url https://yourshop.com --pdf menu.pdf
# ''')


# if __name__ == '__main__':
#     main()









"""
pdf_extract_v2.py — Shop PDF Extractor (standalone script)
============================================================
Extracted & fixed from pdf_extract_v2.ipynb.

Usage:
    pip install pdfplumber pypdf
    python pdf_extract_v2.py your_shop.pdf
    python pdf_extract_v2.py your_shop.pdf --out shop_info.json

Output:
    shop_info.json  → ready to feed into generate_shop.py or extractor.py

Sections:
    1. Install / imports
    2. Raw text + table extraction (pdfplumber, pypdf fallback)
    3. Table-based item detection
    4. Regex-based item detection
    5. Regex metadata detection (shop_name, phone, hours, payment, etc.)
    6. Manual fix section (edit MANUAL_OVERRIDES below)
    7. Save shop_info.json
"""

import re
import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict

# ── Optional imports (installed at runtime) ───────────────────────────────────
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from pypdf import PdfReader # pyright: ignore[reportMissingImports]
except ImportError:
    PdfReader = None


# ══════════════════════════════════════════════════════════════════════════════
#  MANUAL OVERRIDES
#  Fill in anything the auto-detection misses, then re-run.
# ══════════════════════════════════════════════════════════════════════════════

MANUAL_OVERRIDES = {
    # 'bot_name':       'MyBot',
    # 'location':       'MG Road, Ernakulam, Kerala - 682001',
    # 'city':           'Ernakulam',
    # 'hours_sunday':   'Sunday 10AM–6PM',
    # 'whatsapp':       '+91 98765 43210',
    # 'phone':          '+91 98765 43210',
    # 'services':       ['Root Canal', 'Braces', 'Implants'],
    # 'offer_code':     'FIRSTVISIT',
    # 'offer_desc':     'Free first consultation',
}


# ══════════════════════════════════════════════════════════════════════════════
#  1. NUMBER & PRICE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def parse_indian_number(s: str):
    """'3,500' → 3500 | '2,50,000' → 250000"""
    s = s.strip().replace(',', '')
    try:
        return int(s)
    except ValueError:
        return None


def extract_prices(raw: str):
    """
    Given a raw price cell like 'Rs. 3,500' or 'Rs. 40,000 - Rs. 80,000'
    return (price, price_min, price_max).
    """
    price = price_min = price_max = None
    if not raw:
        return price, price_min, price_max

    # Guard: refuse cells that look like identifier codes rather than
    # prices -- license numbers, GST numbers, registration codes, etc. all
    # contain letters mixed with dash-separated digit groups (e.g.
    # "KL-KZD-PH-2005-0482"), which the digit-range regex below would
    # otherwise happily misread as a price range like "₹482-₹2005". A
    # genuine price cell is either pure numeric or explicitly marked with a
    # currency symbol -- never letters with no currency marker at all.
    has_currency = bool(re.search(r'[₹]|Rs\.?|Rupee', raw, re.IGNORECASE))
    has_letters  = bool(re.search(r'[A-Za-z]', raw))
    if has_letters and not has_currency:
        return price, price_min, price_max

    cleaned = re.sub(r'[₹]|Rs\.?', '', raw, flags=re.IGNORECASE).strip()
    tokens = re.findall(r'\d[\d,]*', cleaned)
    nums = [v for t in tokens if (v := parse_indian_number(t)) and v > 0]

    range_match = re.search(r'(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)', cleaned)
    if range_match:
        a = parse_indian_number(range_match.group(1))
        b = parse_indian_number(range_match.group(2))
        if a and b and a != b:
            price_min, price_max = min(a, b), max(a, b)
            return price, price_min, price_max

    if len(nums) == 1:
        price = nums[0]
    elif len(nums) >= 2:
        if nums[0] < nums[1]:
            price_min, price_max = nums[0], nums[1]
        else:
            price = nums[0]

    return price, price_min, price_max


# ══════════════════════════════════════════════════════════════════════════════
#  2. PDF EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_pdf(pdf_path: str) -> tuple[list, list, str]:
    """
    Returns:
        all_pages  : list of {page, text}
        all_tables : list of {page, rows}
        full_text  : concatenated text string
    """
    all_pages: list = []
    all_tables: list = []
    full_text = ''

    if pdfplumber is None and PdfReader is None:
        print('❌ Neither pdfplumber nor pypdf is installed.')
        print('   Run: pip install pdfplumber pypdf')
        sys.exit(1)

    print(f'\n📄 Extracting: {pdf_path}')
    print('=' * 60)

    try:
        if pdfplumber is None:
            raise ImportError('pdfplumber not available')

        with pdfplumber.open(pdf_path) as pdf:
            print(f'Total pages: {len(pdf.pages)}\n')
            for pn, page in enumerate(pdf.pages, 1):
                text = page.extract_text(x_tolerance=3, y_tolerance=3) or ''
                text = text.strip()

                page_tables = []
                for tbl in page.extract_tables() or []:
                    clean = []
                    for row in tbl:
                        cells = [str(c).strip() if c else '' for c in row]
                        if any(c for c in cells):
                            clean.append(cells)
                    if clean:
                        page_tables.append(clean)
                        all_tables.append({'page': pn, 'rows': clean})
                        tbl_text = '\n'.join(' | '.join(r) for r in clean)
                        text += '\n\n[TABLE]\n' + tbl_text

                if text:
                    all_pages.append({'page': pn, 'text': text})
                    full_text += f'\n\n[PAGE {pn}]\n' + text

                print(f'── PAGE {pn} ────────────────────────────────────────')
                print(text[:600] if text else '(no text)')
                if page_tables:
                    print(f'\n  [{len(page_tables)} table(s) on this page]')
                print()

    except Exception as e:
        print(f'pdfplumber error: {e} — trying pypdf fallback...')
        if PdfReader is None:
            print('❌ pypdf not installed either. Exiting.')
            sys.exit(1)
        reader = PdfReader(pdf_path)
        for i, pg in enumerate(reader.pages, 1):
            t = pg.extract_text() or ''
            if t.strip():
                all_pages.append({'page': i, 'text': t.strip()})
                full_text += f'\n\n[PAGE {i}]\n{t.strip()}'
                print(f'── PAGE {i} ────────────────────────────────────────')
                print(t[:400])
                print()

    print('=' * 60)
    print(f'\n✅ Extracted {len(all_pages)} pages | {len(all_tables)} tables | {len(full_text):,} total chars')

    if not full_text.strip():
        print('\n⚠️  No text found — PDF may be scanned/image-based.')
        print('   Fix: Upload to https://www.ilovepdf.com/ocr-pdf first, then retry.')

    return all_pages, all_tables, full_text


# ══════════════════════════════════════════════════════════════════════════════
#  3. TABLE-BASED ITEM DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# FIX: added hyphen and comma to the allowed character class --
# real-world section headers commonly include them ("HAIR
# SERVICES - COMPLETE MENU", "WAXING, THREADING & HAIR REMOVAL").
# Without this, those headers silently fail to match, and every
# item table that follows inherits whatever the LAST matching
# header was -- mis-tagging dozens of real items with the wrong
# category for the rest of the document. Max length also raised
# slightly (50 -> 60) for longer subtitled headers.
SECTION_HEADER_RE = re.compile(r'^\s*([A-Z][A-Z\s&\/\(\)\-,]{3,60})\s*$')

# FIX (generic, applies to every shop type/PDF -- not a per-shop patch):
# SECTION_HEADER_RE matches ANY all-caps line, which also matches
# document-meta titles that are not real product/service categories --
# e.g. a pharmacy PDF section literally titled "COMPLETE PRODUCT &
# SERVICES CATALOGUE" or "GENERIC MEDICINE SAVINGS EXAMPLES" was being
# accepted as current_category, then propagated into every item under
# it, then won the majority vote in detect_specialisation() and ended
# up as an allowed_categories entry -- surfacing verbatim in customer
# replies ("We offer COMPLETE PRODUCT & SERVICES CATALOGUE..."). These
# document-structure words are shop-type-agnostic: any shop's PDF that
# has a section titled "...CATALOGUE", "...PRICE LIST", "...OVERVIEW"
# etc. would hit the same bug. Reject candidate headings containing any
# of these words instead of updating current_category with them --
# current_category is simply left unchanged (falls back to whatever
# real category preceded it, or 'General' if none has been seen yet).
_DOC_META_HEADING_WORDS = {
    "CATALOGUE", "CATALOG", "EXAMPLES", "EXAMPLE", "SAMPLE", "SAMPLES",
    "SUMMARY", "OVERVIEW", "INFORMATION", "GUIDE", "TERMS", "POLICY",
    "POLICIES", "DISCLAIMER", "APPENDIX", "INTRODUCTION", "CONTENTS",
}


def _is_real_category_heading(text: str) -> bool:
    """True if `text` looks like an actual product/service category
    label rather than a document-structure title. Shop-type-agnostic:
    works the same for every PDF, no per-shop-type list to maintain."""
    words = set(text.upper().split())
    return not (words & _DOC_META_HEADING_WORDS)

# ── Junk item filter ──────────────────────────────────────────────────────────
# Patterns that look like prices but are NOT sellable items
_JUNK_ITEM_RE = re.compile(
    r'^('
    r'gst\s*(no\.?|number)?'           # GST No.
    r'|~?\d+\s*g\)?'                   # ~250g)
    r'|pieces?\)?'                     # pieces)
    r'|traditional\s+recipe'           # description fragment
    r'|pickle\s*\+'                    # meal description fragment
    r'|free\s+delivery'                # delivery rule
    r'|delivery\s+(charge|time|zone|areas?|below|above)'  # delivery metadata
    r'|minimum\s+order'                # order rule
    r'|order\s+via'                    # ordering info
    r'|loyalty\s+card'                 # loyalty programme
    r'|offer\s+code'                   # offer metadata
    r'|happy\s+hours?'                 # offer metadata
    r'|family\s+pack'                  # combo deal label
    r'|opening\s+hours?'               # hours metadata
    r'|last\s+order'                   # timing metadata
    r'|home\s+delivery\s+hours'        # delivery hours
    r'|breakfast\s+\('                 # weekend breakfast note
    r'|payment\s+mode'                 # payment metadata
    r'|catering\s+(?:available|service|for)'  # catering note
    r')',
    re.IGNORECASE,
)

_MIN_ITEM_NAME_LEN = 3   # skip single-char / two-char fragments
_MAX_ITEM_NAME_LEN = 80  # skip overly long strings (likely paragraphs)


def is_valid_item(name: str) -> bool:
    """
    Returns True if the name looks like a real sellable item.
    Filters junk rows that pdf extraction picks up as items.
    """
    name = name.strip()
    if len(name) < _MIN_ITEM_NAME_LEN or len(name) > _MAX_ITEM_NAME_LEN:
        return False
    # starts with punctuation / number / bracket — fragment
    if name[0] in ('~', '(', ')', '+', '-', '.', ',', '#'):
        return False
    # purely numeric
    if re.match(r'^\d[\d\s,\.]*$', name):
        return False
    # matches known junk patterns
    if _JUNK_ITEM_RE.match(name):
        return False
    return True


# Rows that are metadata, not sellable items — skip them
META_SKIP_RE = re.compile(
    r'^(Registration\s*No\.?|Address|Phone(?:\s*\(.*?\))?|Emergency\s*Phone|WhatsApp(?:\s*Order)?|'
    r'Monday|Sunday|Emergency|EMI|Kids\s*Special|Senior\s*Citizen|'
    r'Payment\s*Modes?|Health\s*Insurance|Free\s*Consultation|'
    r'FSSAI\s*License|GSTIN?(?:\s*No\.?)?|Zomato|Swiggy|AC\s*Available|Private\s*Dining|'
    r'Owner(?:\s*/\s*Director)?|Head\s*Chef|Cuisine|Seating\s*(?:Capacity)?|Landmark|'
    r'Last\s*Order|Home\s*Delivery\s*Hours|Breakfast(?:\s*\(.*?\))?|'
    r'Free\s*Delivery\s*(?:Above|Below)?|Delivery\s*(?:Charge|Time|Zone|Areas?)|'
    r'Minimum\s*Order|Order\s*via|Catering|Bulk\s*Order|'
    r'Offer\s*Code.*|Happy\s*Hours?\s*Offer|Family\s*Pack|Loyalty\s*Card|'
    r'Weekend\s*Breakfast|Restaurant\s*Name|Equipment|Sterilisation|Parking|'
    r'Salon\s*Name|Clinic\s*Name|Shop\s*Name|Alternate\s*Phone|'
    r'Instagram|Facebook|Accessibility|Lift\s*Available)$',
    re.IGNORECASE
)


# ── Section-level catalogue gate (shop-type-agnostic) ───────────────────────
# META_SKIP_RE above catches specific known ROW labels ("Address", "FSSAI
# License", "Salon Name", ...) but that list has to be hand-extended every
# time a new shop TYPE introduces its own admin-row vocabulary -- a pharmacy
# PDF's "License No." / "Drug Lic. No." / "Public Holidays" / "Night
# Emergency" / "Net Banking" rows all slipped through this way, because the
# regex had only ever been tested against restaurant/salon-style PDFs.
#
# Rather than keep enumerating labels per industry forever, this reads the
# table's own SECTION HEADER (already tracked as `current_category`, e.g.
# "SHOP INFORMATION" / "WORKING HOURS" / "PAYMENT OPTIONS" vs "COMPLETE
# PRODUCT & SERVICES CATALOGUE") to decide whether the section is even the
# kind of section that COULD contain sellable items, for any shop type.
_CATALOG_SECTION_RE = re.compile(
    r'\b(PRODUCTS?|CATALOGUE|CATALOG|MENU|SERVICES?|TREATMENTS?|'
    r'PRICE\s*LIST|PRICING|TARIFF|ITEMS?)\b',
    re.IGNORECASE,
)
_NON_CATALOG_SECTION_RE = re.compile(
    r'\b(INFORMATION|HOURS|TIMING|PAYMENT|DELIVERY|POLICY|POLICIES|'
    r'OFFERS?|LOYALTY|STAFF|EXPERTISE|CONTACT|ABOUT|LICEN[CS]E|'
    r'REGISTRATION|TERMS|FAQ)\b',
    re.IGNORECASE,
)


def _section_looks_administrative(category: str) -> bool:
    """True if this section header reads as shop info/hours/payment/policy
    content rather than a sellable product/service catalogue. A section that
    matches BOTH patterns (e.g. "SERVICE INFORMATION & PRICING") is treated
    as a real catalogue -- the catalogue signal wins on ambiguity, since
    wrongly dropping a real item is worse than wrongly keeping a borderline
    admin row (META_SKIP_RE / is_valid_item / the price checks below still
    get a chance to catch it either way)."""
    if not category:
        return False
    if _CATALOG_SECTION_RE.search(category):
        return False
    return bool(_NON_CATALOG_SECTION_RE.search(category))


def detect_items_from_tables(tables: list) -> tuple[list, list]:
    items = []
    extra_facts: list = []
    seen: set = set()
    current_category = 'General'

    for tbl in tables:
        rows = tbl['rows']
        if not rows:
            continue

        # Single-row table: a pure "Label | Value" fact pair
        # (e.g. "Loyalty Card | Visit 10 times..."), not a
        # header+data table. pdfplumber often extracts these as
        # their own 1-row table -- capture directly as an
        # extra_fact since there is no header row to consume.
        if len(rows) == 1 and len(rows[0]) >= 2:
            label = rows[0][0].strip()
            detail = next((c.strip() for c in rows[0][1:] if c.strip()), "")
            if label and detail and len(label) <= 60:
                extra_facts.append({"label": label, "detail": detail})
            continue

        # Detect single-cell all-caps section header as first row
        non_empty = [c for c in rows[0] if c.strip()]
        if len(non_empty) == 1 and SECTION_HEADER_RE.match(non_empty[0]):
            if _is_real_category_heading(non_empty[0]):
                current_category = non_empty[0].strip()
            # Still strip the heading row either way -- it's never real
            # item/column-header data, whether or not we trust it as a
            # category label.
            rows = rows[1:]
            if not rows:
                continue

        header = rows[0]
        name_col, price_col, desc_col = 0, -1, -1

        for ci, cell in enumerate(header):
            cl = cell.lower()
            if any(k in cl for k in ('name', 'item', 'dish', 'product', 'service', 'treatment', 'type', 'particulars')):
                name_col = ci
            elif any(k in cl for k in ('price', 'rate', 'amount', 'cost', 'fee', 'charge', 'tariff', '₹', 'rs.')):
                price_col = ci
            elif any(k in cl for k in ('description', 'detail', 'desc', 'notes', 'includes', 'inclusion', 'inclusions', 'duration', 'time', 'hrs', 'min')):
                desc_col = ci

        # Auto-detect price column by content if not found in header.
        # Prefer Rs./₹ columns; skip duration columns (e.g. "1.5 hrs").
        DURATION_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:hrs?|min(?:utes?)?|hour)', re.IGNORECASE)
        RS_RE       = re.compile(r'(?:Rs\.?|₹)\s*\d', re.IGNORECASE)

        if price_col == -1:
            # First pass: explicit Rs./₹ symbol in values
            for ci in range(len(header) - 1, 0, -1):
                col_vals = [r[ci] for r in rows[1:] if ci < len(r)]
                rs_hits  = sum(1 for v in col_vals if RS_RE.search(v))
                if col_vals and rs_hits >= max(1, len(col_vals) * 0.3):
                    price_col = ci
                    break

        if price_col == -1:
            # Second pass: numeric-heavy column, skip duration columns
            for ci in range(len(header) - 1, 0, -1):
                col_vals = [r[ci] for r in rows[1:] if ci < len(r)]
                if not col_vals:
                    continue
                if sum(1 for v in col_vals if DURATION_RE.search(v)) > len(col_vals) * 0.4:
                    continue
                if sum(1 for v in col_vals if re.search(r'\d{2,}', v)) > len(col_vals) * 0.4:
                    price_col = ci
                    break

        data_rows = rows[1:] if any(re.search(r'[a-zA-Z]{3,}', c) for c in header) else rows

        for row in data_rows:
            if not row or name_col >= len(row):
                continue
            name = row[name_col].strip()
            if not name or len(name) < 2:
                continue

            # Section header embedded inside table
            if SECTION_HEADER_RE.match(name) and not any(
                re.search(r'\d{2,}', row[ci]) for ci in range(len(row)) if ci != name_col
            ):
                if _is_real_category_heading(name):
                    current_category = name.strip()
                continue

            if META_SKIP_RE.match(name):
                # Correctly excluded from the item catalogue (not a
                # sellable dish/service) -- but capture it as an
                # EXTRA FACT instead of silently dropping it, so
                # loyalty programmes, offer codes, happy-hour deals,
                # combo packs etc. are still available to ground
                # the bot's answers instead of vanishing entirely.
                fact_value = None
                for ci, cell in enumerate(row):
                    if ci != name_col and cell.strip():
                        fact_value = cell.strip()
                        break
                if fact_value:
                    extra_facts.append({"label": name, "detail": fact_value})
                continue

            # ── Section-level catalogue gate (shop-type-agnostic) ────────
            # Backstop for META_SKIP_RE: even when a row's own label isn't
            # on the known-metadata list (new shop type, new label we've
            # never seen), a row sitting under a clearly non-catalogue
            # section header ("SHOP INFORMATION", "WORKING HOURS", "PAYMENT
            # OPTIONS", ...) still shouldn't become a sellable item just
            # because some unrelated number appears in the row.
            if _section_looks_administrative(current_category):
                fact_value = None
                for ci, cell in enumerate(row):
                    if ci != name_col and cell.strip():
                        fact_value = cell.strip()
                        break
                if fact_value:
                    extra_facts.append({"label": name, "detail": fact_value})
                continue

            # ── Junk item guard (FIX 1) ──────────────────────────────────
            if not is_valid_item(name):
                continue

            price = price_min = price_max = None

            if price_col != -1 and price_col < len(row):
                price, price_min, price_max = extract_prices(row[price_col])

            # Scan all non-name cells if still nothing
            if not price and not price_min:
                for ci, cell in enumerate(row):
                    if ci == name_col:
                        continue
                    p, pn, px = extract_prices(cell)
                    if pn and px:
                        price_min, price_max = pn, px
                        break
                    if p and p >= 5:
                        price = p

            if not price and not price_min:
                continue

            # Skip implausibly small values (phone/address noise)
            if price and price < 10:
                continue
            if price_min and price_min < 10 and (not price_max or price_max < 100):
                continue

            key = name.lower().strip()
            if key in seen:
                continue
            seen.add(key)

            item = {'name': name, 'category': current_category, '_source': 'table'}
            if desc_col != -1 and desc_col < len(row):
                desc = row[desc_col].strip()
                if desc and desc.lower() not in ('description', 'details', 'desc', ''):
                    item['description'] = desc

            if price_min and price_max and price_min != price_max:
                item['price_min'] = price_min
                item['price_max'] = price_max
            elif price:
                item['price'] = price
            elif price_min:
                item['price'] = price_min

            items.append(item)

    return items, extra_facts


# ══════════════════════════════════════════════════════════════════════════════
#  4. REGEX-BASED ITEM DETECTION (from plain text lines)
# ══════════════════════════════════════════════════════════════════════════════

PRICE_PATTERNS = [
    r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s+[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*(?:\/\-|\/-)?$',
    r'^(.+?)\s*[|\t]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*$',
    r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s*[₹]\s*(\d[\d,]{1,9})',
]

RANGE_PATTERNS = [
    r'^([A-Za-z][\w\s\(\)\/&,\-]{2,60?})\s+[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*[-–]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})',
    r'^(.+?)\s*[|\t]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})\s*[-–]\s*[₹Rs\.]{0,3}\s*(\d[\d,]{1,9})',
]

HEADER_RE = re.compile(
    r'^\s*([A-Z][A-Z\s&\/]{3,35}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s*[:\-]?\s*$'
)


def _is_junk_item(name, price=None) -> bool:
    """Generic PDF-extraction junk detector (any shop type). Rejects
    description fragments mis-parsed as items, and discount % rows stored
    as tiny prices. No shop-specific words — works for beauty, food,
    pharmacy, dental, etc."""
    import re as _re
    n = (name or "").strip()
    if not n:
        return True
    if n[0].islower():                              # fragment continuation
        return True
    if "+" in n or _re.search(r"\(\d+\s*members?\)", n, _re.I):
        return True
    if _re.match(r"^(and|with|plus|including|reception|lashes)\b", n, _re.I):
        return True
    if price is not None and isinstance(price, (int, float)) and price <= 20:
        if _re.search(r"discount|loyalty|referral|programme|program|offer|%|percent",
                      n, _re.I):
            return True
    return False


def detect_items_regex(text: str) -> list:
    items = []
    current_category = 'General'
    seen_names: set = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 4:
            continue

        hm = HEADER_RE.match(line)
        if hm and len(line) < 50 and not re.search(r'\d{3,}', line):
            current_category = line.strip(':').strip()
            continue

        matched = False
        for pat in RANGE_PATTERNS:
            m = re.match(pat, line, re.IGNORECASE)
            if m:
                name = m.group(1).strip().strip('|-').strip()
                pmin = parse_indian_number(m.group(2))
                pmax = parse_indian_number(m.group(3))
                if pmin and pmax and 1 <= pmin <= 9_999_999 and pmin < pmax:
                    key = name.lower()
                    if key not in seen_names and len(name) >= 3 and is_valid_item(name):
                        seen_names.add(key)
                        items.append({
                            'name': name,
                            'price_min': pmin,
                            'price_max': pmax,
                            'category': current_category,
                            '_source': 'regex_range',
                        })
                        matched = True
                        break

        if matched:
            continue

        for pat in PRICE_PATTERNS:
            m = re.match(pat, line, re.IGNORECASE)
            if m:
                name = re.sub(r'\s*\|.*$', '', m.group(1).strip()).strip()
                price = parse_indian_number(m.group(2))
                if price and 5 <= price <= 9_999_999:
                    key = re.sub(r'\s*\(.*?\)\s*$', '', name).lower().strip()
                    if key not in seen_names and len(name) >= 3 and is_valid_item(name):
                        seen_names.add(key)
                        items.append({
                            'name': name,
                            'price': price,
                            'category': current_category,
                            '_source': 'regex',
                        })
                        break

    return items


# ══════════════════════════════════════════════════════════════════════════════
#  5. METADATA DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_metadata_regex(text: str) -> dict:
    meta: dict = {
        'shop_name': None, 'shop_type': None, 'tagline': None,
        'location': None, 'city': None, 'state': None,
        'phone': None, 'whatsapp': None, 'email': None, 'website': None,
        'hours_weekdays': None, 'hours_sunday': None,
        'payment': [], 'services': [],
        'delivery_free': None, 'delivery_charge': None,
        'delivery_days': None, 'delivery_areas': None,
        'offer_code': None, 'offer_desc': None,
    }

    # Phone numbers
    phone_raw = re.findall(r'(?:\+91|\b0)?[\s\-]?[6-9][\d\s\-]{9,14}', text)

    def clean_phone(p: str) -> str:
        digits = re.sub(r'[^\d]', '', p)
        if digits.startswith('91') and len(digits) == 12:
            return '+91 ' + digits[2:7] + ' ' + digits[7:]
        if len(digits) == 10:
            return '+91 ' + digits[:5] + ' ' + digits[5:]
        return p.strip()

    cleaned_phones = []
    seen_ph: set = set()
    for p in phone_raw:
        digits = re.sub(r'[^\d]', '', p)
        if len(digits) >= 10 and digits[-10] in '6789':
            key = digits[-10:]
            if key not in seen_ph:
                seen_ph.add(key)
                cleaned_phones.append(clean_phone(p))
    if cleaned_phones:
        meta['phone'] = cleaned_phones[0]
        meta['whatsapp'] = cleaned_phones[0]

    # Email
    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', text)
    if emails:
        meta['email'] = emails[0]

    # Website
    websites = re.findall(r'(?:https?://|www\.)[\w\.-]+\.[a-z]{2,}', text)
    if websites:
        meta['website'] = websites[0]

    # Hours
    hours = re.findall(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
        r'[\s\-–]+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?'
        r'[\s:]+\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)',
        text, re.IGNORECASE
    )
    if hours:
        for h in hours:
            line_match = re.search(re.escape(h) + r'.*?(\d{1,2}(?::\d{2})?\s*(?:AM|PM))', text, re.IGNORECASE)
            if line_match and line_match.group(1).lower() not in h.lower():
                meta['hours_weekdays'] = h + ' - ' + line_match.group(1)
                break
        else:
            meta['hours_weekdays'] = hours[0]

    time_ranges = re.findall(
        r'\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)',
        text
    )
    if time_ranges and not meta['hours_weekdays']:
        meta['hours_weekdays'] = time_ranges[0]

    sun_match = re.search(r'Sunday[\s:]+(.{5,50}?(?:AM|PM).*?)(?:\n|$)', text, re.IGNORECASE)
    if sun_match:
        meta['hours_sunday'] = 'Sunday: ' + sun_match.group(1).strip()

    # Location (pincode-based)
    joined_text = re.sub(r'\n', ' ', text)
    # Anchor on an explicit address label first. Without this, the old
    # bounded-backward-capture below would grab whatever 10-200 chars sat
    # before the FIRST pincode anywhere in the whole flattened document --
    # e.g. bleeding a preceding "License No. KL-..." field straight into the
    # address, since after newlines are stripped they become neighbours in
    # one long string even though they're separate table rows in the PDF.
    addr_match = re.search(
        r'\b(?:Address|Located at|Location)\b[\s:|]*'
        r'([A-Za-z0-9][A-Za-z0-9 ,\.\-/#]{5,200}?\b(\d{6})\b)',
        joined_text, re.IGNORECASE,
    )
    if not addr_match:
        # Fallback for PDFs with no explicit "Address" label. Window shrunk
        # from 200->120 chars to reduce (not eliminate) the same cross-field
        # bleed risk when falling back to this less precise method.
        addr_match = re.search(r'([A-Za-z0-9][A-Za-z0-9 ,\.\-/#]{10,120}?\b(\d{6})\b)', joined_text)
    if addr_match:
        meta['location'] = re.sub(r'\s+', ' ', addr_match.group(1)).strip()

    # City
    city_match = re.search(
        r'\b(Thrissur|Kochi|Trivandrum|Thiruvananthapuram|Kozhikode|Calicut|'
        r'Kollam|Palakkad|Alappuzha|Kannur|Malappuram|Ernakulam|'
        r'Mumbai|Delhi|Bangalore|Chennai|Hyderabad|Pune|Kolkata|'
        r'Ahmedabad|Surat|Jaipur|Lucknow|Nagpur|Indore|Bhopal|'
        r'Patna|Vadodara|Coimbatore|Madurai|Agra|Nashik|Faridabad|'
        r'Meerut|Rajkot|Varanasi|Srinagar|Aurangabad|Dhanbad|Amritsar|'
        r'Navi Mumbai|Allahabad|Prayagraj|Ranchi|Howrah|Jabalpur|Gwalior|'
        r'Vijayawada|Jodhpur|Raipur|Kota|Guwahati|Chandigarh|Solapur|'
        r'Hubli|Tiruchirappalli|Bareilly|Mysore|Tiruppur|Gurgaon|Gurugram|'
        r'Mangalore|Belgaum|Gulbarga|Udupi|Manipal)\b',
        text
    )
    if city_match:
        meta['city'] = city_match.group(1)

    # State
    state_match = re.search(
        r'\b(Kerala|Karnataka|Tamil Nadu|Tamilnadu|Maharashtra|Gujarat|'
        r'Rajasthan|Uttar Pradesh|Madhya Pradesh|West Bengal|Bihar|'
        r'Andhra Pradesh|Telangana|Odisha|Punjab|Haryana|Jharkhand|'
        r'Uttarakhand|Assam|Himachal Pradesh|Goa|Chhattisgarh|Delhi)\b',
        text
    )
    if state_match:
        meta['state'] = state_match.group(1)

    # Payment methods
    pay_keywords = {
        'UPI': r'\bUPI\b', 'GPay': r'\bGPay\b|Google Pay',
        'PhonePe': r'\bPhonePe\b', 'Cash': r'\bCash\b',
        'Cards': r'\bCard\b|Credit Card|Debit Card',
        'Paytm': r'\bPaytm\b', 'NetBanking': r'Net Banking|NEFT|RTGS',
        'Cheque': r'\bCheque\b|\bCheck\b',
    }
    for method, pat in pay_keywords.items():
        if re.search(pat, text, re.IGNORECASE):
            meta['payment'].append(method)

    # Shop type detection
    TYPE_KW = {
        'restaurant':    ['menu', 'biriyani', 'curry', 'dosa', 'restaurant', 'cafe', 'food', 'dining'],
        'clothing':      ['shirt', 'saree', 'kurta', 'dress', 'garment', 'fashion', 'wear', 'textile'],
        'dental_clinic': ['dental', 'dentist', 'tooth', 'teeth', 'root canal', 'braces', 'clinic'],
        'beauty_parlour': ['salon', 'parlour', 'makeup', 'facial', 'bridal', 'spa', 'beauty'],
        'jewellery':     ['gold', 'silver', 'diamond', 'jewel', 'necklace', 'ring', 'jewellery'],
        'gym':           ['gym', 'fitness', 'workout', 'membership', 'trainer', 'yoga'],
        'hospital':      ['hospital', 'doctor', 'ward', 'surgery', 'opd', 'patient', 'medical'],
        'pharmacy':      ['pharmacy', 'medicine', 'drug', 'tablet', 'prescription', 'chemist'],
        'optical':       ['optical', 'spectacle', 'glasses', 'lens', 'eye test', 'frame'],
        'electronics':   ['mobile', 'laptop', 'phone', 'television', 'electronics', 'gadget'],
        'supermarket':   ['supermarket', 'grocery', 'vegetables', 'fruits', 'mart', 'kirana'],
        'bakery':        ['bakery', 'cake', 'bread', 'pastry', 'bake', 'cookie'],
        'hotel':         ['hotel', 'room', 'check-in', 'accommodation', 'resort', 'suite', 'tariff'],
        'travel_agency': ['tour', 'travel', 'package', 'visa', 'itinerary', 'holiday', 'tourism'],
        'real_estate':   ['property', 'flat', 'apartment', 'plot', 'villa', 'rent', 'sqft', 'bhk'],
        'law_firm':      ['lawyer', 'advocate', 'legal', 'court', 'law firm', 'attorney'],
        'ca_firm':       ['chartered', 'accountant', 'gst', 'income tax', 'audit', 'tds', 'itr'],
        'school':        ['school', 'college', 'admission', 'student', 'class', 'education'],
    }
    tl = text.lower()
    scores = {t: sum(1 for kw in kws if kw in tl) for t, kws in TYPE_KW.items()}
    best = max(scores, key=scores.get) # pyright: ignore[reportCallIssue, reportArgumentType]
    meta['shop_type'] = best if scores[best] > 0 else 'general'

    # ── Universal offer extraction (any shop type) ──────────────────────────
    # Finds an UPPERCASE promo code near "offer/code/coupon/promo" plus the
    # description after it. Works for FIRSTGLAM (beauty), FIRSTVISIT (dental),
    # HUNGRY50 (restaurant) — no shop-specific words. A missing offer stays
    # None (never faked), so the bot uses RAG/handoff instead of inventing one.
    _offer_re = re.compile(
        r"(?:offer\s+code|code|coupon|promo)\s+"
        r"([A-Z][A-Z0-9]{3,15})"
        r"\s*[-\u2013\u2014:]?\s*"
        r"([^.\n]{5,80})",
        re.IGNORECASE,
    )
    # code-first format, e.g. "HEALTH5 - 5% off..." (code must contain a digit)
    _offer_re2 = re.compile(
        r"(?:^|\n)\s*"
        r"([A-Z][A-Z0-9]{2,14}\d[A-Z0-9]*|\b[A-Z]{4,}\d{1,3})"
        r"\s*[-\u2013\u2014:]\s*"
        r"(\d{1,3}\s*%|\bRs|\bflat|[^.\n]{0,5}off[^.\n]{0,60})",
        re.IGNORECASE,
    )
    _om = _offer_re.search(text)
    if _om and (_om.group(1).strip().isupper() or any(c.isdigit() for c in _om.group(1))):
        meta['offer_code'] = _om.group(1).strip()
        meta['offer_desc'] = _om.group(2).strip().rstrip("-\u2013\u2014: ")
    else:
        _om2 = _offer_re2.search(text)
        if _om2 and any(c.isdigit() for c in _om2.group(1)):
            meta['offer_code'] = _om2.group(1).strip()
            meta['offer_desc'] = _om2.group(2).strip()

    # Shop name from first few clean lines
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:8]:
        if re.search(r'\d{7,}|@|www\.|http', line):
            continue
        if 5 < len(line) < 60 and not line.startswith('['):
            meta['shop_name'] = line
            break

    # Delivery fields -- these dict keys existed above but were never
    # actually populated by any regex. Restaurant/food-service PDFs
    # commonly state these as "Free Delivery Above Rs. X",
    # "Delivery Charge Below Rs.X Rs. Y flat", "Delivery Zone ...",
    # "Delivery Time ... minutes".
    _free_above = re.search(
        r'Free\s+Delivery\s+Above\s+Rs\.?\s*([\d,]+)', text, re.IGNORECASE)
    if _free_above:
        meta['delivery_free'] = f"₹{_free_above.group(1)}"

    _charge = re.search(
        r'Delivery\s+Charge\s+Below\s+Rs\.?\s*[\d,]+\s+Rs\.?\s*([\d,]+)',
        text, re.IGNORECASE)
    if _charge:
        meta['delivery_charge'] = f"₹{_charge.group(1)} flat"

    _days = re.search(
        r'Delivery\s+Time\s+([^\n]{3,60})', text, re.IGNORECASE)
    if _days:
        meta['delivery_days'] = _days.group(1).strip().rstrip('.')

    _areas = re.search(
        r'Delivery\s+Zone\s+([^\n]{3,150}(?:\n[^\n]{3,80})?)',
        text, re.IGNORECASE)
    if _areas:
        meta['delivery_areas'] = re.sub(r'\s*\n\s*', ' ', _areas.group(1).strip()).rstrip('.')

    return meta


# ══════════════════════════════════════════════════════════════════════════════
#  6. MERGE & BUILD shop_info
# ══════════════════════════════════════════════════════════════════════════════

def llm_extract_items(raw_text: str, shop_type: str = "general",
                      min_needed: int = 5) -> list:
    """LLM fallback for UNSTRUCTURED PDFs. When table+regex extraction is thin
    (a real shop owner pasted prose, a flyer, or a non-tabular layout), regex
    finds almost nothing. This sends the raw text to Ollama and asks for a
    structured item list. Returns [] on any failure (Ollama down, bad JSON) so
    the caller safely keeps whatever regex did find. Costs nothing on clean
    PDFs because the caller only invokes it when regex came back short."""
    import json as _json
    import re as _re
    try:
        import ollama_client
    except Exception:
        return []
    if not ollama_client.is_up():
        print("[pdf] LLM fallback skipped — Ollama not running")
        return []

    snippet = (raw_text or "")[:4000]
    if len(snippet.strip()) < 40:
        return []

    prompt = (
        "You are a data extraction tool. Read the shop document below and "
        "extract every product or service with its price.\n\n"
        f"SHOP TYPE: {shop_type}\n\n"
        "OUTPUT FORMAT - return ONLY a JSON array, no other text:\n"
        '[{"name": "Item Name", "price": 500, "category": "general"}]\n\n'
        "RULES:\n"
        "- Extract the item/service NAME and its PRICE as a number (no symbol).\n"
        "- If a price is a range or 'from X', use the lower number.\n"
        "- If an item has no price, skip it.\n"
        "- Use a short category if obvious, else 'general'.\n"
        "- Do NOT invent items. Only extract what is written.\n"
        "- Return ONLY the JSON array.\n\n"
        f"DOCUMENT:\n{snippet}\n\nJSON array:"
    )

    try:
        reply, ok = ollama_client.generate(
            prompt, temperature=0.1, num_predict=800, lang="english",
        )
    except Exception as e:
        print(f"[pdf] LLM extraction error: {e}")
        return []
    if not ok or not reply:
        return []

    reply = _re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=_re.M).strip()
    m = _re.search(r"\[.*\]", reply, _re.S)
    if not m:
        return []
    try:
        data = _json.loads(m.group(0))
    except _json.JSONDecodeError:
        return []

    items = []
    seen = set()
    for d in (data if isinstance(data, list) else []):
        if not isinstance(d, dict):
            continue
        name = str(d.get("name", "")).strip()
        price = d.get("price")
        if not name or price is None:
            continue
        try:
            price = int(float(price))
        except (ValueError, TypeError):
            continue
        if price <= 0 or _is_junk_item(name, price):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "name": name,
            "price": price,
            "category": str(d.get("category", "general")).strip() or "general",
            "_source": "llm",
        })
    print(f"[pdf] LLM fallback extracted {len(items)} items from unstructured text")
    return items


def build_shop_info(auto_meta: dict, table_items: list, regex_items: list,
                     extra_facts: list | None = None) -> dict:
    # Merge items (table first — more reliable), deduplicate
    all_items: list = []
    seen_names: set = set()
    for item in table_items + regex_items:
        clean_name = re.sub(r'\s*\|.*$', '', item['name']).strip()
        _price = item.get('price') or item.get('price_min')
        if _is_junk_item(clean_name, _price):
            continue
        key = re.sub(r'\s*\(.*?\)\s*$', '', clean_name).lower().strip()
        if key not in seen_names:
            seen_names.add(key)
            all_items.append(item)

    # Build SHOP_INFO with auto-detected values, override with MANUAL_OVERRIDES
    shop_info = {
        # Identity
        'bot_name':       auto_meta.get('shop_name', '').split()[0][:10] if auto_meta.get('shop_name') else None,
        'shop_name':      auto_meta.get('shop_name'),
        'shop_type':      auto_meta.get('shop_type', 'general'),
        'tagline':        auto_meta.get('tagline'),
        'description':    None,
        # Location
        'location':       auto_meta.get('location'),
        'city':           auto_meta.get('city'),
        'state':          auto_meta.get('state', 'Kerala'),
        # Hours
        'hours_weekdays': auto_meta.get('hours_weekdays'),
        'hours_sunday':   auto_meta.get('hours_sunday'),
        'hours_holiday':  'Check WhatsApp for holiday hours',
        # Contact
        'whatsapp':       auto_meta.get('whatsapp'),
        'phone':          auto_meta.get('phone'),
        'email':          auto_meta.get('email'),
        'website':        auto_meta.get('website'),
        # Payment & Services
        'payment':        auto_meta.get('payment') or ['UPI', 'Cash', 'Cards'],
        'services':       [],
        # Delivery
        'delivery_areas': auto_meta.get('delivery_areas'),
        'delivery_free':  auto_meta.get('delivery_free'),
        'delivery_charge': auto_meta.get('delivery_charge'),
        'delivery_days':  auto_meta.get('delivery_days'),
        # Returns
        'return_days':    0,
        'return_condition': None,
        'refund_days':    None,
        # Offers
        'offer_code':     auto_meta.get('offer_code'),
        'offer_desc':     auto_meta.get('offer_desc'),
        # Escalation
        'escalate_whatsapp': auto_meta.get('whatsapp'),
        'escalate_email':    auto_meta.get('email'),
        # Items (strip internal _source/_line keys before use in generate_shop.py)
        'shop_items': [
            {k: v for k, v in item.items() if not k.startswith('_')}
            for item in all_items
            if is_valid_item(item.get('name', ''))   # FIX 1: final junk guard
        ],
        # Promotional/programme facts correctly excluded from
        # shop_items (not sellable dishes) but still real, useful
        # facts -- loyalty cards, offer codes, happy-hour deals,
        # combo packs. Without this they vanish entirely instead
        # of being available to ground the bot's answers.
        'extra_facts': extra_facts or [],
    }

    # Apply manual overrides
    for k, v in MANUAL_OVERRIDES.items():
        if v is not None:
            shop_info[k] = v

    return shop_info


# ══════════════════════════════════════════════════════════════════════════════
#  7. PRINT SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

OPTIONAL_FIELDS = {
    'tagline', 'description', 'offer_code', 'offer_desc',
    'refund_days', 'return_condition', 'delivery_areas',
    'delivery_free', 'delivery_days', 'delivery_charge',
    'hours_holiday', 'escalate_whatsapp', 'escalate_email', 'website',
}

KEY_FIELDS = [
    'location', 'city', 'hours_sunday', 'whatsapp', 'phone', 'services',
]


def print_summary(shop_info: dict):
    print('\n📦 Final shop_info summary:')
    print('=' * 55)
    for k, v in shop_info.items():
        if k == 'shop_items':
            print(f'  shop_items          : {len(v)} items')
        elif v and v not in ([], {}, ''):
            print(f'  ✅ {k:20s}: {str(v)[:50]}')
        else:
            print(f'  ⚠️  {k:20s}: MISSING')

    missing = [
        k for k, v in shop_info.items()
        if k not in ('shop_items', 'return_days') and not v and k not in OPTIONAL_FIELDS
    ]
    if missing:
        print(f'\n⚠️  Fields to fill manually: {missing}')
        print('   Edit MANUAL_OVERRIDES at top of script and re-run')
    else:
        print('\n✅ All key fields filled!')


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Extract shop info from a PDF and output shop_info.json'
    )
    parser.add_argument('pdf', help='Path to shop PDF file')
    parser.add_argument('--out', default='shop_info.json', help='Output JSON file (default: shop_info.json)')
    args = parser.parse_args()

    if not Path(args.pdf).exists():
        print(f'❌ File not found: {args.pdf}')
        sys.exit(1)

    # Step 1 — Extract PDF
    all_pages, all_tables, full_text = extract_pdf(args.pdf)

    if not full_text.strip():
        print('No text to process. Exiting.')
        sys.exit(1)

    # Step 2 — Print table summary
    print(f'\n\n{"=" * 60}')
    print(f'TABLE SUMMARY  ({len(all_tables)} tables found)')
    print('=' * 60)
    for ti, tbl in enumerate(all_tables, 1):
        rows = tbl['rows']
        print(f'\n┌── Table {ti}  (page {tbl["page"]}, {len(rows)} rows) ──────────────────')
        for row in rows:
            truncated = [c[:32] for c in row if c.strip()]
            if truncated:
                print('│ ' + ' │ '.join(truncated))

    # Step 3 — Detect items
    print(f'\n\n{"=" * 60}')
    print('ITEM DETECTION')
    print('=' * 60)
    table_items, extra_facts = detect_items_from_tables(all_tables)
    regex_items = detect_items_regex(full_text)

    # LLM FALLBACK for unstructured PDFs: if table+regex extraction is thin
    # (prose menus, flyers, non-tabular layouts a real shop owner uploads),
    # ask Ollama to read the raw text and extract structured items. Only runs
    # when needed, so clean tabular PDFs pay zero cost.
    _MIN_ITEMS = 5
    if len(table_items) + len(regex_items) < _MIN_ITEMS:
        _stype = detect_metadata_regex(full_text).get('shop_type', 'general')
        print(f"\n⚠️  Only {len(table_items)+len(regex_items)} items from regex — "
              f"trying LLM extraction for this unstructured PDF...")
        _llm_items = llm_extract_items(full_text, _stype, _MIN_ITEMS)
        regex_items = regex_items + _llm_items

    # Quick merge just for count display
    all_merged: list = []
    seen_tmp: set = set()
    for item in table_items + regex_items:
        key = re.sub(r'\s*\(.*?\)\s*$', '', item['name']).lower().strip()
        if key not in seen_tmp:
            seen_tmp.add(key)
            all_merged.append(item)

    print(f'✅ Auto-detected {len(all_merged)} items')
    print(f'   From tables : {len(table_items)}')
    print(f'   From text   : {len([i for i in all_merged if i.get("_source") == "regex"])}')

    print('\n📋 All detected items:')
    print('-' * 80)
    print(f'{"#":3} {"Src":6} {"Category":22} {"Name":30} {"Price"}')
    print('-' * 80)
    for i, item in enumerate(all_merged, 1):
        src  = item.get('_source', '?')[:5]
        cat  = item.get('category', '?')[:21]
        name = item['name'][:29]
        if 'price' in item:
            price_str = f"₹{item['price']:,}"
        elif 'price_min' in item:
            price_str = f"₹{item['price_min']:,}–{item['price_max']:,}"
        else:
            price_str = '?'
        print(f'{i:3} [{src:5}] {cat:22} {name:30} {price_str}')

    # Step 4 — Detect metadata
    print(f'\n\n{"=" * 60}')
    print('METADATA DETECTION')
    print('=' * 60)
    auto_meta = detect_metadata_regex(full_text)
    for k, v in auto_meta.items():
        if v and v not in ([],):
            print(f'  ✅ {k:20s}: {v}')
        else:
            print(f'  ❌ {k:20s}: (not found — fill in MANUAL_OVERRIDES)')

    print('\n⚠️  Review carefully! Regex detection is approximate.')

    # Step 5 — Build and save shop_info
    shop_info = build_shop_info(auto_meta, table_items, regex_items, extra_facts)
    print_summary(shop_info)

    out_path = args.out
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(shop_info, f, ensure_ascii=False, indent=2)
    print(f'\n✅ {out_path} saved ({Path(out_path).stat().st_size:,} bytes)')
    print(f'   {len(shop_info["shop_items"])} items inside')

    print('''
📌 Next steps:
─────────────────────────────────────────
Option A — Feed JSON directly into generate_shop.py:
  1. Open generate_shop.py
  2. Replace SHOP_INFO = { ... } with the contents of shop_info.json
  3. python generate_shop.py

Option B — Use extractor.py (Ollama fills missing fields automatically):
  python extractor.py --pdf your_menu.pdf
  python extractor.py --url https://yourshop.com
  python extractor.py --url https://yourshop.com --pdf menu.pdf
''')


if __name__ == '__main__':
    main()