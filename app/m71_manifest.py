"""Frozen Catalog-only proposal; no authentication, authorization or dispatch."""
from collections import Counter
from pathlib import Path
import re

from app.m65_intelligence import ASIN, US, sha256
from app.m69_history import consolidate
from app.m70_plan import plan
from app.observations import fingerprint

HOST='sellingpartnerapi-na.amazon.com'
PATH='/catalog/2022-04-01/items'
AUTH_URL='https://api.amazon.com/auth/o2/token'
CEILING=251
DATA=['summaries','identifiers','relationships','attributes','productTypes','classifications','dimensions']
# Search phrases are proposed human vocabulary, never product identity evidence.
INTENTS={
 'garden':('plant support clips','seed starting trays','garden plant labels','watering can rose','garden kneeling pad'),
 'pet_accessories':('pet grooming comb','pet food scoop','aquarium cleaning brush','bird cage perch','pet travel bowl'),
 'craft_supplies':('embroidery hoop','crochet stitch markers','beading storage tray','craft cutting mat','felting needle holder'),
 'kitchen_accessories':('silicone jar spatula','bamboo steamer liner','tea infuser basket','dough scraper','reusable baking liner'),
 'home_storage':('fabric drawer dividers','under shelf basket','vacuum storage bag','closet shelf separator','bedside storage caddy'),
 'office_accessories':('cable management sleeve','desk document tray','book binding rings','reusable notebook cover','desktop card holder'),
 'sports_accessories':('yoga mat strap','bicycle tire lever','swimming ear plug case','resistance band handles','camping utensil pouch'),
 'automotive_accessories':('car seat gap organizer','tire valve caps','microfiber applicator pad','car visor clip','automotive trim tool'),
 'hand_tools':('magnetic parts tray','precision screwdriver holder','sanding block','woodworking marking gauge','tool roll pouch'),
 'personal_care_accessories':('soap saver pouch','travel toothbrush case','silicone scalp brush','reusable shower cap','cosmetic brush holder'),
}


def implementation() -> dict:
    from app.m70_discovery import implementation as prior
    root=Path(__file__).parent
    return dict(prior(),**{n:sha256(root/n) for n in ('m71.py','m71_manifest.py','m71_adapter.py','m71_journal.py','amazon_pacing.py')})


def queries() -> list[dict]:
    # Round-robin intents: reaching the target early still spans the ten intents.
    return [dict(id=f'q{index*10+n+1:03}',category_intent=category,keywords=phrases[index],
                 classification_ids=[],product_type_filter=None)
            for index in range(5) for n,(category,phrases) in enumerate(INTENTS.items())]


def freeze(history: dict) -> dict:
    excluded=history['excluded_asins']
    original=sorted(set(history['original_m63_asins'])|set(history['original_m67_asins']))
    if (not history['history_complete'] or len(original)!=40 or not set(original)<=set(excluded)
            or excluded!=sorted(set(excluded)) or any(not ASIN.fullmatch(a) for a in excluded)):
        raise ValueError('Complete current immutable history required')
    pacing=plan()['configured_limits']
    result=dict(schema=1,mode='M71_CATALOG_PREPARATION_ONLY',execution_authorized=False,live_enabled=False,
        account_reference=history['account_reference'],marketplace=US,target_distinct_asins=1000,
        endpoint=dict(method='GET',host=HOST,path=PATH),authentication_endpoint=AUTH_URL,
        included_data=DATA,queries=queries(),maximum_pages_per_query=4,page_size=20,
        budget=dict(authentication=1,keyword=200,identifier=50,detail=0,total=CEILING,retries=0,
                    restrictions=0,pricing=0,fees=0,fba=0,retailer=0,offers=0,approvals=0,purchases=0),
        history_evidence_sha256=history['evidence_sha256'],excluded_asins=excluded,checked_eligibility_asins=original,
        history_sources=history['sources'],implementation_sha256=implementation(),pacing=pacing,
        classification_filter_status='No verified classification IDs in frozen inputs; intent labels are not service filters',
        product_type_filter_status='searchCatalogItems has no product-type query parameter; request productTypes as observed response data only',
        brand_policy='Unbranded queries; no brandNames filter or brand-wide permission inference',
        identifier_strategy='At most 50 one-page batches of up to 20 newly discovered, unclaimed ASINs, sorted; no extra pages or new discovery ASINs admitted',
        stop_policy='First failure, throttle, interruption, uncertain dispatch, invalid cursor or exhausted bound stops permanently; no resume',
        future_authorization='Fresh explicit owner authorization and separately reviewed live entry point required; proposal is not authorization')
    result['proposal_sha256']=fingerprint(result)
    return result


def validate(doc: dict,*,current_history: dict | None=None) -> None:
    copy=dict(doc);digest=copy.pop('proposal_sha256',None)
    if digest!=fingerprint(copy):raise ValueError('Frozen manifest content drift')
    if (doc.get('schema')!=1 or doc.get('mode')!='M71_CATALOG_PREPARATION_ONLY'
            or doc.get('execution_authorized') is not False or doc.get('live_enabled') is not False
            or doc.get('marketplace')!=US or doc.get('endpoint')!=dict(method='GET',host=HOST,path=PATH)
            or doc.get('authentication_endpoint')!=AUTH_URL or doc.get('queries')!=queries()
            or doc.get('included_data')!=DATA or doc.get('maximum_pages_per_query')!=4
            or doc.get('page_size')!=20 or doc.get('target_distinct_asins')!=1000
            or doc.get('implementation_sha256')!=implementation()):raise ValueError('Exact preparation contract required')
    expected=dict(authentication=1,keyword=200,identifier=50,detail=0,total=CEILING,retries=0,
                  restrictions=0,pricing=0,fees=0,fba=0,retailer=0,offers=0,approvals=0,purchases=0)
    if doc.get('budget')!=expected or any(type(v) is not int for v in doc['budget'].values()):raise ValueError('Absolute 251-request contract required')
    excluded=doc.get('excluded_asins',[]);checked=doc.get('checked_eligibility_asins',[])
    if (not isinstance(excluded,list) or excluded!=sorted(set(excluded)) or len(checked)!=40
            or len(set(checked))!=40 or not set(checked)<=set(excluded)
            or any(not isinstance(a,str) or not ASIN.fullmatch(a) for a in excluded)):
        raise ValueError('Permanent exclusions cannot be relaxed')
    if current_history is not None and doc!=freeze(current_history):raise ValueError('Current history/configuration drift')
    rate=doc['pacing']['search_rps_cap'];headroom=doc['pacing']['headroom']
    if not 0<rate<=2 or not 0<headroom<1:raise ValueError('Bounded conservative pacing required')


def prepare(private: Path,store: Path,manifest: Path,digest: str) -> dict:
    # No discovery/identity engine re-run; use unchanged M69's read-only history.
    return freeze(consolidate(private,store,manifest,digest,[]))


def preview(doc: dict) -> str:
    validate(doc)
    lines=['# M71 frozen Catalog request proposal',f"Proposal SHA-256: {doc['proposal_sha256']}",
        'PREPARATION ONLY — no execution or authorization.',
        f"US marketplace: {US}; permanently excluded ASINs: {len(doc['excluded_asins'])}; checked eligibility ASINs: 40.",
        '50 keyword queries, 10 category intents, 4 pages/query, page size 20.',
        'Ceiling: 1 authentication + 200 keyword pages + 50 identifier batches = 251 requests.',
        'No details, retries, eligibility, pricing, fees, FBA, offers, purchases or approvals.',
        'Category labels are intent only; classification IDs unavailable; no supported product-type search filter.',
        f"Frozen search cap {doc['pacing']['search_rps_cap']} RPS × headroom {doc['pacing']['headroom']}.",
        '', '| Query | Category intent | Exact keyword phrase | Proposed request slots |',
        '|---|---|---|---|']
    for i,q in enumerate(doc['queries']):
        slots=', '.join(str(2+page*50+i) for page in range(4))
        lines.append(f"| {q['id']} | {q['category_intent']} | {q['keywords']} | {slots} |")
    lines+=['','Slot 1: POST '+AUTH_URL+' (credentials private; never printed).',
        'Slots 2–201: GET https://'+HOST+PATH+'; round-robin query pass, then subsequent pages.',
        'Every keyword request has marketplaceIds='+US+', pageSize=20, includedData='+','.join(DATA)+'.',
        'pageToken is absent initially; subsequent pages require the exact private prior response cursor.',
        'Slots 202–251: conditional identifier batches; identifiersType=ASIN; at most 20 sorted newly discovered unclaimed ASINs/batch.',
        'Identifier ASINs cannot be frozen before discovery. Batch algorithm is frozen; actual values require checkpoint evidence.',
        'Skipped/terminal query pages are unused budget, never reassigned. No guarantee of 1,000 distinct products.',
        'Raw keyword results can include excluded ASINs; retain evidence but never admit them to candidates or identifier requests.',
        'Separate fresh explicit authorization and reviewed live entry point are mandatory.']
    return '\n\n'.join(lines)+'\n'
