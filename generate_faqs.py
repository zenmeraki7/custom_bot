"""
generate_faqs.py  — v1.0
=========================
Auto-generates complete English + Manglish FAQs for ANY shop type.

Strategy:
  1. UNIVERSAL FAQS — 15 categories that apply to every shop (contact, hours,
     payment, delivery, offers, etc.)  — hardcoded, perfect quality
  2. SHOP-TYPE FAQS — loaded from SHOP_FAQ_TEMPLATES dict below (hardcoded for
     known types, Ollama-generated + cached for unknown types)
  3. OUTPUT FORMAT — matches your existing faq_templates/ JSON exactly:
     [{"category": "...", "question": "...", "answer": "..."}, ...]

Usage:
    python generate_faqs.py --type restaurant --out faq_templates/
    python generate_faqs.py --all --out faq_templates/
    python generate_faqs.py --type pet_shop --out faq_templates/  # unknown → Ollama

Output:
    faq_templates/{type}_english.json
    faq_templates/{type}_manglish.json
"""

from __future__ import annotations
import json, os, sys, argparse, re, time
from pathlib import Path
from typing import Optional
import requests

import ollama_client
CACHE_DIR    = Path("faq_cache")

# ═══════════════════════════════════════════════════════════════════════════
#  UNIVERSAL FAQs — every shop gets these regardless of type
#  Format: list of (category, en_q, en_a, ml_q, ml_a)
# ═══════════════════════════════════════════════════════════════════════════

UNIVERSAL: list[tuple] = [
    (
        "store_timings",
        "What are your opening hours?",
        "Our shop is open during regular business hours. Please contact us or check WhatsApp for exact timings.",
        "Ningalude opening hours enthaanu?",
        "Njangalude shop regular business hoursil thurannu irikkunnu. Exact timings ariyaan WhatsApp cheyyuka.",
    ),
    (
        "holiday_hours",
        "Are you open on Sundays and holidays?",
        "Sunday and holiday timings may vary. Please check WhatsApp or call us for updated information.",
        "Sundaykalkum holidayskum open aano?",
        "Sunday, holiday timings vary cheyyum. WhatsApp cheyyuka allenkil call cheyyuka.",
    ),
    (
        "location_address",
        "Where is your shop located?",
        "Our shop is located in the local area. WhatsApp us for the exact address and directions.",
        "Ningalude shop evide aanu?",
        "Njangalude shop local areayil aanu. Exact address ariyaan WhatsApp cheyyuka.",
    ),
    (
        "contact_info",
        "How can I contact you?",
        "You can reach us by phone, WhatsApp, email, or by visiting the shop directly.",
        "Ningalumaayi engane contact cheyyam?",
        "Phone, WhatsApp, email vazhi allenkil direct visit cheythu contact cheyyam.",
    ),
    (
        "whatsapp_contact",
        "What is your WhatsApp number?",
        "Our WhatsApp number is available on the shop profile. Message us anytime for quick support.",
        "Ningalude WhatsApp number enthaanu?",
        "Shop profileil WhatsApp number undu. Anytime message cheyyam, quick response kittum.",
    ),
    (
        "payment_methods",
        "What payment methods do you accept?",
        "We accept Cash, UPI, Google Pay, PhonePe, Paytm, Credit/Debit cards, and online transfers.",
        "Ethu payment methods accept cheyyum?",
        "Cash, UPI, Google Pay, PhonePe, Paytm, Credit/Debit cards, online transfers ellam accept cheyyum.",
    ),
    (
        "upi_payment",
        "Do you accept UPI payments?",
        "Yes, all major UPI apps including Google Pay, PhonePe, and Paytm are accepted.",
        "UPI payment accept cheyyumo?",
        "Athe, Google Pay, PhonePe, Paytm ulppedunna ella major UPI appskalum accept cheyyum.",
    ),
    (
        "offers_discounts",
        "Do you have any offers or discounts?",
        "Yes, we run seasonal offers, festive discounts, and special deals. Check WhatsApp for current offers.",
        "Offers allenkil discounts undo?",
        "Athe, seasonal offers, festive discounts, special deals undu. Current offers WhatsApp check cheyyuka.",
    ),
    (
        "home_delivery",
        "Do you provide home delivery?",
        "Yes, home delivery is available for selected products and areas. Contact us for delivery details.",
        "Home delivery undo?",
        "Athe, selected productsinum areasinum home delivery available aanu. Details ariyaan contact cheyyuka.",
    ),
    (
        "delivery_charges",
        "What are the delivery charges?",
        "Delivery charges vary based on location and order amount. Free delivery may apply above a minimum order.",
        "Delivery chargees ethreyaanu?",
        "Location, order amount anusari delivery charges vary cheyyum. Minimum order above free delivery undaavaam.",
    ),
    (
        "online_order",
        "Can I place an order online?",
        "Yes, orders can be placed via WhatsApp, phone call, or our website/app if available.",
        "Online ayi order cheyyan pattumo?",
        "Athe, WhatsApp, phone call, website/app vazhi order cheyyam.",
    ),
    (
        "bulk_order",
        "Do you accept bulk or event orders?",
        "Yes, bulk orders for events, parties, and functions are accepted. Contact us in advance for planning.",
        "Bulk allenkil event orders accept cheyyumo?",
        "Athe, events, parties, functionsinu bulk orders accept cheyyum. Planning-inu advance ayi contact cheyyuka.",
    ),
    (
        "parking",
        "Is parking available?",
        "Parking availability depends on our location. Please contact us for parking information.",
        "Parking undo?",
        "Parking availability location anusari undaavum. Info ariyaan contact cheyyuka.",
    ),
    (
        "customer_support",
        "How do I resolve a complaint or issue?",
        "Please contact us directly via phone or WhatsApp. We will resolve your issue as quickly as possible.",
        "Complaint allenkil issue engane resolve cheyyam?",
        "Phone allenkil WhatsApp vazhi directly contact cheyyuka. Issue possible aayal vegam resolve cheyyum.",
    ),
    (
        "feedback",
        "How can I give feedback?",
        "You can share feedback via WhatsApp, Google Review, or by speaking to our staff directly.",
        "Feedback engane nalkanam?",
        "WhatsApp, Google Review vazhi allenkil staff-odu directly feedback parayan.",
    ),
]

# ═══════════════════════════════════════════════════════════════════════════
#  SHOP-TYPE FAQ TEMPLATES
#  Format per entry: {"category": str, "en_q": str, "en_a": str, "ml_q": str, "ml_a": str}
# ═══════════════════════════════════════════════════════════════════════════

SHOP_FAQS: dict[str, list[dict]] = {

    # ── RESTAURANT ──────────────────────────────────────────────────────────
    "restaurant": [
        {"category": "menu_overview",        "en_q": "What is available on your menu?",                    "en_a": "Our menu includes starters, soups, rice, biryani, curries, breads, noodles, seafood, chicken, mutton, beef, desserts, and beverages.",     "ml_q": "Menu-il enthokke undu?",                         "ml_a": "Starters, soups, rice, biryani, curries, breads, noodles, seafood, chicken, mutton, beef, desserts, beverages ellam undu."},
        {"category": "veg_options",          "en_q": "Do you have vegetarian options?",                    "en_a": "Yes, we have a variety of vegetarian dishes including rice, curries, breads, and starters.",                                             "ml_q": "Veg options undo?",                              "ml_a": "Athe, rice, curries, breads, starters ulppedunna variety veg dishes undu."},
        {"category": "non_veg_options",      "en_q": "Do you serve non-vegetarian food?",                  "en_a": "Yes, we serve chicken, mutton, beef, seafood, and egg-based dishes.",                                                                  "ml_q": "Non-veg food serve cheyyumo?",                   "ml_a": "Athe, chicken, mutton, beef, seafood, egg dishes ellam serve cheyyunnu."},
        {"category": "biryani",              "en_q": "Is biryani available?",                              "en_a": "Yes, we serve chicken biryani, mutton biryani, beef biryani, and vegetable biryani.",                                                   "ml_q": "Biryani undo?",                                  "ml_a": "Athe, chicken, mutton, beef, vegetable biryani ellam undu."},
        {"category": "seafood",              "en_q": "What seafood dishes are available?",                 "en_a": "Fish fry, fish curry, prawn, crab, and other seafood items are available based on daily catch.",                                        "ml_q": "Seafood dishes undo?",                           "ml_a": "Fish fry, fish curry, prawn, crab, matte seafood daily availability anusari undu."},
        {"category": "table_booking",        "en_q": "Can I book a table in advance?",                     "en_a": "Yes, table reservations can be made by phone or WhatsApp.",                                                                            "ml_q": "Table advance ayi book cheyyaamo?",              "ml_a": "Athe, phone allenkil WhatsApp vazhi table reservation cheyyam."},
        {"category": "takeaway",             "en_q": "Do you provide takeaway service?",                   "en_a": "Yes, takeaway and parcel service is available.",                                                                                       "ml_q": "Takeaway undo?",                                 "ml_a": "Athe, takeaway, parcel service available aanu."},
        {"category": "meal_combos",          "en_q": "Do you have meal combos or special meals?",          "en_a": "Yes, lunch meals, dinner combos, and special thali options may be available.",                                                         "ml_q": "Meal combos undo?",                              "ml_a": "Athe, lunch meals, dinner combos, special thali options undaavaam."},
        {"category": "food_delivery",        "en_q": "Do you offer food delivery?",                        "en_a": "Yes, food delivery is available through WhatsApp, phone, or food delivery apps.",                                                      "ml_q": "Food delivery undo?",                            "ml_a": "Athe, WhatsApp, phone, food delivery apps vazhi delivery available aanu."},
        {"category": "spice_level",          "en_q": "Can I customize the spice level?",                   "en_a": "Yes, we can adjust spice levels as per your preference.",                                                                             "ml_q": "Spice level customize cheyyaamo?",               "ml_a": "Athe, ningalude preference anusari spice level adjust cheyyam."},
        {"category": "family_dining",        "en_q": "Do you have a family dining area?",                  "en_a": "Yes, we have seating arrangements suitable for families and groups.",                                                                  "ml_q": "Family dining area undo?",                       "ml_a": "Athe, families, groups-inu suitable seating arrangements undu."},
        {"category": "catering",             "en_q": "Do you provide catering for events?",                "en_a": "Yes, we offer catering services for weddings, parties, and corporate events.",                                                         "ml_q": "Events-inu catering service undo?",              "ml_a": "Athe, weddings, parties, corporate events-inu catering service undu."},
        {"category": "hygiene",              "en_q": "How do you maintain food hygiene?",                  "en_a": "We follow strict hygiene standards with fresh ingredients, clean utensils, and regular kitchen inspections.",                           "ml_q": "Food hygiene engane maintain cheyyunnu?",         "ml_a": "Fresh ingredients, clean utensils, regular kitchen inspection vazhi strict hygiene follow cheyyunnu."},
        {"category": "special_diet",         "en_q": "Do you have diet or healthy food options?",          "en_a": "Yes, low-calorie, low-oil, and healthy meal options may be available on request.",                                                    "ml_q": "Diet food options undo?",                        "ml_a": "Athe, low-calorie, low-oil, healthy meals request anusari undaavaam."},
        {"category": "desserts",             "en_q": "What desserts do you serve?",                        "en_a": "We serve ice cream, gulab jamun, payasam, cakes, and other traditional and modern desserts.",                                         "ml_q": "Desserts undo?",                                 "ml_a": "Ice cream, gulab jamun, payasam, cakes, matte traditional, modern desserts ellam undu."},
    ],

    # ── BAKERY ──────────────────────────────────────────────────────────────
    "bakery": [
        {"category": "products_overview",    "en_q": "What products do you sell?",                         "en_a": "We sell cakes, pastries, breads, cookies, buns, snacks, beverages, and customized bakery items.",                                       "ml_q": "Enthokke products undu?",                        "ml_a": "Cakes, pastries, breads, cookies, buns, snacks, beverages, customized items ellam undu."},
        {"category": "custom_cakes",         "en_q": "Do you make customized cakes?",                      "en_a": "Yes, customized cakes for birthdays, weddings, anniversaries, and special events are available.",                                     "ml_q": "Customized cakes cheyyumo?",                     "ml_a": "Athe, birthdays, weddings, anniversaries, special events-inu customized cakes cheyyum."},
        {"category": "photo_cakes",          "en_q": "Do you make photo cakes?",                           "en_a": "Yes, photo cakes with custom images can be prepared on order.",                                                                       "ml_q": "Photo cake cheyyumo?",                           "ml_a": "Athe, custom images ulpetta photo cakes order ayi cheyyam."},
        {"category": "theme_cakes",          "en_q": "Do you make theme cakes?",                           "en_a": "Yes, theme cakes for kids, parties, and special occasions are available.",                                                           "ml_q": "Theme cake cheyyumo?",                           "ml_a": "Athe, kids, parties, special occasions-inu theme cakes undu."},
        {"category": "eggless_cakes",        "en_q": "Do you have eggless cakes?",                         "en_a": "Yes, eggless cakes and pastries are available for all occasions.",                                                                   "ml_q": "Eggless cake undo?",                             "ml_a": "Athe, ella occasionsinum eggless cakes, pastries available aanu."},
        {"category": "cake_flavours",        "en_q": "What cake flavours are available?",                  "en_a": "Chocolate, vanilla, butterscotch, red velvet, black forest, fruit, and other flavours are available.",                               "ml_q": "Cake flavours enthokke undu?",                   "ml_a": "Chocolate, vanilla, butterscotch, red velvet, black forest, fruit, matte flavours undu."},
        {"category": "advance_order",        "en_q": "Can I pre-order a cake?",                            "en_a": "Yes, cakes can be pre-ordered via WhatsApp, phone, or direct visit at least 1-2 days in advance.",                                  "ml_q": "Cake advance order cheyyaamo?",                  "ml_a": "Athe, WhatsApp, phone, direct visit vazhi 1-2 days advance ayi pre-order cheyyam."},
        {"category": "same_day_cake",        "en_q": "Is same-day cake delivery available?",               "en_a": "Same-day delivery depends on availability. Contact us early in the day.",                                                            "ml_q": "Same-day cake delivery undo?",                   "ml_a": "Availability anusari same-day delivery undaavum. Raaviley contact cheyyuka."},
        {"category": "fresh_bread",          "en_q": "Do you sell fresh bread daily?",                     "en_a": "Yes, fresh bread and buns are baked daily.",                                                                                        "ml_q": "Fresh bread daily undo?",                        "ml_a": "Athe, fresh bread, buns daily bake cheyyunnu."},
        {"category": "snacks",               "en_q": "What snacks do you sell?",                           "en_a": "Puffs, sandwiches, rolls, pizza, burgers, samosas, and other snacks are available.",                                               "ml_q": "Snacks enthokke undu?",                          "ml_a": "Puffs, sandwiches, rolls, pizza, burgers, samosas, matte snacks undu."},
        {"category": "veg_baked",            "en_q": "Do you have pure vegetarian baked items?",           "en_a": "Yes, we have a range of vegetarian baked goods including veg puffs, biscuits, and cakes.",                                          "ml_q": "Pure veg baked items undo?",                     "ml_a": "Athe, veg puffs, biscuits, cakes ulppedunna veg baked goods undu."},
        {"category": "sugar_free",           "en_q": "Do you have sugar-free or diabetic-friendly items?", "en_a": "Sugar-free and low-sugar options may be available on request.",                                                                    "ml_q": "Sugar free items undo?",                         "ml_a": "Sugar-free, low-sugar options request anusari undaavaam."},
        {"category": "gift_packing",         "en_q": "Do you offer gift packing for cakes?",               "en_a": "Yes, special gift packing and hampers are available.",                                                                              "ml_q": "Gift packing undo?",                             "ml_a": "Athe, special gift packing, hampers undu."},
        {"category": "birthday_packages",    "en_q": "Do you have birthday packages?",                     "en_a": "Yes, birthday packages with cakes, balloons, snacks, and decorations may be available.",                                           "ml_q": "Birthday packages undo?",                        "ml_a": "Athe, cakes, balloons, snacks, decorations ulpetta birthday packages undaavaam."},
        {"category": "product_freshness",    "en_q": "How fresh are your products?",                       "en_a": "All products are freshly prepared daily with quality ingredients.",                                                                  "ml_q": "Products fresh aano?",                           "ml_a": "Ella products daily quality ingredients upayogicch fresh prepare cheyyunnu."},
    ],

    # ── BEAUTY PARLOUR ───────────────────────────────────────────────────────
    "beauty_parlour": [
        {"category": "services_overview",    "en_q": "What services do you offer?",                        "en_a": "We offer haircuts, hair colour, hair spa, facial, skin care, waxing, threading, manicure, pedicure, bridal makeup, and more.",         "ml_q": "Enthu services undu?",                           "ml_a": "Haircuts, hair colour, hair spa, facial, skin care, waxing, threading, manicure, pedicure, bridal makeup ellam undu."},
        {"category": "appointment",          "en_q": "Do I need an appointment?",                          "en_a": "Appointments are recommended to avoid waiting. Walk-ins are also welcome based on availability.",                                   "ml_q": "Appointment venamoo?",                           "ml_a": "Wait avoid cheyyaan appointment recommend cheyyunnu. Availability anusari walk-in possible."},
        {"category": "bridal_makeup",        "en_q": "Do you offer bridal makeup packages?",               "en_a": "Yes, complete bridal makeup packages including hair styling, mehendi, and skincare are available.",                                 "ml_q": "Bridal makeup packages undo?",                   "ml_a": "Athe, hair styling, mehendi, skincare ulpetta complete bridal packages undu."},
        {"category": "hair_colour",          "en_q": "What hair colouring services are available?",        "en_a": "Global colour, highlights, balayage, ombre, henna, and root touch-up services are available.",                                    "ml_q": "Hair colouring services undo?",                  "ml_a": "Global colour, highlights, balayage, ombre, henna, root touch-up ellam undu."},
        {"category": "facial_types",         "en_q": "What facial treatments do you offer?",               "en_a": "We offer basic facial, gold facial, diamond facial, fruit facial, anti-ageing facial, and more.",                                  "ml_q": "Facial treatments undo?",                        "ml_a": "Basic facial, gold facial, diamond facial, fruit facial, anti-ageing facial ellam undu."},
        {"category": "waxing",               "en_q": "Do you provide waxing services?",                    "en_a": "Yes, full body waxing, half body, arms, legs, and face waxing are available.",                                                    "ml_q": "Waxing service undo?",                           "ml_a": "Athe, full body, half body, arms, legs, face waxing ellam undu."},
        {"category": "threading",            "en_q": "Do you offer threading services?",                   "en_a": "Yes, eyebrow and face threading is available.",                                                                                   "ml_q": "Threading undo?",                                "ml_a": "Athe, eyebrow, face threading undu."},
        {"category": "manicure_pedicure",    "en_q": "Do you offer manicure and pedicure?",                "en_a": "Yes, basic and premium manicure and pedicure services are available.",                                                            "ml_q": "Manicure pedicure undo?",                        "ml_a": "Athe, basic, premium manicure, pedicure services undu."},
        {"category": "hair_spa",             "en_q": "Do you offer hair spa and treatment?",               "en_a": "Yes, hair spa, keratin, smoothening, and deep conditioning treatments are available.",                                           "ml_q": "Hair spa, treatment undo?",                      "ml_a": "Athe, hair spa, keratin, smoothening, deep conditioning treatments undu."},
        {"category": "skin_care",            "en_q": "What skin care treatments are available?",           "en_a": "De-tan, bleach, clean-up, face pack, and skin brightening treatments are available.",                                           "ml_q": "Skin care treatments undo?",                     "ml_a": "De-tan, bleach, clean-up, face pack, skin brightening treatments undu."},
        {"category": "home_service",         "en_q": "Do you offer home service?",                         "en_a": "Yes, home beauty services are available in select areas. Contact us to book.",                                                    "ml_q": "Home service undo?",                             "ml_a": "Athe, select areas-il home beauty service undu. Book cheyyaan contact cheyyuka."},
        {"category": "male_services",        "en_q": "Do you have services for men?",                      "en_a": "Yes, we provide haircuts, facials, de-tan, and grooming services for men.",                                                      "ml_q": "Gents-inu services undo?",                       "ml_a": "Athe, haircuts, facials, de-tan, grooming services gents-inu undu."},
        {"category": "kids_hair",            "en_q": "Do you do kids haircuts?",                           "en_a": "Yes, kids haircuts are available.",                                                                                               "ml_q": "Kids haircut cheyyumo?",                         "ml_a": "Athe, kids haircut undu."},
        {"category": "products_used",        "en_q": "What brands of products do you use?",                "en_a": "We use reputed professional brands. Ask our staff for specific product details.",                                                 "ml_q": "Ethu brands use cheyyunnu?",                     "ml_a": "Reputed professional brands use cheyyunnu. Specific details staff-odu chodyikam."},
        {"category": "hygiene_tools",        "en_q": "Are your tools sterilised and hygienic?",            "en_a": "Yes, all tools and equipment are sterilised and hygienic to ensure client safety.",                                             "ml_q": "Tools hygenic aano?",                            "ml_a": "Athe, client safety-inu ella tools, equipment sterilise cheyyunnu."},
    ],

    # ── GYM ─────────────────────────────────────────────────────────────────
    "gym": [
        {"category": "membership_plans",     "en_q": "What membership plans are available?",               "en_a": "Monthly, quarterly, half-yearly, and annual membership plans are available.",                                                       "ml_q": "Membership plans enthokke undu?",                "ml_a": "Monthly, quarterly, half-yearly, annual membership plans undu."},
        {"category": "facilities",           "en_q": "What gym facilities are available?",                  "en_a": "We have cardio machines, free weights, strength equipment, yoga space, and changing rooms.",                                     "ml_q": "Gym facilities enthokke undu?",                  "ml_a": "Cardio machines, free weights, strength equipment, yoga space, changing rooms ellam undu."},
        {"category": "personal_trainer",     "en_q": "Is a personal trainer available?",                   "en_a": "Yes, certified personal trainers are available for customised workout plans.",                                                   "ml_q": "Personal trainer undo?",                         "ml_a": "Athe, certified personal trainers customised workout plans-inu undu."},
        {"category": "yoga_classes",         "en_q": "Do you have yoga classes?",                          "en_a": "Yes, yoga classes are conducted by qualified instructors.",                                                                      "ml_q": "Yoga classes undo?",                             "ml_a": "Athe, qualified instructors yoga classes nadatthunnu."},
        {"category": "zumba_classes",        "en_q": "Do you have Zumba or group fitness classes?",        "en_a": "Yes, Zumba, aerobics, and group fitness classes are available.",                                                               "ml_q": "Zumba allenkil group fitness classes undo?",     "ml_a": "Athe, Zumba, aerobics, group fitness classes undu."},
        {"category": "diet_plan",            "en_q": "Do you provide diet plans?",                         "en_a": "Yes, personalised diet plans are available through our fitness trainers or nutritionists.",                                    "ml_q": "Diet plan kittumoo?",                            "ml_a": "Athe, fitness trainers allenkil nutritionists vazhi personalised diet plan kittum."},
        {"category": "timing",               "en_q": "What are the gym timings?",                          "en_a": "Morning and evening batches are available. Contact us for exact timing schedules.",                                            "ml_q": "Gym timing enthaanu?",                           "ml_a": "Morning, evening batches undu. Exact timing ariyaan contact cheyyuka."},
        {"category": "trial_session",        "en_q": "Is a free trial session available?",                 "en_a": "Yes, a free trial session or demo class may be available for new members.",                                                    "ml_q": "Free trial session undo?",                       "ml_a": "Athe, new members-inu free trial session allenkil demo class undaavaam."},
        {"category": "ladies_gym",           "en_q": "Is there a separate section for ladies?",            "en_a": "Yes, a separate workout area or batch for ladies is available.",                                                               "ml_q": "Ladies-inu separate section undo?",              "ml_a": "Athe, ladies-inu separate workout area allenkil batch undu."},
        {"category": "locker_facility",      "en_q": "Are locker facilities available?",                   "en_a": "Yes, locker and changing room facilities are available.",                                                                       "ml_q": "Locker facility undo?",                          "ml_a": "Athe, locker, changing room facilities undu."},
        {"category": "steam_sauna",          "en_q": "Is steam or sauna available?",                       "en_a": "Steam and sauna facilities may be available depending on the gym setup.",                                                      "ml_q": "Steam allenkil sauna undo?",                     "ml_a": "Gym setup anusari steam, sauna facilities undaavaam."},
        {"category": "supplements",          "en_q": "Do you sell protein or fitness supplements?",        "en_a": "Yes, protein supplements, energy drinks, and fitness accessories may be available.",                                          "ml_q": "Protein allenkil supplements kittumoo?",         "ml_a": "Athe, protein supplements, energy drinks, fitness accessories undaavaam."},
        {"category": "online_membership",    "en_q": "Can I buy a membership online?",                     "en_a": "Yes, membership enquiries and registrations can be done via WhatsApp or phone.",                                             "ml_q": "Online membership edukkaamo?",                   "ml_a": "Athe, WhatsApp allenkil phone vazhi membership enquiry, registration cheyyam."},
        {"category": "kids_fitness",         "en_q": "Are there fitness classes for kids?",                "en_a": "Yes, kids fitness, karate, or sports training may be available.",                                                             "ml_q": "Kids-inu fitness classes undo?",                 "ml_a": "Athe, kids fitness, karate, sports training undaavaam."},
        {"category": "weight_loss",          "en_q": "Can you help with weight loss goals?",               "en_a": "Yes, our trainers design specific programs for weight loss, muscle gain, and overall fitness.",                              "ml_q": "Weight loss-inu help cheyyumoo?",                "ml_a": "Athe, trainers weight loss, muscle gain, overall fitness-inu specific programs design cheyyum."},
    ],

    # ── PHARMACY ─────────────────────────────────────────────────────────────
    "pharmacy": [
        {"category": "medicines_available",  "en_q": "What medicines are available?",                      "en_a": "Prescription medicines, OTC medicines, vitamins, supplements, baby care, personal care, and surgical supplies are available.",       "ml_q": "Ethu medicines kittum?",                         "ml_a": "Prescription, OTC medicines, vitamins, supplements, baby care, personal care, surgical supplies ellam undu."},
        {"category": "prescription",         "en_q": "Do I need a prescription to buy medicines?",         "en_a": "Prescription medicines require a valid doctor's prescription. OTC medicines can be bought without one.",                         "ml_q": "Medicines-inu prescription venamoo?",            "ml_a": "Prescription medicines-inu valid doctor prescription venam. OTC medicines prescription ille."},
        {"category": "generic_medicines",    "en_q": "Do you have generic medicines?",                     "en_a": "Yes, generic alternatives to branded medicines are available at lower prices.",                                                 "ml_q": "Generic medicines undo?",                        "ml_a": "Athe, branded medicines-nte generic alternatives low price-il undu."},
        {"category": "home_delivery_med",    "en_q": "Do you deliver medicines at home?",                  "en_a": "Yes, medicine home delivery is available. Share your prescription via WhatsApp for quick delivery.",                           "ml_q": "Medicine home delivery undo?",                   "ml_a": "Athe, medicine home delivery undu. Quick delivery-inu prescription WhatsApp cheyyuka."},
        {"category": "24hr_pharmacy",        "en_q": "Are you open 24 hours?",                             "en_a": "Our pharmacy hours vary. Contact us or check WhatsApp for current opening hours.",                                            "ml_q": "24 mani thurannu irikkunno?",                    "ml_a": "Pharmacy hours vary cheyyum. Current timings WhatsApp check cheyyuka."},
        {"category": "blood_pressure",       "en_q": "Do you check blood pressure or sugar levels?",       "en_a": "Yes, basic health checks like BP, sugar, and temperature testing may be available.",                                         "ml_q": "BP allenkil sugar check cheyyumo?",              "ml_a": "Athe, BP, sugar, temperature testing undaavaam."},
        {"category": "baby_products",        "en_q": "Do you have baby care products?",                    "en_a": "Yes, baby food, diapers, feeding bottles, baby care creams, and more are available.",                                       "ml_q": "Baby products undo?",                            "ml_a": "Athe, baby food, diapers, feeding bottles, baby care creams ellam undu."},
        {"category": "ayurvedic",            "en_q": "Do you sell Ayurvedic or herbal medicines?",         "en_a": "Yes, Ayurvedic and herbal medicine brands are available.",                                                                  "ml_q": "Ayurvedic medicines undo?",                      "ml_a": "Athe, Ayurvedic, herbal medicine brands undu."},
        {"category": "surgical_supplies",    "en_q": "Do you sell surgical and medical equipment?",        "en_a": "Yes, bandages, gloves, syringes, thermometers, BP monitors, and other medical supplies are available.",                     "ml_q": "Surgical supplies undo?",                        "ml_a": "Athe, bandages, gloves, syringes, thermometers, BP monitors, medical supplies ellam undu."},
        {"category": "medicine_expiry",      "en_q": "Do you check medicine expiry dates?",                "en_a": "Yes, all medicines are checked for expiry before dispensing.",                                                               "ml_q": "Medicine expiry check cheyyumo?",                "ml_a": "Athe, dispense cheyyunnathin munp ella medicines-inte expiry check cheyyunnu."},
        {"category": "cosmetics",            "en_q": "Do you sell cosmetics and personal care products?",  "en_a": "Yes, skincare, haircare, cosmetics, and personal hygiene products are available.",                                         "ml_q": "Cosmetics undo?",                                "ml_a": "Athe, skincare, haircare, cosmetics, personal hygiene products undu."},
        {"category": "pharmacist_advice",    "en_q": "Can I get pharmacist advice?",                       "en_a": "Yes, our qualified pharmacist can provide guidance on medicines and health queries.",                                       "ml_q": "Pharmacist advice kittumoo?",                    "ml_a": "Athe, qualified pharmacist medicine, health queries-il guidance nalkunnu."},
    ],

    # ── CLOTHING ─────────────────────────────────────────────────────────────
    "clothing": [
        {"category": "products_overview",    "en_q": "What clothing items are available?",                 "en_a": "We stock T-shirts, shirts, pants, jeans, ethnic wear, sarees, kurtas, western wear, sportswear, and accessories.",             "ml_q": "Enthu clothing items undu?",                     "ml_a": "T-shirts, shirts, pants, jeans, ethnic wear, sarees, kurtas, western wear, sportswear, accessories ellam undu."},
        {"category": "sizes",                "en_q": "What sizes are available?",                          "en_a": "We stock S, M, L, XL, XXL, and plus sizes for most items.",                                                                "ml_q": "Ethu sizes kittum?",                             "ml_a": "S, M, L, XL, XXL, plus sizes most items-inu kittum."},
        {"category": "ladies_wear",          "en_q": "Do you have ladies clothing?",                       "en_a": "Yes, we have sarees, kurtas, leggings, tops, dresses, ethnic wear, and accessories for women.",                           "ml_q": "Ladies wear undo?",                              "ml_a": "Athe, sarees, kurtas, leggings, tops, dresses, ethnic wear, accessories ladies-inu undu."},
        {"category": "kids_wear",            "en_q": "Do you have kids clothing?",                         "en_a": "Yes, we have a variety of clothing for boys, girls, infants, and toddlers.",                                             "ml_q": "Kids wear undo?",                                "ml_a": "Athe, boys, girls, infants, toddlers-inu variety clothing undu."},
        {"category": "mens_wear",            "en_q": "What men's wear is available?",                      "en_a": "Shirts, pants, jeans, formal wear, casual wear, ethnic wear, and sportswear for men are available.",                      "ml_q": "Gents wear enthokke undu?",                      "ml_a": "Shirts, pants, jeans, formal wear, casual wear, ethnic wear, sportswear gents-inu undu."},
        {"category": "ethnic_wear",          "en_q": "Do you have ethnic and traditional wear?",           "en_a": "Yes, sarees, kurtas, churidars, sherwanis, and traditional Kerala wear are available.",                                 "ml_q": "Ethnic wear undo?",                              "ml_a": "Athe, sarees, kurtas, churidars, sherwanis, traditional Kerala wear undu."},
        {"category": "uniforms",             "en_q": "Do you sell school or office uniforms?",             "en_a": "Yes, school uniforms and institutional bulk orders are accepted.",                                                        "ml_q": "Uniforms undo?",                                 "ml_a": "Athe, school uniforms, institutional bulk orders accept cheyyunnu."},
        {"category": "fitting",              "en_q": "Do you offer tailoring or alteration?",              "en_a": "Yes, basic alterations and fitting adjustments are available.",                                                          "ml_q": "Tailoring allenkil alteration cheyyumo?",        "ml_a": "Athe, basic alterations, fitting adjustments cheyyam."},
        {"category": "brand_collections",    "en_q": "Do you stock branded clothing?",                     "en_a": "Yes, we carry popular and branded clothing collections along with local brands.",                                        "ml_q": "Branded clothing undo?",                         "ml_a": "Athe, popular, branded, local brand clothing collections undu."},
        {"category": "exchange_policy",      "en_q": "What is your exchange/return policy?",               "en_a": "Exchanges are allowed within a specified period with original bill and tags intact.",                                    "ml_q": "Exchange policy enthaanu?",                      "ml_a": "Original bill, tags intact aayirunn exchange specified period-il allow cheyyum."},
        {"category": "new_arrivals",         "en_q": "Do you have new arrivals?",                          "en_a": "Yes, new collections arrive regularly. Check WhatsApp or visit the shop for latest arrivals.",                         "ml_q": "New arrivals undo?",                             "ml_a": "Athe, new collections regularly etthunnu. Latest ariyaan WhatsApp check cheyyuka."},
        {"category": "wedding_collection",   "en_q": "Do you have wedding or festive collections?",        "en_a": "Yes, special wedding, bridal, and festive collections are available for men and women.",                               "ml_q": "Wedding allenkil festive collection undo?",      "ml_a": "Athe, wedding, bridal, festive collections men, women-inu undu."},
    ],

    # ── ELECTRONICS ──────────────────────────────────────────────────────────
    "electronics": [
        {"category": "products_overview",    "en_q": "What electronics do you sell?",                      "en_a": "We sell mobiles, laptops, TVs, home appliances, audio devices, cameras, and accessories.",                                   "ml_q": "Enthu electronics undu?",                        "ml_a": "Mobiles, laptops, TVs, home appliances, audio, cameras, accessories ellam undu."},
        {"category": "mobile_phones",        "en_q": "Do you sell mobile phones?",                         "en_a": "Yes, we stock smartphones from all major brands including Samsung, Apple, Realme, Redmi, and more.",                       "ml_q": "Mobile phones undo?",                            "ml_a": "Athe, Samsung, Apple, Realme, Redmi ulppedunna all major brands undu."},
        {"category": "laptop",               "en_q": "Do you sell laptops?",                               "en_a": "Yes, laptops from HP, Dell, Lenovo, Apple, Asus, and other brands are available.",                                      "ml_q": "Laptops undo?",                                  "ml_a": "Athe, HP, Dell, Lenovo, Apple, Asus, matte brands laptops undu."},
        {"category": "warranty",             "en_q": "Do products come with warranty?",                    "en_a": "Yes, all products come with manufacturer warranty. Extended warranty may also be available.",                           "ml_q": "Warranty undo?",                                 "ml_a": "Athe, manufacturer warranty undu. Extended warranty undaavaam."},
        {"category": "repair_service",       "en_q": "Do you offer repair services?",                      "en_a": "Yes, mobile, laptop, and appliance repair services are available.",                                                    "ml_q": "Repair service undo?",                           "ml_a": "Athe, mobile, laptop, appliance repair services undu."},
        {"category": "accessories",          "en_q": "Do you sell mobile and laptop accessories?",         "en_a": "Yes, cases, chargers, earphones, screen guards, keyboards, and other accessories are available.",                      "ml_q": "Accessories undo?",                              "ml_a": "Athe, cases, chargers, earphones, screen guards, keyboards, matte accessories undu."},
        {"category": "emi_options",          "en_q": "Is EMI available?",                                  "en_a": "Yes, no-cost and low-cost EMI options are available on selected products and cards.",                                 "ml_q": "EMI option undo?",                               "ml_a": "Athe, selected products, cards-il no-cost, low-cost EMI undu."},
        {"category": "exchange_offer",       "en_q": "Do you have exchange offers?",                       "en_a": "Yes, exchange your old device and get discounts on new purchases.",                                                   "ml_q": "Exchange offer undo?",                           "ml_a": "Athe, old device exchange cheyth new purchase-il discount kittum."},
        {"category": "home_delivery_elec",   "en_q": "Do you deliver electronics at home?",                "en_a": "Yes, home delivery and installation services are available for large appliances.",                                    "ml_q": "Home delivery undo?",                            "ml_a": "Athe, large appliances-inu home delivery, installation service undu."},
        {"category": "demo",                 "en_q": "Can I get a product demo before buying?",            "en_a": "Yes, product demonstrations are available at our store.",                                                            "ml_q": "Buying-inu mumpe demo kittumoo?",                "ml_a": "Athe, store-il product demo available aanu."},
    ],

    # ── JEWELLERY ────────────────────────────────────────────────────────────
    "jewellery": [
        {"category": "collections",          "en_q": "What jewellery collections are available?",          "en_a": "We have gold, silver, diamond, platinum jewellery, necklaces, rings, bangles, earrings, and bridal sets.",                 "ml_q": "Ethu jewellery undu?",                           "ml_a": "Gold, silver, diamond, platinum, necklaces, rings, bangles, earrings, bridal sets ellam undu."},
        {"category": "gold_rate",            "en_q": "What is today's gold rate?",                         "en_a": "Gold rates change daily. Contact us or visit the shop for today's latest gold rate.",                                  "ml_q": "Innu gold rate ethreyaanu?",                     "ml_a": "Gold rate daily change cheyyum. Latest rate ariyaan contact cheyyuka."},
        {"category": "hallmark",             "en_q": "Is your jewellery hallmarked?",                      "en_a": "Yes, all our gold jewellery is BIS hallmarked for assured quality.",                                                  "ml_q": "Jewellery hallmark cheyyitundo?",                "ml_a": "Athe, ella gold jewellery BIS hallmark cheyyitundu."},
        {"category": "custom_design",        "en_q": "Can I get custom jewellery designed?",               "en_a": "Yes, custom jewellery can be designed as per your requirements.",                                                     "ml_q": "Custom jewellery design cheyyumo?",              "ml_a": "Athe, ningalude requirements anusari custom design cheyyam."},
        {"category": "repair_service",       "en_q": "Do you offer jewellery repair?",                     "en_a": "Yes, jewellery cleaning, polishing, resizing, and repair services are available.",                                  "ml_q": "Jewellery repair undo?",                         "ml_a": "Athe, cleaning, polishing, resizing, repair services undu."},
        {"category": "exchange",             "en_q": "Can I exchange old jewellery?",                      "en_a": "Yes, old gold and silver jewellery exchange is accepted with fair valuation.",                                      "ml_q": "Pala jewellery exchange cheyyaamo?",             "ml_a": "Athe, pala gold, silver jewellery fair valuation-il exchange cheyyam."},
        {"category": "bridal_jewellery",     "en_q": "Do you have bridal jewellery sets?",                 "en_a": "Yes, complete bridal jewellery sets and rental options may be available.",                                         "ml_q": "Bridal jewellery sets undo?",                    "ml_a": "Athe, complete bridal sets, rental options undaavaam."},
        {"category": "emi_gold",             "en_q": "Is gold purchase available on EMI?",                 "en_a": "Yes, gold EMI schemes and chit fund options may be available.",                                                    "ml_q": "Gold EMI ayi vangaamo?",                         "ml_a": "Athe, gold EMI schemes, chit fund options undaavaam."},
        {"category": "certified",            "en_q": "Are diamonds and gemstones certified?",              "en_a": "Yes, diamonds come with GIA or IGI certification.",                                                                "ml_q": "Diamonds certified aano?",                       "ml_a": "Athe, diamonds GIA allenkil IGI certification undu."},
    ],

    # ── OPTICAL ──────────────────────────────────────────────────────────────
    "optical": [
        {"category": "products",             "en_q": "What optical products are available?",               "en_a": "Eyeglasses, sunglasses, contact lenses, sports eyewear, and kids eyewear are available.",                               "ml_q": "Enthu optical products undu?",                   "ml_a": "Eyeglasses, sunglasses, contact lenses, sports eyewear, kids eyewear undu."},
        {"category": "eye_test",             "en_q": "Do you offer eye testing?",                          "en_a": "Yes, free or nominal eye testing is available at our store.",                                                        "ml_q": "Eye test cheyyumo?",                             "ml_a": "Athe, free allenkil nominal charge-il eye test cheyyam."},
        {"category": "frame_brands",         "en_q": "What spectacle frame brands are available?",         "en_a": "We stock Rayban, Fastrack, Titan, Lenskart, and other premium brands.",                                           "ml_q": "Ethu frame brands undu?",                        "ml_a": "Rayban, Fastrack, Titan, Lenskart, matte premium brands undu."},
        {"category": "lens_types",           "en_q": "What lens types are available?",                     "en_a": "Single vision, bifocal, progressive, anti-glare, blue-light blocking, and photochromic lenses are available.",       "ml_q": "Ethu lens types undu?",                          "ml_a": "Single vision, bifocal, progressive, anti-glare, blue-light blocking, photochromic lenses undu."},
        {"category": "contact_lenses",       "en_q": "Do you sell contact lenses?",                        "en_a": "Yes, daily, monthly, and yearly contact lenses from major brands are available.",                                 "ml_q": "Contact lenses undo?",                           "ml_a": "Athe, daily, monthly, yearly contact lenses major brands-il undu."},
        {"category": "kids_glasses",         "en_q": "Do you have glasses for children?",                  "en_a": "Yes, kids eyewear with durable frames and lenses are available.",                                                 "ml_q": "Kids glasses undo?",                             "ml_a": "Athe, durable frames, lenses ulpetta kids eyewear undu."},
        {"category": "delivery_time",        "en_q": "How long does it take to get spectacles ready?",     "en_a": "Ready-made spectacles are available instantly. Custom prescription glasses may take 1-3 days.",                    "ml_q": "Spectacles ethra time-il ready aakum?",          "ml_a": "Ready-made instant kittum. Custom prescription glasses 1-3 days edukum."},
        {"category": "repair",               "en_q": "Do you repair spectacles?",                          "en_a": "Yes, frame and lens repair, replacement, and adjustments are available.",                                        "ml_q": "Spectacles repair cheyyumo?",                    "ml_a": "Athe, frame, lens repair, replacement, adjustments cheyyam."},
    ],

    # ── HOTEL ─────────────────────────────────────────────────────────────────
    "hotel": [
        {"category": "room_types",           "en_q": "What types of rooms are available?",                 "en_a": "Standard, Deluxe, Suite, and Family rooms are available.",                                                           "ml_q": "Ethu room types undu?",                          "ml_a": "Standard, Deluxe, Suite, Family rooms undu."},
        {"category": "room_booking",         "en_q": "How can I book a room?",                             "en_a": "Rooms can be booked via WhatsApp, phone, website, or online booking platforms.",                                  "ml_q": "Room engane book cheyyam?",                      "ml_a": "WhatsApp, phone, website, online platforms vazhi book cheyyam."},
        {"category": "check_in_out",         "en_q": "What are the check-in and check-out times?",         "en_a": "Standard check-in is 12 PM and check-out is 11 AM. Early check-in/late check-out may be arranged.",              "ml_q": "Check-in check-out time enthaanu?",              "ml_a": "Check-in 12 PM, check-out 11 AM. Early/late arrangement cheyyam."},
        {"category": "amenities",            "en_q": "What amenities are included?",                       "en_a": "AC, TV, WiFi, hot water, room service, parking, and housekeeping are included.",                               "ml_q": "Enthu amenities undu?",                          "ml_a": "AC, TV, WiFi, hot water, room service, parking, housekeeping ellam undu."},
        {"category": "restaurant_hotel",     "en_q": "Is there an in-house restaurant?",                   "en_a": "Yes, our restaurant serves breakfast, lunch, dinner, and snacks.",                                             "ml_q": "Restaurant undo?",                               "ml_a": "Athe, breakfast, lunch, dinner, snacks serve cheyyunna restaurant undu."},
        {"category": "conference_hall",      "en_q": "Is a conference or event hall available?",           "en_a": "Yes, conference and banquet halls for meetings, events, and functions are available.",                          "ml_q": "Conference hall undo?",                          "ml_a": "Athe, meetings, events, functions-inu conference, banquet halls undu."},
        {"category": "cancellation",         "en_q": "What is the cancellation policy?",                   "en_a": "Cancellation policies vary by booking type. Contact us for details.",                                          "ml_q": "Cancellation policy enthaanu?",                  "ml_a": "Booking type anusari vary cheyyum. Details ariyaan contact cheyyuka."},
        {"category": "couple_rooms",         "en_q": "Are rooms available for couples?",                   "en_a": "Yes, couple rooms are available. Valid ID proof required at check-in.",                                       "ml_q": "Couple rooms undo?",                             "ml_a": "Athe, couple rooms undu. Check-in-il valid ID venam."},
        {"category": "airport_transfer",     "en_q": "Do you offer airport or station pickup?",            "en_a": "Airport and station pickup/drop services may be available. Contact us in advance.",                          "ml_q": "Airport pickup undo?",                           "ml_a": "Airport, station pickup/drop undaavaam. Advance ayi contact cheyyuka."},
    ],

    # ── SUPERMARKET ──────────────────────────────────────────────────────────
    "supermarket": [
        {"category": "products",             "en_q": "What products are available?",                       "en_a": "Groceries, vegetables, fruits, dairy, snacks, beverages, personal care, and household items are available.",           "ml_q": "Enthokke products undu?",                        "ml_a": "Groceries, vegetables, fruits, dairy, snacks, beverages, personal care, household items ellam undu."},
        {"category": "fresh_produce",        "en_q": "Do you sell fresh vegetables and fruits?",           "en_a": "Yes, fresh vegetables and seasonal fruits are available daily.",                                                  "ml_q": "Fresh vegetables, fruits undo?",                 "ml_a": "Athe, fresh vegetables, seasonal fruits daily undu."},
        {"category": "dairy",                "en_q": "Do you have dairy products?",                        "en_a": "Yes, milk, curd, butter, cheese, paneer, and other dairy products are available.",                            "ml_q": "Dairy products undo?",                           "ml_a": "Athe, milk, curd, butter, cheese, paneer, matte dairy products undu."},
        {"category": "home_delivery_sm",     "en_q": "Do you deliver groceries at home?",                  "en_a": "Yes, home delivery of groceries is available via WhatsApp or phone order.",                                   "ml_q": "Groceries home delivery undo?",                  "ml_a": "Athe, WhatsApp allenkil phone order vazhi grocery home delivery undu."},
        {"category": "organic",              "en_q": "Do you sell organic products?",                      "en_a": "Yes, organic groceries and natural products may be available.",                                              "ml_q": "Organic products undo?",                         "ml_a": "Athe, organic groceries, natural products undaavaam."},
        {"category": "loyalty_card",         "en_q": "Do you have a loyalty or rewards program?",          "en_a": "Yes, loyalty cards and reward points may be available for regular customers.",                                "ml_q": "Loyalty card undo?",                             "ml_a": "Athe, regular customers-inu loyalty cards, reward points undaavaam."},
    ],

    # ── SCHOOL ───────────────────────────────────────────────────────────────
    "school": [
        {"category": "classes",              "en_q": "What classes or grades do you offer?",               "en_a": "We offer classes from KG to Class 12, including primary, secondary, and higher secondary levels.",                   "ml_q": "Ethu classes undu?",                             "ml_a": "KG muthal Class 12 vare, primary, secondary, higher secondary levels undu."},
        {"category": "admission",            "en_q": "How do I apply for admission?",                      "en_a": "Admission applications can be submitted online or at the school office during open enrollment.",                "ml_q": "Admission engane cheyyam?",                      "ml_a": "Online allenkil school office-il open enrollment-il application submit cheyyam."},
        {"category": "fees",                 "en_q": "What are the school fees?",                          "en_a": "Fees vary by class and program. Contact the school office for the detailed fee structure.",                   "ml_q": "School fees ethreyaanu?",                        "ml_a": "Class, program anusari fees vary cheyyum. Detailed structure ariyaan office contact cheyyuka."},
        {"category": "syllabus",             "en_q": "Which board or syllabus do you follow?",             "en_a": "We follow CBSE / ICSE / State Board syllabus. Contact us for current affiliation details.",                   "ml_q": "Ethu syllabus follow cheyyunnu?",                "ml_a": "CBSE / ICSE / State Board syllabus follow cheyyunnu. Current details contact cheyyuka."},
        {"category": "transport",            "en_q": "Do you provide school bus service?",                 "en_a": "Yes, school bus service is available for major routes.",                                                      "ml_q": "School bus undo?",                               "ml_a": "Athe, major routes-il school bus undu."},
        {"category": "extracurricular",      "en_q": "What extracurricular activities are available?",     "en_a": "Sports, music, dance, arts, science club, and other activities are available.",                            "ml_q": "Extracurricular activities undo?",               "ml_a": "Sports, music, dance, arts, science club, matte activities undu."},
        {"category": "uniform",              "en_q": "Is there a school uniform?",                         "en_a": "Yes, school uniform is mandatory. Details will be provided at admission.",                                  "ml_q": "School uniform undo?",                           "ml_a": "Athe, uniform mandatory aanu. Admission-il details kittum."},
        {"category": "online_classes",       "en_q": "Do you offer online classes?",                       "en_a": "Yes, online classes and digital learning resources are available.",                                        "ml_q": "Online classes undo?",                           "ml_a": "Athe, online classes, digital learning resources undu."},
    ],

    # ── TRAVEL AGENCY ────────────────────────────────────────────────────────
    "travel_agency": [
        {"category": "packages",             "en_q": "What tour packages do you offer?",                   "en_a": "Kerala tours, India tours, international packages, honeymoon tours, group tours, and custom packages are available.",  "ml_q": "Tour packages enthokke undu?",                   "ml_a": "Kerala tours, India tours, international, honeymoon, group tours, custom packages ellam undu."},
        {"category": "honeymoon",            "en_q": "Do you have honeymoon packages?",                    "en_a": "Yes, customized honeymoon packages for Kerala, India, and international destinations are available.",              "ml_q": "Honeymoon packages undo?",                       "ml_a": "Athe, Kerala, India, international destinations-inu customized honeymoon packages undu."},
        {"category": "visa",                 "en_q": "Do you assist with visa processing?",                "en_a": "Yes, visa assistance and documentation support is available for international travel.",                          "ml_q": "Visa help kittumoo?",                            "ml_a": "Athe, international travel-inu visa, documentation support undu."},
        {"category": "flight_booking",       "en_q": "Do you book flights?",                              "en_a": "Yes, domestic and international flight booking services are available.",                                        "ml_q": "Flight booking cheyyumo?",                       "ml_a": "Athe, domestic, international flight booking cheyyam."},
        {"category": "hotel_booking",        "en_q": "Do you provide hotel booking?",                     "en_a": "Yes, hotel and resort bookings are arranged as part of tour packages or separately.",                        "ml_q": "Hotel booking cheyyumo?",                        "ml_a": "Athe, tour packages-il allenkil separately hotel, resort booking undu."},
        {"category": "group_tours",          "en_q": "Do you arrange group tours?",                       "en_a": "Yes, group tours for families, offices, and institutions are arranged.",                                    "ml_q": "Group tours arrange cheyyumo?",                  "ml_a": "Athe, families, offices, institutions-inu group tours arrange cheyyam."},
        {"category": "cancellation_tour",    "en_q": "What is the cancellation policy for tours?",        "en_a": "Cancellation charges depend on booking type and timing. Contact us for details.",                          "ml_q": "Tour cancellation policy enthaanu?",             "ml_a": "Booking type, timing anusari cancellation charges. Details ariyaan contact cheyyuka."},
    ],

    # ── LAW FIRM ──────────────────────────────────────────────────────────────
    "law_firm": [
        {"category": "services",             "en_q": "What legal services do you provide?",                "en_a": "We handle civil, criminal, family, property, corporate, labour law cases and legal consultation.",                 "ml_q": "Enthu legal services undu?",                     "ml_a": "Civil, criminal, family, property, corporate, labour law cases, consultation ellam cheyyunnu."},
        {"category": "consultation",         "en_q": "How do I book a legal consultation?",                "en_a": "Consultations can be scheduled via phone, WhatsApp, or office visit.",                                         "ml_q": "Consultation engane book cheyyam?",              "ml_a": "Phone, WhatsApp allenkil office visit vazhi consultation book cheyyam."},
        {"category": "fees",                 "en_q": "What are your legal fees?",                          "en_a": "Fees depend on case type and complexity. Contact us for a fee estimate.",                                    "ml_q": "Legal fees ethreyaanu?",                         "ml_a": "Case type, complexity anusari fees. Estimate ariyaan contact cheyyuka."},
        {"category": "property_law",         "en_q": "Do you handle property disputes?",                   "en_a": "Yes, property purchase, disputes, registration, and documentation are handled.",                            "ml_q": "Property cases handle cheyyumo?",                "ml_a": "Athe, property purchase, disputes, registration, documentation cheyyunnu."},
        {"category": "family_law",           "en_q": "Do you handle family law matters?",                  "en_a": "Yes, divorce, child custody, maintenance, and family disputes are handled.",                               "ml_q": "Family law cases handle cheyyumo?",              "ml_a": "Athe, divorce, child custody, maintenance, family disputes cheyyunnu."},
        {"category": "corporate",            "en_q": "Do you handle corporate legal matters?",             "en_a": "Yes, company registration, contracts, compliance, and corporate disputes are handled.",                    "ml_q": "Corporate legal matters cheyyumo?",              "ml_a": "Athe, company registration, contracts, compliance, corporate disputes cheyyunnu."},
        {"category": "confidentiality",      "en_q": "Is client information kept confidential?",           "en_a": "Yes, strict client confidentiality is maintained as per legal ethics.",                                   "ml_q": "Client information confidential aano?",          "ml_a": "Athe, legal ethics anusari strict confidentiality maintain cheyyunnu."},
    ],

    # ── CA FIRM ───────────────────────────────────────────────────────────────
    "ca_firm": [
        {"category": "services",             "en_q": "What accounting services do you provide?",           "en_a": "We offer tax filing, audit, GST, accounting, company registration, payroll, and financial consultation.",           "ml_q": "Enthu services undu?",                           "ml_a": "Tax filing, audit, GST, accounting, company registration, payroll, financial consultation ellam undu."},
        {"category": "gst",                  "en_q": "Do you handle GST registration and filing?",         "en_a": "Yes, GST registration, returns, and compliance are handled.",                                                  "ml_q": "GST registration handle cheyyumo?",              "ml_a": "Athe, GST registration, returns, compliance cheyyunnu."},
        {"category": "income_tax",           "en_q": "Do you file income tax returns?",                    "en_a": "Yes, individual and corporate income tax return filing is done.",                                            "ml_q": "Income tax filing cheyyumo?",                    "ml_a": "Athe, individual, corporate income tax returns file cheyyunnu."},
        {"category": "company_reg",          "en_q": "Do you handle company registration?",                "en_a": "Yes, private limited, partnership, LLP, and sole proprietorship registrations are done.",                   "ml_q": "Company registration cheyyumo?",                 "ml_a": "Athe, private limited, partnership, LLP, sole proprietorship registrations cheyyunnu."},
        {"category": "audit",                "en_q": "Do you conduct audits?",                             "en_a": "Yes, statutory, internal, and tax audits are conducted.",                                                  "ml_q": "Audit cheyyumo?",                                "ml_a": "Athe, statutory, internal, tax audits cheyyunnu."},
        {"category": "payroll",              "en_q": "Do you manage payroll?",                             "en_a": "Yes, payroll processing, PF, ESI, and salary management are handled.",                                   "ml_q": "Payroll manage cheyyumo?",                       "ml_a": "Athe, payroll processing, PF, ESI, salary management cheyyunnu."},
        {"category": "fees",                 "en_q": "What are your service fees?",                        "en_a": "Fees depend on the type and scope of service. Contact us for a quote.",                                 "ml_q": "Service fees ethreyaanu?",                       "ml_a": "Service type, scope anusari fees. Quote ariyaan contact cheyyuka."},
    ],

    # ── REAL ESTATE ───────────────────────────────────────────────────────────
    "real_estate": [
        {"category": "properties",           "en_q": "What properties are available?",                     "en_a": "Apartments, villas, plots, commercial spaces, and rental properties are available.",                             "ml_q": "Enthu properties undu?",                         "ml_a": "Apartments, villas, plots, commercial spaces, rental properties undu."},
        {"category": "site_visit",           "en_q": "Can I schedule a site visit?",                       "en_a": "Yes, site visits can be arranged at your convenience.",                                                      "ml_q": "Site visit arrange cheyyaamo?",                  "ml_a": "Athe, ningalude convenience anusari site visit arrange cheyyam."},
        {"category": "loan_assistance",      "en_q": "Do you assist with home loans?",                     "en_a": "Yes, home loan assistance and bank tie-ups are available.",                                               "ml_q": "Home loan help kittumoo?",                       "ml_a": "Athe, home loan assistance, bank tie-ups undu."},
        {"category": "legal_docs",           "en_q": "Do you help with legal documentation?",              "en_a": "Yes, property registration, legal verification, and documentation support is available.",                "ml_q": "Legal documentation help kittumoo?",             "ml_a": "Athe, property registration, legal verification, documentation support undu."},
        {"category": "rental",               "en_q": "Do you list rental properties?",                    "en_a": "Yes, residential and commercial rental listings are available.",                                        "ml_q": "Rental properties undo?",                        "ml_a": "Athe, residential, commercial rental listings undu."},
        {"category": "new_projects",         "en_q": "Do you have new housing projects?",                 "en_a": "Yes, upcoming residential and commercial projects are available. Contact us for details.",              "ml_q": "New projects undo?",                             "ml_a": "Athe, upcoming residential, commercial projects undu. Details ariyaan contact cheyyuka."},
    ],

    # ── DENTAL CLINIC ─────────────────────────────────────────────────────────
    "dental_clinic": [
        {"category": "services",             "en_q": "What dental services are available?",                "en_a": "Teeth cleaning, filling, extraction, braces, root canal, dental implants, whitening, and more are available.",     "ml_q": "Enthu dental services undu?",                    "ml_a": "Teeth cleaning, filling, extraction, braces, root canal, implants, whitening ellam undu."},
        {"category": "appointment",          "en_q": "How do I book a dental appointment?",                "en_a": "Appointments can be booked via phone, WhatsApp, or walk-in.",                                                 "ml_q": "Appointment engane book cheyyam?",               "ml_a": "Phone, WhatsApp allenkil walk-in vazhi appointment book cheyyam."},
        {"category": "braces",               "en_q": "Do you offer dental braces?",                       "en_a": "Yes, metal, ceramic, and invisible braces are available.",                                                  "ml_q": "Braces undo?",                                   "ml_a": "Athe, metal, ceramic, invisible braces undu."},
        {"category": "root_canal",           "en_q": "Do you perform root canal treatment?",              "en_a": "Yes, root canal treatments are performed by experienced dentists.",                                        "ml_q": "Root canal treatment cheyyumo?",                 "ml_a": "Athe, experienced dentists root canal treatments cheyyunnu."},
        {"category": "whitening",            "en_q": "Do you offer teeth whitening?",                     "en_a": "Yes, professional teeth whitening treatments are available.",                                            "ml_q": "Teeth whitening undo?",                          "ml_a": "Athe, professional teeth whitening treatments undu."},
        {"category": "kids_dental",          "en_q": "Do you treat children?",                            "en_a": "Yes, paediatric dental services for children are available.",                                          "ml_q": "Kuttikalkku dental treatment undo?",             "ml_a": "Athe, children-inu paediatric dental services undu."},
        {"category": "emergency",            "en_q": "Do you handle dental emergencies?",                 "en_a": "Yes, emergency dental care is available. Call us immediately for urgent cases.",                       "ml_q": "Emergency dental care undo?",                    "ml_a": "Athe, emergency dental care undu. Urgent cases-inu immediately call cheyyuka."},
        {"category": "implants",             "en_q": "Do you offer dental implants?",                     "en_a": "Yes, dental implants and prosthetics are available.",                                                 "ml_q": "Dental implants undo?",                          "ml_a": "Athe, dental implants, prosthetics undu."},
        {"category": "insurance",            "en_q": "Do you accept dental insurance?",                   "en_a": "Some insurance plans may be accepted. Contact us to check your coverage.",                          "ml_q": "Insurance accept cheyyumo?",                     "ml_a": "Chila insurance plans accept cheyyum. Coverage check cheyyaan contact cheyyuka."},
    ],

    # ── SALON / BARBER ────────────────────────────────────────────────────────
    "salon": [
        {"category": "services",             "en_q": "What services do you offer?",                        "en_a": "Haircuts, hair colour, beard trimming, shaving, facial, hair spa, and styling services are available.",            "ml_q": "Enthu services undu?",                           "ml_a": "Haircuts, hair colour, beard trimming, shaving, facial, hair spa, styling undu."},
        {"category": "haircut",              "en_q": "What types of haircuts are available?",              "en_a": "Classic cuts, fades, undercuts, modern styles, and kids haircuts are available.",                            "ml_q": "Ethu haircut styles undu?",                      "ml_a": "Classic cuts, fades, undercuts, modern styles, kids haircuts undu."},
        {"category": "beard",                "en_q": "Do you offer beard trimming and styling?",           "en_a": "Yes, beard trimming, shaping, shaving, and beard colouring are available.",                                  "ml_q": "Beard trimming undo?",                           "ml_a": "Athe, beard trimming, shaping, shaving, beard colouring undu."},
        {"category": "hair_colour",          "en_q": "Do you offer hair colouring?",                      "en_a": "Yes, global colour, highlights, and creative colouring services are available.",                          "ml_q": "Hair colour cheyyumo?",                          "ml_a": "Athe, global colour, highlights, creative colouring undu."},
        {"category": "facial",               "en_q": "Do you offer facials for men?",                     "en_a": "Yes, men's facials, de-tan, and skin care treatments are available.",                                   "ml_q": "Gents facial undo?",                             "ml_a": "Athe, gents facial, de-tan, skin care treatments undu."},
        {"category": "appointment",          "en_q": "Do I need an appointment?",                         "en_a": "Walk-ins are welcome. For busy times, booking in advance is recommended.",                             "ml_q": "Appointment venamoo?",                           "ml_a": "Walk-in ok. Busy time-il advance booking recommend cheyyunnu."},
        {"category": "products",             "en_q": "What hair products do you use?",                    "en_a": "We use professional brands for all treatments and styling.",                                         "ml_q": "Ethu products use cheyyunnu?",                   "ml_a": "Professional brands use cheyyunnu."},
    ],

    # ── CAFE / COFFEE SHOP ────────────────────────────────────────────────────
    "cafe": [
        {"category": "menu",                 "en_q": "What is on your menu?",                              "en_a": "Coffee, tea, cold beverages, shakes, sandwiches, wraps, cakes, and light snacks are available.",                 "ml_q": "Menu-il enthokke undu?",                         "ml_a": "Coffee, tea, cold beverages, shakes, sandwiches, wraps, cakes, snacks ellam undu."},
        {"category": "wifi",                 "en_q": "Do you have WiFi?",                                  "en_a": "Yes, free WiFi is available for customers.",                                                                   "ml_q": "WiFi undo?",                                     "ml_a": "Athe, customers-inu free WiFi undu."},
        {"category": "seating",              "en_q": "Do you have indoor and outdoor seating?",            "en_a": "Yes, indoor and outdoor seating options are available.",                                                      "ml_q": "Indoor outdoor seating undo?",                   "ml_a": "Athe, indoor, outdoor seating undu."},
        {"category": "special_coffee",       "en_q": "What coffee specialties do you offer?",             "en_a": "Espresso, cappuccino, latte, cold brew, filter coffee, and seasonal specialties are available.",              "ml_q": "Ethu coffee specialties undu?",                  "ml_a": "Espresso, cappuccino, latte, cold brew, filter coffee, seasonal specialties undu."},
        {"category": "vegan_options",        "en_q": "Do you have vegan or dairy-free options?",          "en_a": "Yes, plant-based milk alternatives and vegan snacks may be available.",                                    "ml_q": "Vegan options undo?",                            "ml_a": "Athe, plant-based milk, vegan snacks undaavaam."},
        {"category": "takeaway_cafe",        "en_q": "Do you offer takeaway?",                            "en_a": "Yes, takeaway cups and parcel packing are available.",                                                     "ml_q": "Takeaway undo?",                                 "ml_a": "Athe, takeaway cups, parcel packing undu."},
        {"category": "group_seating",        "en_q": "Can you accommodate large groups?",                 "en_a": "Yes, group seating arrangements can be made for events and gatherings.",                                 "ml_q": "Group seating undo?",                            "ml_a": "Athe, events, gatherings-inu group seating arrange cheyyam."},
    ],

    # ── PET SHOP ──────────────────────────────────────────────────────────────
    "pet_shop": [
        {"category": "animals",              "en_q": "What pets are available?",                           "en_a": "Dogs, cats, birds, fish, rabbits, hamsters, and other small animals may be available.",                        "ml_q": "Ethu pets undu?",                                "ml_a": "Dogs, cats, birds, fish, rabbits, hamsters, matte small animals undu."},
        {"category": "pet_food",             "en_q": "Do you sell pet food?",                              "en_a": "Yes, dog food, cat food, bird feed, fish food, and specialty pet nutrition are available.",                   "ml_q": "Pet food undo?",                                 "ml_a": "Athe, dog food, cat food, bird feed, fish food, specialty nutrition undu."},
        {"category": "grooming",             "en_q": "Do you offer pet grooming services?",               "en_a": "Yes, dog bathing, haircut, nail trimming, and grooming services are available.",                          "ml_q": "Pet grooming service undo?",                     "ml_a": "Athe, dog bathing, haircut, nail trimming, grooming undu."},
        {"category": "vet",                  "en_q": "Is a veterinary doctor available?",                 "en_a": "Yes, veterinary consultations and basic health checks are available.",                                   "ml_q": "Veterinary doctor undo?",                        "ml_a": "Athe, vet consultation, basic health check undu."},
        {"category": "accessories",          "en_q": "Do you sell pet accessories?",                      "en_a": "Yes, cages, leashes, collars, toys, beds, and accessories for all pets are available.",                 "ml_q": "Pet accessories undo?",                          "ml_a": "Athe, cages, leashes, collars, toys, beds, accessories undu."},
        {"category": "vaccination",          "en_q": "Do you provide pet vaccinations?",                  "en_a": "Yes, pet vaccination services are available.",                                                          "ml_q": "Pet vaccination undo?",                          "ml_a": "Athe, pet vaccination services undu."},
        {"category": "boarding",             "en_q": "Do you offer pet boarding?",                        "en_a": "Yes, pet boarding and day care services may be available.",                                          "ml_q": "Pet boarding undo?",                             "ml_a": "Athe, pet boarding, day care services undaavaam."},
    ],

    # ── DRIVING SCHOOL ───────────────────────────────────────────────────────
    "driving_school": [
        {"category": "courses",              "en_q": "What driving courses are available?",                "en_a": "2-wheeler, 4-wheeler, heavy vehicle, and defensive driving courses are available.",                           "ml_q": "Ethu driving courses undu?",                     "ml_a": "2-wheeler, 4-wheeler, heavy vehicle, defensive driving courses undu."},
        {"category": "licence",              "en_q": "Do you help with driving licence application?",      "en_a": "Yes, learner's and permanent licence application assistance is provided.",                                  "ml_q": "Driving licence help kittumoo?",                 "ml_a": "Athe, learner's, permanent licence application help cheyyunnu."},
        {"category": "duration",             "en_q": "How long is the driving course?",                   "en_a": "Course duration typically ranges from 14 to 30 days depending on the programme.",                        "ml_q": "Course ethra days?",                             "ml_a": "Programme anusari 14 muthal 30 divas course undaavum."},
        {"category": "pickup",               "en_q": "Do you offer doorstep training?",                   "en_a": "Yes, home pickup for training sessions may be available in select areas.",                            "ml_q": "Doorstep training undo?",                        "ml_a": "Athe, select areas-il home pickup undaavaam."},
        {"category": "ladies_training",      "en_q": "Is there special training for ladies?",             "en_a": "Yes, special batches and female instructors are available for ladies.",                              "ml_q": "Ladies-inu special training undo?",              "ml_a": "Athe, ladies-inu special batch, female instructors undu."},
    ],

    # ── FURNITURE SHOP ───────────────────────────────────────────────────────
    "furniture_shop": [
        {"category": "products",             "en_q": "What furniture items are available?",                "en_a": "Sofas, beds, wardrobes, dining sets, office furniture, and home décor items are available.",                   "ml_q": "Enthu furniture undu?",                          "ml_a": "Sofas, beds, wardrobes, dining sets, office furniture, home décor ellam undu."},
        {"category": "custom",               "en_q": "Do you make custom furniture?",                     "en_a": "Yes, customised furniture can be designed and built to your requirements.",                              "ml_q": "Custom furniture cheyyumo?",                     "ml_a": "Athe, requirements anusari custom furniture design, build cheyyam."},
        {"category": "delivery",             "en_q": "Do you offer delivery and installation?",           "en_a": "Yes, free or paid delivery and professional installation are available.",                            "ml_q": "Delivery, installation undo?",                   "ml_a": "Athe, free allenkil paid delivery, professional installation undu."},
        {"category": "material",             "en_q": "What materials are used?",                          "en_a": "Teak, plywood, MDF, metal, glass, and other quality materials are used.",                          "ml_q": "Enthu materials use cheyyunnu?",                 "ml_a": "Teak, plywood, MDF, metal, glass, matte quality materials use cheyyunnu."},
        {"category": "warranty_furn",        "en_q": "Do you provide warranty?",                          "en_a": "Yes, furniture comes with a manufacturing warranty.",                                               "ml_q": "Warranty undo?",                                 "ml_a": "Athe, manufacturing warranty undu."},
        {"category": "emi",                  "en_q": "Is EMI available for furniture?",                   "en_a": "Yes, easy EMI options are available on select products.",                                          "ml_q": "Furniture EMI-il vangaamo?",                     "ml_a": "Athe, select products-il easy EMI undu."},
    ],

    # ── MOBILE / RECHARGE SHOP ───────────────────────────────────────────────
    "mobile_shop": [
        {"category": "products",             "en_q": "What do you sell?",                                  "en_a": "Mobile phones, accessories, earphones, chargers, screen protectors, and smart gadgets are available.",         "ml_q": "Enthokke undu?",                                 "ml_a": "Mobile phones, accessories, earphones, chargers, screen protectors, gadgets ellam undu."},
        {"category": "recharge",             "en_q": "Do you do mobile recharges?",                       "en_a": "Yes, all network recharges, DTH recharges, and bill payments are done.",                                 "ml_q": "Mobile recharge cheyyumo?",                      "ml_a": "Athe, all network recharges, DTH, bill payments cheyyunnu."},
        {"category": "repair",               "en_q": "Do you repair mobile phones?",                      "en_a": "Yes, screen replacement, battery change, software issues, and general repairs are done.",                "ml_q": "Mobile repair cheyyumo?",                        "ml_a": "Athe, screen, battery, software, general repairs cheyyunnu."},
        {"category": "second_hand",          "en_q": "Do you sell second-hand phones?",                   "en_a": "Yes, quality-checked used phones are available.",                                                      "ml_q": "Second hand phones undo?",                       "ml_a": "Athe, quality check cheyttha used phones undu."},
        {"category": "sim_card",             "en_q": "Do you sell SIM cards?",                            "en_a": "Yes, SIM cards from all major networks are available.",                                            "ml_q": "SIM card undu?",                                 "ml_a": "Athe, all major networks SIM cards undu."},
    ],

    # ── LAUNDRY ──────────────────────────────────────────────────────────────
    "laundry_service": [
        {"category": "services",             "en_q": "What laundry services do you offer?",                "en_a": "Wash, dry, fold, ironing, dry cleaning, and express laundry services are available.",                         "ml_q": "Enthu laundry services undu?",                   "ml_a": "Wash, dry, fold, ironing, dry cleaning, express laundry undu."},
        {"category": "pickup",               "en_q": "Do you offer pickup and delivery?",                  "en_a": "Yes, home pickup and delivery of laundry is available.",                                                   "ml_q": "Pickup delivery undo?",                          "ml_a": "Athe, home pickup, delivery undu."},
        {"category": "timing_laundry",       "en_q": "How long does laundry take?",                       "en_a": "Standard service takes 24-48 hours. Express same-day service may be available.",                        "ml_q": "Laundry ethra time?",                            "ml_a": "Standard 24-48 mani. Express same-day undaavaam."},
        {"category": "dry_cleaning",         "en_q": "Do you do dry cleaning?",                           "en_a": "Yes, dry cleaning for suits, sarees, coats, and delicate fabrics is available.",                     "ml_q": "Dry cleaning undo?",                             "ml_a": "Athe, suits, sarees, coats, delicate fabrics dry cleaning undu."},
        {"category": "ironing",              "en_q": "Is ironing service available?",                     "en_a": "Yes, ironing and steam pressing services are available.",                                          "ml_q": "Ironing service undo?",                          "ml_a": "Athe, ironing, steam pressing undu."},
    ],

    # ── TAILORING ────────────────────────────────────────────────────────────
    "tailoring_shop": [
        {"category": "services",             "en_q": "What tailoring services do you provide?",            "en_a": "Stitching, alterations, blouse work, uniforms, and custom garment making are available.",                    "ml_q": "Enthu tailoring services undu?",                 "ml_a": "Stitching, alterations, blouse work, uniforms, custom garment making undu."},
        {"category": "blouse",               "en_q": "Do you stitch blouses?",                            "en_a": "Yes, all types of blouse designs including bridal and designer blouses are stitched.",                   "ml_q": "Blouse stitch cheyyumo?",                        "ml_a": "Athe, bridal, designer ulppedunna all types blouse designs cheyyunnu."},
        {"category": "timing",               "en_q": "How long does stitching take?",                     "en_a": "Regular work takes 3-7 days. Urgent stitching may be available at extra charge.",                    "ml_q": "Stitching ethra divasam?",                       "ml_a": "Regular 3-7 divasam. Urgent work extra charge-il undaavaam."},
        {"category": "alteration",           "en_q": "Do you do alterations on readymade clothes?",       "en_a": "Yes, alterations for all types of garments are done.",                                              "ml_q": "Readymade alteration cheyyumo?",                 "ml_a": "Athe, all garment types alteration cheyyunnu."},
        {"category": "uniform_stitch",       "en_q": "Do you stitch school or office uniforms?",          "en_a": "Yes, bulk uniform orders for schools and institutions are accepted.",                               "ml_q": "Uniform stitch cheyyumo?",                       "ml_a": "Athe, schools, institutions bulk uniform orders cheyyunnu."},
    ],

    # ── COACHING / TUITION CENTER ─────────────────────────────────────────────
    "coaching_center": [
        {"category": "courses",              "en_q": "What subjects or courses do you offer?",             "en_a": "Tuition for school subjects, competitive exam preparation, language courses, and skill development are available.",  "ml_q": "Ethu subjects undu?",                            "ml_a": "School subjects, competitive exams, language courses, skill development ellam undu."},
        {"category": "batches",              "en_q": "What batch timings are available?",                  "en_a": "Morning, afternoon, evening, and weekend batches are available.",                                            "ml_q": "Batch timings enthaanu?",                        "ml_a": "Morning, afternoon, evening, weekend batches undu."},
        {"category": "online",               "en_q": "Do you offer online classes?",                      "en_a": "Yes, online live and recorded classes are available.",                                                    "ml_q": "Online classes undo?",                           "ml_a": "Athe, online live, recorded classes undu."},
        {"category": "demo_class",           "en_q": "Is a demo class available?",                        "en_a": "Yes, a free demo class may be available for new students.",                                           "ml_q": "Demo class kittumoo?",                           "ml_a": "Athe, new students-inu free demo class undaavaam."},
        {"category": "fees_coaching",        "en_q": "What are the tuition fees?",                        "en_a": "Fees depend on subject, level, and batch type. Contact us for the fee structure.",                   "ml_q": "Tuition fees ethreyaanu?",                       "ml_a": "Subject, level, batch anusari fees. Fee structure ariyaan contact cheyyuka."},
        {"category": "results",              "en_q": "What are your student results like?",               "en_a": "Our students have achieved excellent results in board exams and competitive tests.",                   "ml_q": "Students results engane undu?",                  "ml_a": "Board exams, competitive tests-il students excellent results achieve cheythu."},
    ],

    # ── SPA / WELLNESS ────────────────────────────────────────────────────────
    "spa": [
        {"category": "services",             "en_q": "What spa services are available?",                   "en_a": "Body massage, facial, steam, sauna, aromatherapy, and beauty treatments are available.",                      "ml_q": "Enthu spa services undu?",                       "ml_a": "Body massage, facial, steam, sauna, aromatherapy, beauty treatments undu."},
        {"category": "massage",              "en_q": "What massage types do you offer?",                  "en_a": "Swedish, deep tissue, Thai, Ayurvedic, hot stone, and relaxation massages are available.",               "ml_q": "Ethu massage types undu?",                       "ml_a": "Swedish, deep tissue, Thai, Ayurvedic, hot stone, relaxation massages undu."},
        {"category": "packages",             "en_q": "Do you have spa packages?",                         "en_a": "Yes, day spa packages, couple packages, and wellness packages are available.",                        "ml_q": "Spa packages undo?",                             "ml_a": "Athe, day spa, couple, wellness packages undu."},
        {"category": "appointment_spa",      "en_q": "Do I need to book in advance?",                     "en_a": "Yes, advance booking is recommended. Same-day booking may be available based on slots.",             "ml_q": "Advance booking venamoo?",                       "ml_a": "Athe, advance booking recommend cheyyunnu. Slots anusari same-day undaavaam."},
        {"category": "ladies_only",          "en_q": "Is it available for ladies only?",                  "en_a": "We have dedicated time slots and separate areas for ladies.",                                      "ml_q": "Ladies only undo?",                              "ml_a": "Ladies-inu dedicated time slots, separate areas undu."},
        {"category": "ayurvedic_spa",        "en_q": "Do you offer Ayurvedic treatments?",               "en_a": "Yes, Ayurvedic therapies like Abhyanga, Shirodhara, and Kizhi are available.",                    "ml_q": "Ayurvedic treatments undo?",                     "ml_a": "Athe, Abhyanga, Shirodhara, Kizhi ulppedunna Ayurvedic therapies undu."},
    ],

    # ── HARDWARE STORE ────────────────────────────────────────────────────────
    "hardware_store": [
        {"category": "products",             "en_q": "What hardware products are available?",              "en_a": "Tools, pipes, fittings, paint, electrical items, plumbing supplies, and building materials are available.",     "ml_q": "Enthu hardware items undu?",                     "ml_a": "Tools, pipes, fittings, paint, electrical items, plumbing, building materials undu."},
        {"category": "paint",                "en_q": "Do you sell paint and wall finishing products?",    "en_a": "Yes, interior and exterior paints from major brands are available.",                                     "ml_q": "Paint undo?",                                    "ml_a": "Athe, interior, exterior paints major brands-il undu."},
        {"category": "plumbing",             "en_q": "Do you have plumbing materials?",                   "en_a": "Yes, pipes, taps, fittings, water tanks, and sanitary ware are available.",                           "ml_q": "Plumbing materials undo?",                       "ml_a": "Athe, pipes, taps, fittings, water tanks, sanitary ware undu."},
        {"category": "electrical",           "en_q": "Do you sell electrical items?",                     "en_a": "Yes, wires, switches, MCBs, and electrical accessories are available.",                             "ml_q": "Electrical items undo?",                         "ml_a": "Athe, wires, switches, MCBs, electrical accessories undu."},
        {"category": "tools",                "en_q": "Do you have tools and power tools?",                "en_a": "Yes, hand tools, power tools, drills, and safety equipment are available.",                       "ml_q": "Tools undo?",                                    "ml_a": "Athe, hand tools, power tools, drills, safety equipment undu."},
    ],

    # ── MEDICAL LAB / DIAGNOSTIC ──────────────────────────────────────────────
    "diagnostic_center": [
        {"category": "tests",                "en_q": "What tests are available?",                          "en_a": "Blood tests, urine tests, X-ray, ECG, scan, thyroid, sugar, cholesterol, and full body checkup are available.",  "ml_q": "Enthu tests cheyyam?",                           "ml_a": "Blood, urine tests, X-ray, ECG, scan, thyroid, sugar, cholesterol, full body checkup undu."},
        {"category": "home_collection",      "en_q": "Do you offer home sample collection?",              "en_a": "Yes, home blood and sample collection service is available.",                                           "ml_q": "Home sample collection undo?",                   "ml_a": "Athe, home blood, sample collection undu."},
        {"category": "report_time",          "en_q": "How long do reports take?",                         "en_a": "Most reports are ready within 24-48 hours. Urgent reports may be available faster.",                  "ml_q": "Report ethra time-il kittum?",                   "ml_a": "Most reports 24-48 mani-il kittum. Urgent reports vegam undaavaam."},
        {"category": "packages_diag",        "en_q": "Do you have health package deals?",                 "en_a": "Yes, preventive health checkup packages are available at discounted rates.",                        "ml_q": "Health packages undo?",                          "ml_a": "Athe, preventive health checkup packages discounted rates-il undu."},
        {"category": "doctor",               "en_q": "Is a doctor available for consultation?",           "en_a": "Yes, doctors are available for consultation along with the diagnostic services.",                 "ml_q": "Doctor consultation undo?",                      "ml_a": "Athe, diagnostic services kaum doctor consultation undu."},
    ],
}

# ═══════════════════════════════════════════════════════════════════════════
#  OLLAMA — generate shop-type FAQs for unknown types
# ═══════════════════════════════════════════════════════════════════════════

def _call_ollama(prompt: str) -> str:
    # long num_predict + generous timeout: this generates 15 FAQs in one go
    reply, ok = ollama_client.generate(
        prompt, temperature=0.15, num_predict=2000, timeout=180,
    )
    return reply if ok else ""

def _generate_via_ollama(shop_type: str) -> list[dict]:
    """Ask Ollama to generate 15 shop-specific FAQs in English + Manglish."""
    display = shop_type.replace("_", " ")
    print(f"  Asking Ollama for '{display}'...")
    prompt = f"""Generate exactly 15 FAQ entries for a {display} shop in Kerala, India.
Return ONLY a valid JSON array. No explanation, no markdown.
Each item must have these exact keys:
  "category"  : short snake_case tag (e.g. "opening_hours")
  "en_q"      : question in natural English
  "en_a"      : answer in natural English (1-2 sentences)
  "ml_q"      : same question in Manglish (Kerala Malayalam written in English letters)
  "ml_a"      : same answer in Manglish

Manglish style: mix Malayalam words with English, written in English script.
Example Manglish: "Delivery undo?" / "Athe, WhatsApp vazhi order cheyyam."

Cover: what they offer, pricing, timings, booking/ordering, delivery, quality, specialties.
Return only the JSON array, nothing else."""

    raw = _call_ollama(prompt)
    if not raw:
        return []
    # strip markdown fences
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data and "en_q" in data[0]:
            return data
    except Exception:
        pass
    return []


# ═══════════════════════════════════════════════════════════════════════════
#  DISK CACHE for Ollama results
# ═══════════════════════════════════════════════════════════════════════════

def _cache_file(shop_type: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9_]", "_", shop_type)
    return CACHE_DIR / f"{safe}.json"


def _load_cached(shop_type: str) -> list[dict] | None:
    p = _cache_file(shop_type)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_cache(shop_type: str, data: list[dict]) -> None:
    try:
        _cache_file(shop_type).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"  [cache write error] {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  QUESTION VARIANT LIBRARY
#  Maps category → (english_variants, manglish_variants)
#  Used by build_unified_faqs() to enrich each FAQ with 4–5 phrasings.
#  Improves semantic match hit-rate from ~40% to ~85%+ on real messages.
# ═══════════════════════════════════════════════════════════════════════════

CATEGORY_VARIANTS: dict[str, tuple[list[str], list[str]]] = {
    "hours": (
        ["What are your timings?", "When do you open?", "What time do you close?", "Are you open now?"],
        ["Ethra mani open aanu?", "Ningal eppo open aanu?", "Timing enthu aanu?", "Ippo open aano?"],
    ),
    "location": (
        ["Where are you located?", "What is your address?", "How do I get there?", "Where is your shop?"],
        ["Evide aanu?", "Address enthu aanu?", "Engane etham?", "Ningalde shop evide aanu?"],
    ),
    "contact": (
        ["How can I contact you?", "What is your phone number?", "Do you have WhatsApp?", "How to reach you?"],
        ["Ningale engane contact cheyyam?", "Number enthu aanu?", "WhatsApp undaakumo?", "Ethra aanu number?"],
    ),
    "payment": (
        ["What payment methods do you accept?", "Can I pay by card?", "Do you accept UPI?", "Is cash accepted?"],
        ["Enthu payment modes und?", "Card edukumo?", "UPI cheyyaamo?", "GPay cheyyaamo?"],
    ),
    "delivery": (
        ["Do you offer delivery?", "Can you deliver to my location?", "What is the delivery charge?", "How long does delivery take?"],
        ["Delivery undaakumo?", "Deliver cheyyumo?", "Delivery charge ethra?", "Ethra neram kittum?"],
    ),
    "returns": (
        ["What is your return policy?", "Can I return a product?", "How do I get a refund?", "How many days to return?"],
        ["Return cheyyaamo?", "Refund kittum?", "Return policy enthu aanu?", "Ethra diwasam return cheyyam?"],
    ),
    "booking": (
        ["How do I book an appointment?", "Can I book a slot?", "Is advance booking available?", "How to schedule a visit?"],
        ["Appointment book cheyyaamo?", "Slot book cheyyaamo?", "Advance booking undaakumo?", "Evide register cheyyam?"],
    ),
    "services": (
        ["What services do you offer?", "What do you provide?", "What treatments are available?", "What can I get here?"],
        ["Enthu services und?", "Enthu cheyyunnu?", "Enthu treatments und?", "Yenthu kittum ividey?"],
    ),
    "pricing": (
        ["What are your prices?", "How much does it cost?", "What is the fee?", "Can I see your price list?"],
        ["Ethra aanu price?", "Cost ethra?", "Fee ethra?", "Price list und?"],
    ),
    "offer": (
        ["Do you have any offers?", "Is there a discount?", "Any special deals?", "First-time customer offer?"],
        ["Offer undaakumo?", "Discount und?", "Special deal und?", "New customer offer undaakumo?"],
    ),
    "parking": (
        ["Is parking available?", "Where can I park?", "Do you have a parking area?"],
        ["Parking undaakumo?", "Parking evide und?", "Vehicle park cheyyaamo?"],
    ),
    "complaint": (
        ["I have a complaint", "I want to raise an issue", "Something went wrong", "I'm not satisfied"],
        ["Oru complaint und", "Problem und", "Issue cheyyaan und", "Sheriya alla"],
    ),
    "general": (
        ["Can you help me?", "I have a question", "I need information", "Can you tell me more?"],
        ["Help cheyyumo?", "Oru doubt und", "Ariyaano?", "Paryanjudamo?"],
    ),
}


def _get_variants(category: str, en_q: str, ml_q: str) -> list[str]:
    """
    Build question_variants list for a FAQ entry.
    Combines the specific English + Manglish questions with up to 2
    extra phrasings from CATEGORY_VARIANTS for that category.
    Deduplicates and caps at 6 variants total.
    """
    cv = CATEGORY_VARIANTS.get(category) or CATEGORY_VARIANTS.get("general")
    variants = list(dict.fromkeys(filter(None, [en_q, ml_q])))

    if cv:
        en_extras, ml_extras = cv
        # Add 1 English extra and 1 Manglish extra that aren't already present
        for v in en_extras:
            if v not in variants and len(variants) < 6:
                variants.append(v)
                break
        for v in ml_extras:
            if v not in variants and len(variants) < 6:
                variants.append(v)
                break

    return variants


# ═══════════════════════════════════════════════════════════════════════════
#  GET SHOP-TYPE FAQS  (hardcoded → disk cache → Ollama → empty)
# ═══════════════════════════════════════════════════════════════════════════

def _get_shop_faqs(shop_type: str, use_ollama: bool) -> list[dict]:
    key = shop_type.lower().strip()
    if key in SHOP_FAQS:
        return SHOP_FAQS[key]
    cached = _load_cached(key)
    if cached:
        print(f"  [cache hit] '{key}'")
        return cached
    if use_ollama:
        data = _generate_via_ollama(key)
        if data:
            _save_cache(key, data)
            return data
    print(f"  [warning] No shop FAQs for '{key}' — universal only")
    return []


# ═══════════════════════════════════════════════════════════════════════════
#  BUILD FINAL FAQ LIST
# ═══════════════════════════════════════════════════════════════════════════

def build_faqs(shop_type: str, lang: str, use_ollama: bool = True) -> list[dict]:
    """
    Build a complete FAQ list for a shop type in the given language.
    lang: "english" or "manglish"
    Returns list of {"category": ..., "question": ..., "answer": ...}
    """
    result = []

    # 1. Universal FAQs
    for cat, en_q, en_a, ml_q, ml_a in UNIVERSAL:
        q = ml_q if lang == "manglish" else en_q
        a = ml_a if lang == "manglish" else en_a
        result.append({"category": cat, "question": q, "answer": a})

    # 2. Shop-type specific FAQs
    shop_specific = _get_shop_faqs(shop_type, use_ollama)
    for entry in shop_specific:
        if lang == "manglish":
            q = entry.get("ml_q", entry.get("en_q", ""))
            a = entry.get("ml_a", entry.get("en_a", ""))
        else:
            q = entry.get("en_q", "")
            a = entry.get("en_a", "")
        if q and a:
            result.append({
                "category": entry.get("category", "general"),
                "question": q,
                "answer": a,
            })

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  SAVE OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

def save_faqs(shop_type: str, out_dir: str, use_ollama: bool = True) -> tuple[int, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    en_faqs = build_faqs(shop_type, "english",  use_ollama)
    ml_faqs = build_faqs(shop_type, "manglish", use_ollama)

    en_path = out / f"{shop_type}_english.json"
    ml_path = out / f"{shop_type}_manglish.json"

    en_path.write_text(json.dumps({"faqs": en_faqs}, ensure_ascii=False, indent=2), encoding="utf-8")
    ml_path.write_text(json.dumps({"faqs": ml_faqs}, ensure_ascii=False, indent=2), encoding="utf-8")

    return len(en_faqs), len(ml_faqs)


# ═══════════════════════════════════════════════════════════════════════════
#  ALL SHOP TYPES
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
#  UNIFIED OUTPUT — shop_manager.py compatible format
#  Both languages in one file. shop_manager._parse_faqs() reads this.
#
#  Each FAQ entry:
#    id                : unique string
#    category          : snake_case topic
#    question_variants : [en_q, ml_q]  — both get embedded separately
#    answer            : English answer (returned when lang == "english")
#    answer_ml         : Manglish answer (returned when lang == "manglish")
#    lang              : "english_manglish"
#    tier              : "base" | "type"
# ═══════════════════════════════════════════════════════════════════════════

def build_unified_faqs(shop_type: str, use_ollama: bool = True) -> list[dict]:
    """
    Build unified FAQ list with both languages per entry.
    Consumed by shop_manager._parse_faqs() and generate_shop.py.
    """
    result = []

    # 1. Universal FAQs (base tier — every shop)
    for i, (cat, en_q, en_a, ml_q, ml_a) in enumerate(UNIVERSAL):
        result.append({
            "id":                f"base_{cat}",
            "category":          cat,
            "question_variants": _get_variants(cat, en_q, ml_q),
            "answer":            en_a,
            "answer_ml":         ml_a,
            "lang":              "english_manglish",
            "tier":              "base",
        })

    # 2. Shop-type specific FAQs
    shop_specific = _get_shop_faqs(shop_type, use_ollama)
    for i, entry in enumerate(shop_specific):
        en_q = entry.get("en_q", "")
        ml_q = entry.get("ml_q", en_q)
        en_a = entry.get("en_a", "")
        ml_a = entry.get("ml_a", en_a)
        if not en_q or not en_a:
            continue
        result.append({
            "id":                f"{shop_type}_{entry.get('category', 'q')}_{i}",
            "category":          entry.get("category", "general"),
            "question_variants": _get_variants(entry.get("category", "general"), en_q, ml_q),
            "answer":            en_a,
            "answer_ml":         ml_a,
            "lang":              "english_manglish",
            "tier":              "type",
        })

    return result


def save_unified_faqs(shop_type: str, out_dir: str, use_ollama: bool = True) -> int:
    """
    Save unified FAQ file to {out_dir}/{shop_type}_faq.json.
    This is what shop_manager.py loads via load_type_faqs().
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    faqs = build_unified_faqs(shop_type, use_ollama)
    path = out / f"{shop_type}_faq.json"
    path.write_text(json.dumps(faqs, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(faqs)


def load_type_faqs(shop_type: str, types_dir: str = "faqs/types") -> list[dict]:
    """
    Load pre-generated unified FAQ pack for a shop type.
    Called from:
      - shop_manager.ShopContext._load()
      - generate_shop.generate_shop_from_items()
    Falls back to 'general' if specific type file is missing.
    """
    p = Path(types_dir) / f"{shop_type}_faq.json"
    if not p.exists():
        p = Path(types_dir) / "general_faq.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[load_type_faqs] Error loading {p}: {e}")
    return []

ALL_SHOP_TYPES = [
    # Known hardcoded
    "restaurant", "bakery", "beauty_parlour", "gym", "pharmacy",
    "clothing", "electronics", "jewellery", "optical", "hotel",
    "supermarket", "school", "travel_agency", "real_estate",
    "law_firm", "ca_firm", "dental_clinic", "salon", "cafe",
    "pet_shop", "driving_school", "furniture_shop", "mobile_shop",
    "laundry_service", "tailoring_shop", "coaching_center", "spa",
    "hardware_store", "diagnostic_center",
    # New types → Ollama on first run, then cached
    "automobile_showroom", "car_service_center", "bike_showroom",
    "bike_service_center", "computer_shop", "laptop_service_center",
    "electrical_shop", "home_appliances_store", "stationery_shop",
    "book_store", "toy_shop", "gift_shop", "footwear_shop",
    "watch_shop", "aquarium_shop", "flower_shop", "ice_cream_shop",
    "juice_shop", "tea_shop", "fast_food_shop", "catering_service",
    "event_management", "photography_studio", "printing_shop",
    "advertising_agency", "digital_marketing_agency", "it_company",
    "software_company", "web_development_agency", "cyber_cafe",
    "recharge_shop", "courier_service", "logistics_company",
    "packers_movers", "taxi_service", "car_rental", "bike_rental",
    "music_academy", "dance_academy", "yoga_center",
    "tattoo_studio", "dry_cleaning_service", "interior_design",
    "architecture_firm", "construction_company", "plumbing_service",
    "electrical_service", "ac_service_center", "cctv_installation",
    "security_agency", "pest_control", "cleaning_service",
    "water_purifier_service", "ro_service_center",
    "internet_service_provider", "finance_company",
    "insurance_agency", "bank", "microfinance_service",
    "gold_loan_company", "forex_exchange",
    "medical_laboratory", "physiotherapy_clinic",
    "veterinary_clinic", "eye_clinic", "skin_clinic",
    "ayurvedic_clinic", "homeopathy_clinic",
    "fitness_supplement_store", "organic_store",
    "agricultural_store", "seed_fertilizer_shop",
    "fish_market", "meat_shop", "vegetable_shop", "fruit_shop",
    "wholesale_shop", "department_store", "wedding_planner",
    "function_hall", "resort", "homestay",
    "apartment_rental", "hostel", "pg_accommodation",
    "sports_shop", "adventure_tourism", "boat_service",
    "immigration_consultancy", "overseas_education_consultancy",
    "recruitment_agency", "hr_consultancy",
    "gaming_center", "kindergarten", "daycare_center",
    "hospital", "general",
]


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
#  CLI — supports both split (legacy) and unified output
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate English + Manglish FAQs for any shop type"
    )
    parser.add_argument("--type",        help="Single shop type (e.g. restaurant)")
    parser.add_argument("--all",         action="store_true", help="All shop types")
    parser.add_argument("--out",         default="faq_templates",
                        help="Output dir for legacy split files (default: faq_templates)")
    parser.add_argument("--unified",     action="store_true",
                        help="Output unified faqs/types/{type}_faq.json for shop_manager")
    parser.add_argument("--unified-out", default="faqs/types",
                        help="Output dir for unified files (default: faqs/types)")
    parser.add_argument("--no-ollama",   action="store_true",
                        help="Skip Ollama for unknown types")
    args = parser.parse_args()

    use_ollama  = not args.no_ollama
    unified_out = args.unified_out

    if args.all:
        total = len(ALL_SHOP_TYPES)
        if args.unified:
            print(f"\n🚀 Unified FAQs → {unified_out}/  ({total} types)\n")
            for i, stype in enumerate(ALL_SHOP_TYPES, 1):
                src = ("hardcoded" if stype in SHOP_FAQS
                       else "cached" if _load_cached(stype)
                       else "ollama" if use_ollama else "universal-only")
                print(f"[{i:3}/{total}] {stype:<35} ({src})")
                try:
                    n = save_unified_faqs(stype, unified_out, use_ollama)
                    print(f"         ✅  {n} FAQs")
                except Exception as e:
                    print(f"         ❌  {e}")
                time.sleep(0.05)
            print(f"\n✅ Done → {unified_out}/")
        else:
            print(f"\n🚀 Split FAQs → {args.out}/  ({total} types)\n")
            for i, stype in enumerate(ALL_SHOP_TYPES, 1):
                src = ("hardcoded" if stype in SHOP_FAQS
                       else "cached" if _load_cached(stype)
                       else "ollama" if use_ollama else "universal-only")
                print(f"[{i:3}/{total}] {stype:<35} ({src})")
                try:
                    en_n, ml_n = save_faqs(stype, args.out, use_ollama)
                    print(f"         ✅  {en_n} EN + {ml_n} ML")
                except Exception as e:
                    print(f"         ❌  {e}")
                time.sleep(0.05)
            print(f"\n✅ Done → {args.out}/")

    elif args.type:
        stype = args.type.lower().replace(" ", "_")
        if args.unified:
            n = save_unified_faqs(stype, unified_out, use_ollama)
            print(f"✅ {n} unified FAQs → {unified_out}/{stype}_faq.json")
        else:
            en_n, ml_n = save_faqs(stype, args.out, use_ollama)
            print(f"✅ {en_n} EN + {ml_n} ML → {args.out}/{stype}_*.json")

    else:
        parser.print_help()
