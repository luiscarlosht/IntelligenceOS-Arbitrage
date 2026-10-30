"""Conservative candidate triage from saved listing descriptions, never exact identity.

Title conflicts reject an investigation candidate, not prove physical goods differ.
Unknown brand/manufacturer equivalence is never assumed. Counts have distinct bases.
"""
import re
import unicodedata

POLICY = 'evidence-v1'
# Explicit title markers found in reviewed evidence. No brand inference from manufacturer.
BRANDS = ('Mainstays', 'GreenLife', 'LIANYU', 'P&P CHEF', 'OXO', 'Cuisinart',
          'Vunnn', 'OHHSUN', 'Axidou', 'TWINBELL', 'oannao', 'AOTHOD',
          'AOKIWO', 'Umite Chef', 'Astercook', 'CAROTE', 'GIR', 'TeamFar',
          'Chef Craft', 'Pleafind', 'Gibson Home', 'Viking', 'Newness', 'Walchoice',
          'Homikit', 'E-far', 'COOK WITH COLOR', 'HEESEM', 'Core Kitchen', 'ZUNEVALIS')
COLORS = {'black', 'white', 'cream', 'cream white', 'pink', 'blue', 'silver',
          'khaki', 'taupe', 'gray', 'grey', 'papyrus beige', 'rose whisper', 'multicolor'}


def clean(value: object) -> str:
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def title_pieces(title: str) -> list[int]:
    """Explicit piece/set-of count only; never bare numbers, percentages or unit_count."""
    patterns = (r'\b(\d+)\s*[- ]?\s*(?:pcs?|pieces?)\b', r'\bset of\s+(\d+)\b')
    return sorted({int(m.group(1)) for pattern in patterns for m in re.finditer(pattern, clean(title))})


def title_colors(title: str) -> list[str]:
    # A terminal selected color is stronger than mentions such as "Black Wooden Handles".
    text = clean(title).rstrip(' ,')
    found = re.search(r'\(([^()]*)\)$', text) or re.search(r',\s*([^,]+)$', text)
    return [found.group(1)] if found and found.group(1) in COLORS else []


def assess(source: dict, candidate: dict, detail: dict | None = None) -> dict:
    """One auditable classification. Plausible means worthy of inspection, never matched."""
    context = source.get('source_context') or {}
    title = candidate.get('title') or ''
    catalog = (detail or {}).get('catalog') or {}
    attrs = (detail or {}).get('package_attributes') or {}
    if catalog and catalog.get('asin') != candidate['asin']:
        raise ValueError('Candidate/detail scope mismatch')
    # Compare independently declared brand to explicit title markers, not manufacturer.
    brand = context.get('brand')
    markers = list(dict.fromkeys((*BRANDS, *context.get('recognized_brands', []), *([brand] if brand else []))))
    titles = [title] + ([catalog['title']] if catalog.get('title') else [])
    seen_brands = sorted({marker for marker in markers if any(
        re.search(r'(?<!\w)'+re.escape(clean(marker))+r'(?!\w)', clean(t)) for t in titles)})
    structured_brands = attrs.get('brand') or ([candidate['brand']] if candidate.get('brand') else [])
    declared_brands = sorted(set(seen_brands) | set(structured_brands))
    conflicts, support, missing = [], [], []
    if brand and declared_brands:
        if any(clean(b) != clean(brand) for b in declared_brands):
            conflicts.append('Explicit title/structured brand differs: source '+str(brand)+'; candidate '+', '.join(declared_brands))
        else:
            support.append('Same declared source brand and explicit title/structured brand: '+str(brand))
    else:
        missing.append('Candidate explicit brand missing' if brand else 'Source brand missing')
    source_pieces = context.get('piece_count')
    counts = sorted({count for t in titles for count in title_pieces(t)})
    if source_pieces is not None and counts:
        if any(count != source_pieces for count in counts):
            conflicts.append(f'Explicit piece-count descriptions differ: source {source_pieces}; candidate {counts}')
        else:
            support.append(f'Explicit piece-count descriptions agree: {source_pieces}; retail package quantity still unknown')
    else:
        missing.append('Comparable explicit piece count missing')
    # Explicit dimensions keep each quantity basis separate.
    patterns = {
        'model': r'\b(?:rd-?\d+|e91mp-8|e92mp-8)\b',
        'net_contents': r'\b\d+(?:\.\d+)?\s*(?:fl\s*oz|oz|ml|grams?|g|liters?)\b',
        'unit_count': r'\b\d+\s*(?:count|ct)\b',
        'pack_count': r'\b\d+[- ]*(?:pack|packs)\b|\bpack of \d+\b',
        'variant': r'\b(?:aaa|aa|quantum|ultimate|sensitive|unscented|gel|liquid|broad line|fine line|ultra.clean|deep moisture|commander)\b',
    }
    dimensions = {}
    for dimension, pattern in patterns.items():
        left = sorted(set(re.findall(pattern, clean(source.get('name')))))
        right = sorted(set(re.findall(pattern, clean(title))))
        if dimension in ('pack_count', 'unit_count'):
            left = sorted({re.search(r'\d+', v).group() for v in left})
            right = sorted({re.search(r'\d+', v).group() for v in right})
        dimensions[dimension] = dict(source=left, candidate=right)
        if not left or not right:
            missing.append('Comparable explicit '+dimension+' unknown')
        elif left != right:
            conflicts.append('Explicit '+dimension+' descriptions differ: '+str(left)+' / '+str(right))
        else:
            support.append('Explicit '+dimension+' agrees: '+str(left))
    source_color = clean(source.get('variation'))
    colors = sorted({c for t in titles for c in title_colors(t)} | {
        clean(c) for c in attrs.get('color', []) if clean(c) in COLORS})
    if source_color in COLORS and colors:
        if any(c != source_color for c in colors):
            conflicts.append('Selected color descriptions differ: source '+source_color+'; candidate '+', '.join(colors))
        else:
            support.append('Selected color description agrees: '+source_color)
    else:
        missing.append('Comparable selected color missing')
    if context.get('checkpoint_schema'):
        from app.checkpoint_quality import compare
        extra_conflicts, extra_support, extra_missing = compare(source, titles, attrs)
        conflicts.extend(extra_conflicts); support.extend(extra_support); missing.extend(extra_missing)
    missing += ['Source identity identifiers/manufacturer-model not verified',
                'Retail package quantity and package composition require independent verification',
                'Titles do not prove exact identity; no brand equivalence assumed']
    if not detail:
        missing.append('Catalog details not retained for this source/candidate pair')
    else:
        missing.append('Amazon manufacturer is separate from source brand; equivalence not established')
    classification = ('rejected_description_difference' if conflicts else
                      'plausible_unverified' if support else 'insufficient_evidence')
    return dict(**candidate, classification=classification, differences=conflicts,
        supporting_evidence=support, missing_evidence=missing, exact=False,
        title_piece_counts=counts, title_brand_markers=seen_brands, amazon_structured_brands=structured_brands,
        source_piece_count=source_pieces, source_retail_package_quantity=source.get('package_quantity'),
        amazon_manufacturer=catalog.get('manufacturer') or None,
        amazon_retail_package_quantity=catalog.get('package_quantity'),
        amazon_number_of_items=attrs.get('number_of_items'), amazon_unit_count=attrs.get('unit_count'),
        detail_retained=bool(detail), dimensions=dimensions)


def review_candidates(source: dict, search: dict, details: dict | None = None) -> dict:
    details = details or {}
    audits = [assess(source, candidate, details.get(candidate['asin'])) for candidate in search.get('candidates', [])]
    plausible = [a for a in audits if a['classification']=='plausible_unverified']
    # Preserve ties; ordering is presentation only, never evidence.
    plausible.sort(key=lambda a: (-len(a['supporting_evidence']), a['rank'], a['asin']))
    return dict(policy=POLICY, candidates=audits,
        selected_asin=plausible[0]['asin'] if plausible and (len(plausible)==1 or len(plausible[0]['supporting_evidence'])>len(plausible[1]['supporting_evidence'])) else None,
        selection_reason='Unique strongest explicit evidence lead; identity unverified' if plausible and (len(plausible)==1 or len(plausible[0]['supporting_evidence'])>len(plausible[1]['supporting_evidence'])) else 'Tied or insufficient explicit evidence; no arbitrary selection',
        plausible_asins=[a['asin'] for a in plausible], exact=False,
        row_classification=('plausible_unverified' if plausible else 'insufficient_evidence'
            if any(a['classification']=='insufficient_evidence' for a in audits)
            else 'all_retained_candidates_rejected' if audits
            else 'no_candidate_returned_by_bounded_search' if search.get('complete')
            else 'no_retained_candidate_search_incomplete'),
        unexamined_results=bool(search.get('more_results') or not search.get('complete')))
