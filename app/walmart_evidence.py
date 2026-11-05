"""M87 saved Walmart observations → M86. Offline only; no live executor."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile

from app.amazon_evaluation import MODES, SCENARIOS
from app.evidence_io import digest, offline, pinned, publication, json_write, safe
from app.observations import fingerprint
from app.product_analysis import comparison, workbook

US = 'ATVPDKIKX0DER'
ACQUISITION = ('purchase', 'retailer_shipping', 'sales_tax', 'inbound_shipping',
               'preparation', 'packaging', 'other_cost')
IDENTITY = ('walmart_item_id', 'url', 'title', 'brand', 'gtin', 'model', 'size',
            'pack_quantity', 'variation', 'observed_at', 'source_reference')


def agent_export(saved: dict) -> dict:
    """Import the existing Walmart Agent/Sheets text-row export, with no Sheets access.

    A newly authorized Agent run may save the same format for later offline import.
    Missing identity/verification/cost data remains unknown, never inferred.
    """
    from app.sheets_intake import product
    rows = saved.get('rows')
    if saved.get('schema') != 'walmart_agent_saved_export_v1' or not isinstance(rows, list) or len(rows) != 6:
        raise ValueError('Six saved Agent rows required')
    observations = []
    for row in rows:
        product(row)  # Reuse raw/export consistency, URL, price and timestamp checks.
        metadata = dict(source=row['source'], source_reference='saved Agent record '+row['record_id'],
                        observed_at=row['observed_at_utc'], confidence='UNKNOWN', verified=False)
        identity = dict(metadata, walmart_item_id=row['walmart_item_id'], url=row['product_url'],
                        title=row['title'], brand=row['brand'] or 'UNKNOWN', variation=row['selected_variant'] or 'UNKNOWN',
                        gtin='UNKNOWN', model='UNKNOWN', size='UNKNOWN', pack_quantity='UNKNOWN')
        acquisition = {key: dict(value='UNKNOWN') for key in ACQUISITION}
        for key, field in [('purchase', 'item_price_usd'), ('retailer_shipping', 'shipping_charge_usd')]:
            acquisition[key] = dict(metadata, value=row[field] or 'UNKNOWN', currency='USD')
        observations.append(dict(source_candidate_id=row['record_id'], walmart_product=identity,
            acquisition=acquisition, original_agent_row=deepcopy(row)))
    return dict(schema='walmart_pilot_batch_v1', batch_kind='NEW_PILOT',
                other_cost_basis='excludes_retailer_shipping', observations=observations)


def normalize(batch: dict) -> dict:
    """Stable content-addressed import. Never choose between conflicting evidence."""
    if batch.get('schema') != 'walmart_pilot_batch_v1' or batch.get('batch_kind') not in ('NEW_PILOT', 'SYNTHETIC_DEMO'):
        raise ValueError('Explicit new pilot label required; historical recovery is separate')
    rows = batch.get('observations')
    if not isinstance(rows, list) or len(rows) != 6:
        raise ValueError('Exactly six saved observations required')
    ids = [r.get('source_candidate_id') for r in rows]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != 6:
        raise ValueError('Unique original source candidate IDs required')
    if batch.get('other_cost_basis') != 'excludes_retailer_shipping':
        raise ValueError('Explicit shipping exclusion required to prevent double counting')
    content = deepcopy(batch)
    content.pop('batch_id', None)
    batch_id = 'M87-' + fingerprint(content)
    if batch.get('batch_id', batch_id) != batch_id:
        raise ValueError('Batch ID/content conflict')
    candidates = []
    for row in rows:
        product = deepcopy(row.get('walmart_product', {}))
        item = product.get('walmart_item_id')
        if not isinstance(item, str) or not re.fullmatch(r'[0-9]{1,30}', item):
            raise ValueError('Original Walmart item ID required')
        if sum(r.get('walmart_product', {}).get('walmart_item_id') == item for r in rows) != 1:
            raise ValueError('Duplicate Walmart item observations require explicit conflict resolution')
        amazon = deepcopy(row.get('amazon', {}))
        record = dict(candidate_id=row['source_candidate_id'], asin=amazon.get('asin'),
                      identity=dict(retailer_product=product, amazon_product=amazon.get('product', {})),
                      eligibility=amazon.get('eligibility', {'status': 'UNKNOWN'}),
                      market=amazon.get('market', {}), financials={},
                      is_synthetic=batch['batch_kind'] == 'SYNTHETIC_DEMO',
                      batch_id=batch_id, batch_kind=batch['batch_kind'],
                      original_observation_sha256=fingerprint(row), missing_source_fields=[], input_conflicts=[])
        record['missing_source_fields'] = [k for k in IDENTITY if product.get(k) in (None, '', 'UNKNOWN')]
        if row.get('conflicting_observations'):
            record['input_conflicts'].append('conflicting Walmart observations require resolution')
        for mode in MODES:
            record['financials'][mode] = {}
            for scenario in SCENARIOS:
                values = deepcopy(amazon.get('financials', {}).get(mode, {}).get(scenario, {}))
                acquisition = row.get('acquisition', {})
                for key in ACQUISITION:
                    if key in values and values[key] != acquisition.get(key):
                        record['input_conflicts'].append(f'{mode}.{scenario}.{key}')
                    values[key] = deepcopy(acquisition.get(key, {'value': 'UNKNOWN'}))
                record['financials'][mode][scenario] = values
        candidates.append(record)
    return dict(schema='walmart_product_analysis_input_v1', expected_candidates=6,
                batch_id=batch_id, batch_kind=batch['batch_kind'], candidates=candidates,
                source_inventory=batch.get('source_inventory', []), recovery_blockers=[
                    'Original historical six remain unrecovered. This is an explicitly new batch.'])


def preview(manifest: dict) -> dict:
    """Exact bounded request proposal only. No credentials, transport or approval bypass."""
    requests, unresolved = [], []
    for row in manifest['candidates']:
        asin = row.get('asin')
        if not isinstance(asin, str) or not re.fullmatch(r'B[A-Z0-9]{9}', asin):
            unresolved.append(row['candidate_id']); continue
        common = dict(candidate_id=row['candidate_id'], asin=asin)
        requests.append(dict(common, method='GET', path=f'/catalog/2022-04-01/items/{asin}',
            query=dict(marketplaceIds=US, includedData='identifiers,attributes,relationships,summaries,salesRanks')))
        requests.append(dict(common, method='GET', path=f'/products/pricing/v0/items/{asin}/offers',
            query=dict(MarketplaceId=US, ItemCondition='New', CustomerType='Consumer')))
        for mode in MODES:
            for scenario in SCENARIOS:
                price = row['financials'][mode][scenario].get('selling_price', {})
                if price.get('value') in (None, '', 'UNKNOWN'): continue
                requests.append(dict(common, method='POST', path=f'/products/fees/v0/items/{asin}/feesEstimate',
                    scenario=scenario, body={'FeesEstimateRequest': dict(MarketplaceId=US,
                    IsAmazonFulfilled=mode == 'FBA', Identifier=f'{row["candidate_id"]}:{mode}:{scenario}',
                    PriceToEstimateFees=dict(ListingPrice=dict(CurrencyCode='USD', Amount=price['value']),
                        Shipping=dict(CurrencyCode='USD', Amount='0')))}))
    return dict(schema='m87_execution_preview_v1', batch_id=manifest['batch_id'],
        candidates=[dict(candidate_id=r['candidate_id'], asin=r.get('asin')) for r in manifest['candidates']],
        requests=requests, unresolved=unresolved, maximum_requests=len(requests)+1,
        authentication=dict(method='POST', host='api.amazon.com', path='/auth/o2/token', maximum_requests=1),
        api_host='sellingpartnerapi-na.amazon.com', marketplace=US, condition='New',
        permissions=['Product Listing (Catalog)', 'Pricing', 'Amazon Fulfillment (Fees); verify applicable account roles before approval'],
        rate_policy='Sequential; catalog >=1s, pricing >=2s, fees >=1s; honor stricter returned limits',
        retry_policy=dict(retries=0, refreshes=0, pagination=0, timeout_seconds=30),
        evidence_destination='NEW private owner-only batch directory; raw receipts plus SHA256; never overwrite',
        estimated_provider_cost='UNKNOWN: verify current account/API charges before approval; no paid provider enabled',
        stop_conditions=['No explicit owner approval of exact manifest SHA256', 'Unresolved ASIN or variant',
                         '401/403/429 or any request failure', 'Budget, scope, price basis or evidence integrity drift'],
        approval_required=True, live_executor_available=False, purchase_authorized=False)


def execute_live(*args, **kwargs):
    raise PermissionError('M87 live execution disabled. Owner-approved manifest and reviewed executor required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--as-of')
    args = parser.parse_args()
    path = safe(args.input)
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    with publication(args.output, [path]) as stage:
        previous = tempfile.tempdir
        try:
            tempfile.tempdir = str(stage)
            with offline(reads=[path], writes=[stage]):
                batch = pinned(path, args.sha256)
                manifest = normalize(agent_export(batch) if batch.get('schema') == 'walmart_agent_saved_export_v1' else batch)
                manifest['source_inventory'] = list(manifest['source_inventory']) + [
                    dict(path=str(path), sha256=args.sha256, role='original saved batch')]
                report = comparison(manifest, now)
                report.update(batch_id=manifest['batch_id'], batch_kind=manifest['batch_kind'],
                              original_recovery_status='INCOMPLETE',
                              recovery_status=manifest['batch_kind']+'_COMPLETE')
                for name, value in [('normalized.json', manifest), ('execution-preview.json', preview(manifest)),
                                    ('comparison.json', report)]:
                    json_write(stage/name, value)
                workbook(report, stage/'comparison.xlsx')
                if digest(path) != args.sha256:
                    raise ValueError('Source drift during import')
        finally:
            tempfile.tempdir = previous


if __name__ == '__main__':
    main()
