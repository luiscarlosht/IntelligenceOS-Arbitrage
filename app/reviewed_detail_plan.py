"""Prepare a source-bound shortlist plan from a saved offline review. No live I/O."""
import argparse
import json
from pathlib import Path

from app.observations import fingerprint
from app.catalog_saved_evidence import sha, saved_evidence, DETAIL_DATA
from app.sheets_candidate_plan import MARKETPLACE


def prepare(review_path: Path) -> dict:
    review = json.loads(review_path.read_text())
    for name, signature in review['protected_inputs'].items():
        path = Path(name)
        if sha(path) != signature['sha256'] or path.stat().st_mtime_ns != signature['mtime_ns']:
            raise ValueError('Protected saved evidence changed')
    reports = [Path(p) for p in review['protected_inputs'] if Path(p).name.startswith('candidates-') and p.endswith('.json')]
    reports = [p for p in reports if len(json.loads(p.read_text()).get('rows', [])) == 38]
    if len(reports) != 1:
        raise ValueError('One original search report required')
    report_path = reports[0]
    report = json.loads(report_path.read_text())
    if len(report['rows']) != 38 or report['status'] != 'succeeded':
        raise ValueError('Completed 38-row saved run required')
    paths = [Path(p) for p in review['protected_inputs'] if p.endswith('.json') and Path(p).name.startswith(('candidates-', 'candidate-details-'))]
    cache, blocked, _ = saved_evidence(paths)
    requests, reused = [], []
    shortlist = list(review['shortlist'])
    aaa = next(e for e in shortlist if e[4] == 'B004U42A28')
    if not any(e[4] == 'B0D51H9LQP' for e in shortlist):
        alternative = list(aaa)
        alternative[4] = 'B0D51H9LQP'
        shortlist.append(alternative)
    for entry in shortlist:
        ordinal, _, _, _, asin = entry[:5]
        row = next(r for r in report['rows'] if r['ordinal'] == ordinal)
        audit = next(r for r in review['rows'] if r['ordinal'] == ordinal)
        candidate = next(c for c in audit['candidates'] if c['asin'] == asin)
        if not any(c['asin'] == asin for c in row['search']['candidates']):
            raise ValueError('Candidate absent from saved search')
        binding = dict(asin=asin, source_fingerprint=fingerprint(row['source']),
            lineage=audit['lineage'], selection_reason=entry[8], candidate_audit=candidate,
            alternatives=audit['candidates'], exact=False)
        if asin in cache:
            reused.append(dict(**binding, detail=cache[asin]))
        elif asin in blocked or asin == 'B0000AQOAB':
            raise ValueError('Prior uncertain/attempted detail remains reserved')
        else:
            requests.append(dict(**binding, method='GET', path='/catalog/2022-04-01/items/'+asin,
                params=dict(marketplaceIds=MARKETPLACE, includedData=DETAIL_DATA, locale='en_US')))
    if len({r['asin'] for r in requests}) != len(requests):
        raise ValueError('Duplicate detail request')
    return dict(schema=1, action='offline_reviewed_shortlist_details', execution_authorized=False,
        live_requests=0, review=dict(path=str(review_path.resolve()), sha256=sha(review_path)),
        saved_report=dict(path=str(report_path), sha256=sha(report_path)),
        protected_inputs=review['protected_inputs'], reused_searches=38, reused_details=reused,
        requests=requests, budget=dict(authentication=int(bool(requests)), search=0, detail=len(requests),
            total=len(requests)+int(bool(requests)), retries=0, pagination=0, pricing=0, fees=0, restrictions=0),
        reservations='All existing operation reservations remain authoritative; revalidate complete evidence inventory and shared ledger before any future execution; never clear uncertain operations',
        purchase_approved=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.review)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
