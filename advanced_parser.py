"""
Techpack Construction Intelligence Parser.
Extracts ONLY decision-critical information for:
- gauge selection
- folder / template selection
- construction risk analysis

Output: section-wise JSON with keys collar, sleeve, cuff, pocket, front, back, assembly.
Each item: category, name, value, source (explicit|inferred), relevance (gauge|folder|risk|automation).
"""
import sys
import json
import re
import pdfplumber
import logging

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(message)s')
logger = logging.getLogger()

# -------------------------------------------------------------------------
# ALLOWED CATEGORIES (STRICT)
# -------------------------------------------------------------------------
ALLOWED_CATEGORIES = {"measurement", "stitch", "process", "automation", "construction_note"}
ALLOWED_RELEVANCE = {"gauge", "folder", "risk", "automation"}
OUTPUT_SECTIONS = ["collar", "sleeve", "cuff", "pocket", "front", "back", "assembly"]

# -------------------------------------------------------------------------
# PATTERNS
# -------------------------------------------------------------------------
MEASUREMENT_REGEX = re.compile(
    r"((\d+\s?/\s?\d+)|(\d+(\.\d+)?))\s?(mm|cm|\"|inch|”|')", re.IGNORECASE
)
STITCH_REGEX = re.compile(
    r"\b(SNLS|DNCS|T/S|S/B|T\/S|S\/B|SPI|Box stitch|Lock stitch)\b", re.IGNORECASE
)
CONSTRUCTION_REGEX = re.compile(
    r"(back tack|double fold|clean finish|raw edge|binding|facing|hem fold)", re.IGNORECASE
)
AUTOMATION_REGEX = re.compile(r"(auto|pneumatic|operation|notch)", re.IGNORECASE)

# Noise: do not extract these as values or as standalone names
NOISE_VALUES = {"front", "back", "side", "collar", "pocket", "yoke", "sleeve", "cuff", "frontback"}
# Words to strip from names to avoid ambiguous "Back", "Front", etc.
STOP_WORDS = {"front", "back", "frontback", "assembly", "detail", "section", "item"}

IGNORE_LINE_PATTERNS = [
    r"buyer", r"style ref", r"order no", r"season", r"modified",
    r"main label", r"size label", r"w/c label", r"barcode",
    r"dressed", r"cotton", r"brand", r"logo", r"sheet", r"page", r"spec actual"
]

RELEVANT_MEASUREMENT_KEYWORDS = [
    "margin", "hem", "seam", "stand", "height", "width", "placket",
    "cuff", "opening", "allowance", "depth", "run", "spread", "trimming", "fold"
]

# Term -> relevance for naming
RELEVANCE_MAP = {
    "margin": "gauge", "allowance": "gauge", "run": "automation", "stitch": "risk",
    "spi": "risk", "notch": "automation", "hem": "folder", "fold": "folder",
    "binding": "folder", "piping": "folder", "pleat": "folder", "gather": "folder",
    "smocking": "automation", "clean_finish": "folder", "double_fold": "folder",
}

# Construction phrases that imply folder/template (for inference)
FOLDER_IMPLYING = re.compile(
    r"clean finish|double fold|binding|hem|facing|raw edge|back tack", re.IGNORECASE
)


def _is_ignored_line(line):
    for pat in IGNORE_LINE_PATTERNS:
        if re.search(pat, line, re.IGNORECASE):
            return True
    return False


def _is_relevant_measurement_label(label):
    if not label or len(label) > 120:
        return False
    lower = label.lower()
    if any(kw in lower for kw in RELEVANT_MEASUREMENT_KEYWORDS):
        return True
    if len(label) < 25 and not any(w in lower for w in NOISE_VALUES):
        return True
    return False


def _clear_name(section, raw_name):
    """Produce unambiguous name: e.g. collar_run_stitch, cuff_hem_width. No raw 'Back'/'Front'."""
    if not raw_name or not raw_name.strip():
        return f"{section}_dimension"
    text = raw_name.lower().strip()
    for word in list(STOP_WORDS) + [section]:
        text = re.sub(rf"\b{re.escape(word)}\b", "", text)
    text = re.sub(r"[-\s]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text or text in NOISE_VALUES:
        return f"{section}_spec"
    return f"{section}_{text}" if not text.startswith(section + "_") else text


def _relevance_from_name(name):
    lower = name.lower()
    for term, rel in RELEVANCE_MAP.items():
        if term in lower:
            return rel
    return "risk"


def _add_item(results, seen, section, category, name, value, source="explicit", relevance=None):
    if section not in results:
        return
    if not name or not value:
        return
    if value.upper().strip() in NOISE_VALUES:
        return
    if category not in ALLOWED_CATEGORIES:
        return
    clear = _clear_name(section, name)
    rel = relevance or _relevance_from_name(clear)
    if rel not in ALLOWED_RELEVANCE:
        rel = "risk"
    item = {
        "category": category,
        "name": clear,
        "value": str(value).strip(),
        "source": source if source in ("explicit", "inferred") else "explicit",
        "relevance": rel,
    }
    key = (item["category"], item["name"], item["value"].lower())
    if key in seen:
        return
    seen.add(key)
    results[section].append(item)


def _infer_from_construction_line(section, line, results, seen):
    """Infer folder/construction_note from phrases like 'Pocket S/B clean finish'."""
    lower = line.lower()
    if not FOLDER_IMPLYING.search(lower):
        return
    match = CONSTRUCTION_REGEX.search(line)
    term = match.group(0) if match else "clean finish"
    name_part = term.replace(" ", "_").replace("-", "_")
    name = f"{section}_{name_part}" if not name_part.startswith(section) else name_part
    _add_item(
        results, seen, section, "construction_note",
        name, f"Likely requires folder for {term}",
        source="inferred", relevance="folder",
    )


def extract_from_pdf(pdf_path):
    results = {s: [] for s in OUTPUT_SECTIONS}
    seen = set()

    try:
        with pdfplumber.open(pdf_path) as pdf:
            lines = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    lines.extend(t.split("\n"))
    except Exception as e:
        logger.error(f"PDF read failed: {e}")
        return _finalize(results)

    current_section = "assembly"
    for line in lines:
        line = line.strip()
        if not line or _is_ignored_line(line):
            continue

        lower = line.lower()
        if "collar" in lower:
            current_section = "collar"
        elif "cuff" in lower:
            current_section = "cuff"
        elif "sleeve" in lower:
            current_section = "sleeve"
        elif "pocket" in lower:
            current_section = "pocket"
        elif "yoke" in lower:
            current_section = "assembly"
        elif "front" in lower and "back" not in lower:
            current_section = "front"
        elif "back" in lower:
            current_section = "back"

        for m in MEASUREMENT_REGEX.finditer(line):
            full = m.group(0)
            val = m.group(1)
            unit = m.group(5) or ""
            name_part = line.replace(full, "", 1).strip()
            if _is_relevant_measurement_label(name_part):
                _add_item(
                    results, seen, current_section, "measurement",
                    name_part or "dimension", f"{val}{unit}",
                    source="explicit", relevance="gauge"
                )

        stitch_m = STITCH_REGEX.search(line)
        if stitch_m:
            val = stitch_m.group(0)
            spi_m = re.search(r"SPI\s?(\d+)", line, re.IGNORECASE)
            if spi_m:
                val = f"{val} (SPI {spi_m.group(1)})"
            _add_item(
                results, seen, current_section, "stitch",
                "stitch_type", val,
                source="explicit", relevance="risk"
            )

        construction_m = CONSTRUCTION_REGEX.search(line)
        if construction_m:
            term = construction_m.group(0)
            _add_item(
                results, seen, current_section, "process",
                _clear_name(current_section, term).replace(f"{current_section}_", "").strip("_") or "construction_method",
                term, source="explicit", relevance="folder"
            )
            _add_item(
                results, seen, current_section, "construction_note",
                f"{current_section}_folder_requirement",
                f"Likely requires folder for {term}",
                source="inferred", relevance="folder"
            )

        auto_m = AUTOMATION_REGEX.search(line)
        if auto_m:
            _add_item(
                results, seen, current_section, "automation",
                "automation_type", auto_m.group(0),
                source="explicit", relevance="automation"
            )

        if ("margin" in lower or "allowance" in lower) and ":" not in line:
            # Never output raw strings: use numeric value or short descriptor
            meas = MEASUREMENT_REGEX.search(line)
            value = f"{meas.group(1)}{meas.group(5) or ''}" if meas else "Margin/allowance specified"
            _add_item(
                results, seen, current_section, "construction_note",
                f"{current_section}_seam_spec", value,
                source="explicit", relevance="gauge"
            )

        _infer_from_construction_line(current_section, line, results, seen)

    return _finalize(results)


def _finalize(results):
    """Return only OUTPUT_SECTIONS with valid items. No yoke key; yoke stays in assembly."""
    out = {s: [] for s in OUTPUT_SECTIONS}
    for section in OUTPUT_SECTIONS:
        items = results.get(section, [])
        seen = set()
        for item in items:
            sig = (item["category"], item["name"], item["value"].lower())
            if sig in seen:
                continue
            seen.add(sig)
            out[section].append(item)
    return out


# -------------------------------------------------------------------------
# STRICT TECHNICAL TABLE (garment-industry logic, no inference)
# Per component: Construction | Base Measurement | Grading (one category per line)
# Output: components[] with constructionTable, baseMeasurementsTable, gradingTable
# -------------------------------------------------------------------------

TECHNICAL_IGNORE = re.compile(
    r"buyer|style ref|order no|season|modified|wash care|finishing|fabric|trim|care instruction|barcode|w/c label|dressed|cotton|brand|logo|sheet|page\s*\d|--\s*\d+\s+of\s+\d+\s*--",
    re.IGNORECASE
)
# Explicit section headers only (Sleeve, Pocket, Front, Back, Assembly, Collar, Cuff, Yoke)
COMPONENT_HEADING = re.compile(
    r"^(ASSEMBLY|REGULAR\s+CUTAWAY\s+COLLAR|SHORT\s+SLEEVE|SLEEVE|FRONT|STRAIGHT\s+BACK|BACK|STRAIGHT\s+YOKE|YOKE|POCKET|CUFF)\s*$",
    re.IGNORECASE
)
# Size label + value: XS-5cm, S-M-5.5cm, L-XL-6cm, 2XL-3XL-6.5cm
SIZE_VALUE = re.compile(
    r"\b(XS|S|M|L|XL|2XL|3XL)\s*[-:]?\s*(\d+(?:\.\d+)?)\s*(mm|cm)?",
    re.IGNORECASE
)

def _inch_to_mm(val_str):
    """Convert fraction or decimal inch to mm. No guess."""
    val_str = val_str.strip().replace('"', "").replace("'", "")
    m = re.match(r"(\d+)\s*/\s*(\d+)", val_str)
    if m:
        return round(float(m.group(1)) / float(m.group(2)) * 25.4, 2)
    m = re.match(r"(\d+(?:\.\d+)?)\s*(mm|cm)?", val_str, re.IGNORECASE)
    if m:
        n = float(m.group(1))
        u = (m.group(2) or "").lower()
        if u == "cm":
            return round(n * 10, 2)
        if u == "mm":
            return round(n, 2)
        return round(n * 25.4, 2)
    return None

def _normalize_unit(val_str, unit_str):
    """Return (numeric_value, unit) in SI."""
    if not val_str:
        return None, None
    u = (unit_str or "").strip().lower()
    mm = _inch_to_mm(val_str + (u if u in ("mm", "cm") else ""))
    if mm is None:
        return None, None
    if mm >= 10:
        return round(mm / 10, 2), "cm"
    return round(mm, 2), "mm"

def _size_key(s):
    """Normalize size label for grading column key."""
    t = s.upper().strip()
    if t == "2XL":
        return "2XL"
    if t == "3XL":
        return "3XL"
    return t

def extract_technical_table(pdf_path):
    """
    Strict extraction. One category per line: A. Construction | B. Base Measurement | C. Grading.
    Returns: { "components": [ { "component", "constructionTable", "baseMeasurementsTable", "gradingTable" } ] }
    - constructionTable: Operation | Stitch Type | SPI/Gauge | Notes (merged, no risk/folder unless explicit)
    - baseMeasurementsTable: Parameter | Value | Unit | Related Operation
    - gradingTable: Parameter | XS | S | M | L | XL | 2XL | 3XL (one row per parameter)
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            lines = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    lines.extend(t.split("\n"))
    except Exception as e:
        logger.error(f"Technical table PDF read failed: {e}")
        return {"components": []}

    component_map = [
        ("assembly", "Assembly"),
        ("regular cutaway collar", "Collar"),
        ("short sleeve", "Sleeve"),
        ("sleeve", "Sleeve"),
        ("front", "Front"),
        ("straight back", "Back"),
        ("back", "Back"),
        ("straight yoke", "Yoke"),
        ("yoke", "Yoke"),
        ("pocket", "Pocket"),
        ("cuff", "Cuff"),
    ]
    current_component = "Assembly"
    # Per-component accumulators
    construction_rows = {}  # component -> set of (operation, stitch, spi, notes)
    construction_list = {}  # component -> list of dicts (merged)
    base_meas = {}  # component -> list of { parameter, value, unit, relatedOperation }
    grading_params = {}  # component -> { param_key -> { parameter, xs, s, m, l, xl, 2xl, 3xl } }

    def ensure_component(c):
        if c not in construction_list:
            construction_list[c] = []
            construction_rows[c] = set()
            base_meas[c] = []
            grading_params[c] = {}

    SIZE_COLS = ["XS", "S", "M", "L", "XL", "2XL", "3XL"]

    for line in lines:
        raw = line.strip()
        if not raw or len(raw) > 250:
            continue
        if TECHNICAL_IGNORE.search(raw):
            continue
        lower = raw.lower()

        # STEP 1: Component only from explicit section headers
        if raw.isupper() or COMPONENT_HEADING.match(raw):
            for key, name in component_map:
                if key in lower:
                    current_component = name
                    break
            ensure_component(current_component)
            continue

        ensure_component(current_component)

        # STEP 2: Classify into ONE category. Grading first (size labels = C).
        size_matches = list(SIZE_VALUE.finditer(raw))
        if size_matches:
            # C. Grading: one row per parameter, all sizes in columns
            param_candidate = raw
            for m in size_matches:
                param_candidate = param_candidate.replace(m.group(0), " ")
            param_candidate = re.sub(r"\s+", " ", param_candidate).strip()
            if len(param_candidate) > 80:
                param_candidate = param_candidate[:80]
            if not param_candidate:
                param_candidate = "Size"
            param_key = (current_component, param_candidate)
            if param_key not in grading_params[current_component]:
                grading_params[current_component][param_key] = {
                    "parameter": param_candidate,
                    "XS": "", "S": "", "M": "", "L": "", "XL": "", "2XL": "", "3XL": "",
                }
            row = grading_params[current_component][param_key]
            for m in size_matches:
                size_lbl = _size_key(m.group(1))
                val = m.group(2)
                u = (m.group(3) or "").strip().lower()
                cell = val + u if u else val
                if size_lbl in SIZE_COLS:
                    row[size_lbl] = cell
            continue

        # A. Construction: stitch, SPI, process terms only. Merge duplicates per component.
        stitch_m = STITCH_REGEX.search(raw)
        spi_m = re.search(r"SPI\s?(\d+)", raw, re.IGNORECASE)
        const_m = CONSTRUCTION_REGEX.search(raw)
        meas_in_line = MEASUREMENT_REGEX.search(raw)
        operation = raw
        if stitch_m:
            operation = operation.replace(stitch_m.group(0), "")
        if spi_m:
            operation = operation.replace(spi_m.group(0), "")
        if const_m:
            operation = operation.replace(const_m.group(0), "")
        if meas_in_line:
            operation = operation.replace(meas_in_line.group(0), "")
        operation = re.sub(r"\s+", " ", operation).strip()[:80] or "Operation"
        stitch_type = stitch_m.group(0) if stitch_m else (const_m.group(0) if const_m else "")
        spi_val = spi_m.group(1) if spi_m else ""
        measurement_from_line = ""
        if meas_in_line:
            measurement_from_line = meas_in_line.group(0).strip()
        sig = (current_component, operation, stitch_type, spi_val)
        if stitch_type or const_m:
            if sig not in construction_rows[current_component]:
                construction_rows[current_component].add(sig)
                construction_list[current_component].append({
                    "operation": operation,
                    "stitchType": stitch_type,
                    "spiGauge": spi_val,
                    "notes": measurement_from_line,
                })
            continue

        # B. Base Measurement: single numeric, no size labels (already handled above)
        for m in MEASUREMENT_REGEX.finditer(raw):
            val, unit = _normalize_unit(m.group(1), m.group(5))
            if val is None:
                continue
            name_part = raw.replace(m.group(0), "").strip()
            if not name_part or len(name_part) > 80:
                name_part = "Dimension"
            if any(skip in name_part.lower() for skip in ["buyer", "style", "order", "wash", "care", "label", "xs", "s-", "m-", "l-", "xl", "2xl", "3xl"]):
                continue
            base_meas[current_component].append({
                "parameter": name_part[:80],
                "value": str(val),
                "unit": unit or "mm",
                "relatedOperation": "",
            })
            break

    # Build grading table: one row per parameter with size columns
    components_out = []
    seen_components = set()
    for comp in ["Assembly", "Collar", "Sleeve", "Cuff", "Front", "Back", "Yoke", "Pocket"]:
        if comp not in construction_list and comp not in base_meas and comp not in grading_params:
            continue
        seen_components.add(comp)
        ensure_component(comp)
        grading_list = []
        for k, row in grading_params[comp].items():
            grading_list.append({
                "parameter": row["parameter"],
                "XS": row["XS"], "S": row["S"], "M": row["M"], "L": row["L"],
                "XL": row["XL"], "2XL": row["2XL"], "3XL": row["3XL"],
            })
        components_out.append({
            "component": comp,
            "constructionTable": construction_list[comp],
            "baseMeasurementsTable": base_meas[comp],
            "gradingTable": grading_list,
        })
    for comp in construction_list:
        if comp not in seen_components:
            ensure_component(comp)
            grading_list = [
                {"parameter": row["parameter"], "XS": row["XS"], "S": row["S"], "M": row["M"], "L": row["L"], "XL": row["XL"], "2XL": row["2XL"], "3XL": row["3XL"]}
                for row in grading_params[comp].values()
            ]
            components_out.append({
                "component": comp,
                "constructionTable": construction_list[comp],
                "baseMeasurementsTable": base_meas[comp],
                "gradingTable": grading_list,
            })

    return {"components": components_out}


# -------------------------------------------------------------------------
# BASE INFORMATION (buyer, con no., style, fit, season, etc.)
# -------------------------------------------------------------------------

BASE_INFO_PATTERNS = [
    (re.compile(r"buyer\s*[:\-]\s*(.+)", re.IGNORECASE), "buyer"),
    (re.compile(r"(?:order\s*no\.?|con\s*no\.?|contract\s*no\.?)\s*[:\-]\s*(.+)", re.IGNORECASE), "orderNo"),
    (re.compile(r"style\s*ref\.?\s*[:\-]\s*(.+)", re.IGNORECASE), "styleRef"),
    (re.compile(r"fit\s*[:\-]\s*(.+)", re.IGNORECASE), "fit"),
    (re.compile(r"season\s*[:\-]\s*(.+)", re.IGNORECASE), "season"),
    (re.compile(r"modified\s*(?:on)?\s*[:\-]\s*(.+)", re.IGNORECASE), "modified"),
]


def extract_base_info(pdf_path):
    """Extract buyer, con no., style, fit, and other base info from the tech pack."""
    result = {
        "buyer": "",
        "orderNo": "",
        "styleRef": "",
        "fit": "",
        "season": "",
        "modified": "",
    }
    try:
        with pdfplumber.open(pdf_path) as pdf:
            lines = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    lines.extend(t.split("\n"))
    except Exception as e:
        logger.error(f"Base info PDF read failed: {e}")
        return result

    for line in lines:
        raw = line.strip()
        if not raw or len(raw) > 200:
            continue
        for pattern, key in BASE_INFO_PATTERNS:
            m = pattern.search(raw)
            if m:
                val = m.group(1).strip()
                if val and not result[key]:
                    result[key] = val[:120]
                break

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Usage: python advanced_parser.py <pdf_path>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    data = extract_from_pdf(pdf_path)
    technical_table = extract_technical_table(pdf_path)
    base_info = extract_base_info(pdf_path)
    out = {**data, "technicalTable": technical_table, "baseInformation": base_info}
    print(json.dumps(out, indent=2, default=str))
