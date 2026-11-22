"""
menu_export.py — generates a customer-facing "full menu" PDF from a shop's
extracted shop_items, deliberately excluding address, contact, loyalty
card, and offer info that lives elsewhere in shop_info.

Called once, right after /admin/extract-pdf saves shop_items.json — NOT
per chat request. The generated file is cached at shops/{slug}/menu.pdf
and reused on every "full menu" query until the shop's PDF is re-uploaded.
"""

import os
import logging
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

log = logging.getLogger(__name__)

_CATALOG_NOUNS = {
    "restaurant": "Menu", "bakery": "Menu", "coffee_shop": "Menu", "fast_food": "Menu",
    "beauty_parlour": "Service List", "salon": "Service List", "spa": "Service List",
    "pharmacy": "Product Price List",
    "dental_clinic": "Treatment List", "skin_clinic": "Treatment List",
}


def _menu_path(slug: str) -> Path:
    return Path("shops") / slug / "menu.pdf"


def _price_label(item: dict) -> str:
    """Render exact prices and complete extracted ranges without data loss."""
    price, price_min, price_max = item.get("price"), item.get("price_min"), item.get("price_max")

    def money(value) -> str:
        return f"Rs. {value:,.0f}" if isinstance(value, (int, float)) else str(value)

    if price not in (None, ""):
        return money(price)
    if price_min not in (None, "") and price_max not in (None, ""):
        return f"{money(price_min)} - {money(price_max)}"
    if price_min not in (None, ""):
        return f"From {money(price_min)}"
    if price_max not in (None, ""):
        return f"Up to {money(price_max)}"
    return "Price on request"


def build_menu_pdf(
    slug: str, shop_name: str | None, shop_items: list, shop_type: str | None = None,
) -> str | None:
    """Generate shops/{slug}/menu.pdf from shop_items only.

    Deliberately reads ONLY name/category/price from each item — never
    touches shop_info's location, whatsapp, offer_code, etc. Returns the
    saved path on success, or None if there were no valid items to render
    (so callers can skip attaching a menu link for empty/service-only shops).
    """
    if not shop_items:
        log.info("[menu_export] no shop_items for slug=%s, skipping PDF", slug)
        return None

    out_path = _menu_path(slug)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Group by category, preserving first-seen order
    by_cat: dict[str, list] = {}
    for item in shop_items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        cat = (item.get("category") or "Other").strip() or "Other"
        by_cat.setdefault(cat, []).append(item)

    if not by_cat:
        log.info("[menu_export] no valid named items for slug=%s, skipping PDF", slug)
        return None

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MenuTitle", parent=styles["Title"], fontSize=20, spaceAfter=4,
    )
    cat_style = ParagraphStyle(
        "MenuCategory", parent=styles["Heading2"], fontSize=13,
        spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#333333"),
    )
    display_title_style = ParagraphStyle(
        "CatalogDisplayTitle", parent=styles["Title"], fontSize=20, spaceAfter=4,
    )
    # The old title literal in this legacy file contains a replacement
    # character. Keep that paragraph visually inert while emitting a clean,
    # shop-type-aware title below.
    title_style.textColor = colors.white
    title_style.fontSize = 1
    title_style.leading = 1

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
    )

    catalog_name = _CATALOG_NOUNS.get((shop_type or "").strip().lower(), "Full Catalogue")
    story = [
        Paragraph(f"{escape(shop_name or 'Our Shop')} - {catalog_name}", display_title_style),
        Paragraph(f"{shop_name or 'Our'} — Full Menu", title_style),
        Spacer(1, 8),
    ]

    for cat, items in by_cat.items():
        story.append(Paragraph(cat, cat_style))
        rows = [["Item", "Price"]]
        for item in items:
            name = item.get("name", "").strip()
            description = (item.get("description") or "").strip()
            label = escape(name)
            if description:
                label += f"<br/><font size=8 color='#555555'>{escape(description)}</font>"
            rows.append([Paragraph(label, styles["BodyText"]), _price_label(item)])

        table = Table(rows, colWidths=[120 * mm, 40 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ]))
        story.append(table)

    doc.build(story)
    log.info("[menu_export] menu.pdf built for slug=%s (%d categories, %d items)",
              slug, len(by_cat), sum(len(v) for v in by_cat.values()))
    return str(out_path)


def get_menu_path_if_exists(slug: str) -> str | None:
    """Return the path to an already-generated menu.pdf for this shop,
    or None if it hasn't been built yet (e.g. shop has no shop_items)."""
    path = _menu_path(slug)
    return str(path) if path.exists() else None
