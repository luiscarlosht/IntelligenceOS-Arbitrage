"""Source-bound restriction-only pilot; preparation and validation never read credentials."""
import argparse
import hashlib
import json
from pathlib import Path

from app import amazon_candidate_enrichment as engine
from app.amazon_catalog import MARKETPLACE


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(source, evidence, asins, protected, *, identity_review=None,
            stop_after_no_restrictions=None):
    """Bind exact saved target bytes, negative evidence and original provenance files."""
    source, evidence = Path(source), Path(evidence)
    targets = {t['asin']: t for t in json.loads(source.read_text())}
    negative = json.loads(evidence.read_text())
    excluded = {r['asin'] for r in negative['excluded_targets']}
    reviewed = identity_review is not None
    if not 1 <= len(asins) <= (20 if reviewed else 10) or len(set(asins)) != len(asins):
        raise ValueError('Unique saved ASINs within the reviewed 10/20 target ceiling required')
    selected = [targets[a] for a in asins]
    if any(t['asin'] in excluded or (t.get('brand') or '').casefold() in ('sharpie', 'sanford')
           or not t.get('identifiers') for t in selected):
        raise ValueError('Excluded, ambiguous or incomplete target')
    if not reviewed and any(not t.get('brand') or t['historical_metrics']['mapping_issues'] for t in selected):
        raise ValueError('Excluded, ambiguous or incomplete target')
    if not reviewed and len({t['brand'].casefold() for t in selected}) != len(selected):
        raise ValueError('Distinct brands required for this reviewed pilot')
    if reviewed:
        if type(stop_after_no_restrictions) is not int or stop_after_no_restrictions != 3:
            raise ValueError('Reviewed screening stops after exactly three no-restriction results')
        review = json.loads(Path(identity_review).read_text())
        records = review['targets']
        if [r['asin'] for r in records] != asins:
            raise ValueError('Exact ordered identity review required')
        allowed_issues = {'Package hierarchy requires source verification', 'Variation theme values incomplete'}
        for t, r in zip(selected, records, strict=True):
            target_hash = hashlib.sha256(json.dumps(t, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            issues = t['historical_metrics']['mapping_issues']
            ids = t['identifiers']
            if (r['target_sha256'] != target_hash or r.get('identity_supported') is not True
                    or r.get('unresolved_identity_contradictions') != []
                    or r.get('reviewed_mapping_issues') != issues or set(issues) - allowed_issues
                    or not r.get('pack') or not r.get('category') or not r.get('review_rationale')
                    or not r.get('brand_label') or not t.get('model')
                    or r['brand_label'].casefold() not in ' '.join(str(t.get(k) or '') for k in ('brand', 'manufacturer', 'title')).casefold()
                    or any(i.get('status') == 'conflicting' or i['kind'] not in ('UPC','EAN','GTIN')
                           or not i['value'].isdigit() or len(i['value']) not in (12,13,14) for i in ids)
                    or len({i['value'].zfill(14) for i in ids}) != 1):
                raise ValueError('Unsupported identity review or ambiguous identifiers')
            for field, value in t['exact_package_evidence'].items():
                if value.get('status') != 'conflicting':
                    continue
                if field not in ('included_components', 'material') or field not in r.get('multi_value_fields', {}):
                    raise ValueError('Unresolved identity contradiction')
                values = value['evidence']
                if (len({(v['observed_at'], v['provenance']) for v in values}) != 1
                        or r['multi_value_fields'][field] != [v['value'] for v in values]):
                    raise ValueError('Multi-value array review must preserve same-source values')
    elif stop_after_no_restrictions is not None:
        raise ValueError('Early stop requires a bound identity review')
    result = dict(schema=2 if reviewed else 1, mode='saved_target_restrictions_only', source=str(source.resolve()),
        source_sha256=digest(source), exclusion_evidence=str(evidence.resolve()),
        exclusion_evidence_sha256=digest(evidence),
        protected_inputs={str(Path(p).resolve()): digest(p) for p in sorted(protected)},
        asins=asins, targets=selected, marketplace_id=MARKETPLACE, condition='new_new',
        seller_reference='operator-intended-account',
        authentication=dict(method='POST', url='https://api.amazon.com/auth/o2/token'),
        requests=[dict(asin=t['asin'], target_id=t['target_id'], method='GET',
            path='/listings/2021-08-01/restrictions', params=dict(asin=t['asin'],
                marketplaceIds=MARKETPLACE, conditionType='new_new', reasonLocale='en_US',
                sellerId='[private operator entry]')) for t in selected],
        budget=dict(authentication=1, restrictions=len(selected), pricing=0, fees=0,
                    catalog=0, retailer=0, maximum_requests=1+len(selected), retries=0),
        deadline_seconds=120, pagination=False, execution_authorized=False, live_requests=0,
        fulfillment_eligibility=None, purchase_approved=False)
    if reviewed:
        result.update(identity_review=str(Path(identity_review).resolve()),
            identity_review_sha256=digest(identity_review), stop_after_no_restrictions=3,
            sourcing_document_acceptability=None)
    return result


def validate(path, expected_sha256, maximum):
    if digest(path) != expected_sha256:
        raise ValueError('Manifest checksum mismatch')
    manifest = json.loads(Path(path).read_text())
    expected = prepare(manifest['source'], manifest['exclusion_evidence'], manifest['asins'],
                       manifest['protected_inputs'], identity_review=manifest.get('identity_review'),
                       stop_after_no_restrictions=manifest.get('stop_after_no_restrictions'))
    if manifest != expected:
        raise ValueError('Manifest/source/evidence/scope mismatch')
    if type(maximum) is not int or maximum != manifest['budget']['maximum_requests']:
        raise ValueError('Exact reviewed request ceiling required')
    return manifest


def execute(path, expected_sha256, maximum, private_path=engine.pilot.DIRECTORY, **dependencies):
    m = validate(path, expected_sha256, maximum)
    # Reuse existing exclusive report reservation, durable per-attempt checkpoints,
    # hidden seller entry, credential loader and shared quota/cooldown pacer.
    internal = dict(m, saved_report_sha256=expected_sha256, requests=[dict(
        asin=r['asin'], seller_reference=m['seller_reference'], pricing={},
        restrictions=dict(path=r['path'], params=r['params'])) for r in m['requests']])
    rows = [dict(asin=r['asin'], target_id=r['target_id'], marketplace_id=MARKETPLACE,
        condition='new_new', seller_reference=m['seller_reference'],
        pricing=dict(status='not_requested', data=None), fees=dict(status='not_requested', data=None),
        restrictions=dict(status='not_attempted', data=None), fulfillment_eligibility=None)
        for r in m['requests']]
    return engine._execute(internal, private_path,
        operations={a: ('restrictions',) for a in m['asins']}, request_limit=maximum,
        stem='saved-target-restrictions-'+expected_sha256+'-01',
        initial_report=dict(rows=rows, source_bound_manifest=m, sourcing_document_acceptability=None),
        stop_after_no_restrictions=m.get('stop_after_no_restrictions'), **dependencies)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('validate', 'run'))
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--max-requests', type=int, required=True)
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    if (args.action == 'run') != args.execute:
        p.error('run requires --execute; validate must not execute')
    try:
        manifest = validate(args.manifest, args.sha256, args.max_requests)
        if args.action == 'validate':
            print(json.dumps(dict(status='validated_offline', budget=manifest['budget'], live_requests=0)))
            return 0
        report = execute(args.manifest, args.sha256, args.max_requests)
        outcomes = {r['asin']: r['restrictions']['status'] for r in report['rows']}
        print(json.dumps(dict(restriction_outcomes=outcomes, attempts=len(report['attempts']),
                              no_restrictions_asins=report.get('no_restrictions_asins', []),
                              stop_reason=report.get('stop_reason'),
                              sourcing_document_acceptability=None,
                              fulfillment_eligibility=None, purchase_approved=False)))
        return 0 if (report.get('stop_reason') == 'listing_permission_goal_reached'
                     or all(s == 'succeeded' for s in outcomes.values())) else 1
    except (Exception, KeyboardInterrupt):
        print('Stopped without retry; inspect the private reserved report. No automatic replay.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
