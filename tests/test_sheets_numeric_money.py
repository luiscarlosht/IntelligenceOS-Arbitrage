"""Browser JSON money can be numeric without changing literal exported evidence."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from app.sheets_intake import FIELDS, BATCH_FIELDS, ValidationFailure, process, product
from test_sheets_intake import fixture


def browser_row(price=24.86, exported='24.86', shipping=None, exported_shipping=''):
    row, batch = fixture()
    row.update(item_price_usd=exported, shipping_charge_usd=exported_shipping)
    raw = {k:v for k,v in row.items() if k != 'raw_record_json'}
    raw['displayed_price'] = price; del raw['item_price_usd']
    raw['shipping_charge'] = shipping; del raw['shipping_charge_usd']
    raw['observation_timestamp'] = raw.pop('observed_at_utc')
    row['raw_record_json'] = json.dumps(raw)
    return row, batch


@pytest.mark.parametrize('price,exported', [
    (24.86,'24.86'), (12.84,'12.84'), (9.97,'9.97'), (15.82,'15.82'),
    (5.47,'5.47'), (1.68,'1.68'), (2.32,'2.32'), (7.78,'7.78'), (9.94,'9.94'),
    (50,'50.00'), ('Now $50.00','50.00'), ('$24.86','24.860'),
])
def test_equivalent_browser_prices_preserve_original_row(price,exported):
    row,_=browser_row(price,exported)
    before=deepcopy(row)
    result=product(row)
    assert row == before
    assert result.purchase_price == Decimal(exported)
    assert result.source_context['source_shipping_cost'] is None


def test_numeric_shipping_is_exact_not_inferred_free():
    row,_=browser_row(shipping=2.5,exported_shipping='2.50')
    assert product(row).source_context['source_shipping_cost']==Decimal('2.50')
    row['shipping_charge_usd']='0'
    with pytest.raises(ValidationFailure): product(row)


@pytest.mark.parametrize('price', [True,False,None,-1,[],{},'About $24.86','24.86 or 25.00'])
def test_nonmonetary_or_ambiguous_price_still_rejects(price):
    row,_=browser_row(price)
    with pytest.raises(ValidationFailure): product(row)


@pytest.mark.parametrize('shipping', ['Free','Free with Walmart+','Free over $35','Calculated at checkout'])
@pytest.mark.parametrize('exported_shipping', ['', '0', 'Free'])
def test_shipping_descriptions_are_not_numeric_charge(shipping,exported_shipping):
    row,_=browser_row(shipping=shipping,exported_shipping=exported_shipping)
    with pytest.raises(ValidationFailure): product(row)


def test_conflicting_price_does_not_choose_a_value():
    row,_=browser_row(24.86,'24.87')
    with pytest.raises(ValidationFailure,match='RAW_EXPORT_MISMATCH'): product(row)
    row,_=browser_row(24.86)
    raw=json.loads(row['raw_record_json']);raw['item_price_usd']='99.99'
    row['raw_record_json']=json.dumps(raw)
    with pytest.raises(ValidationFailure,match='RAW_EXPORT_MISMATCH'): product(row)


def test_json_decimal_lexeme_is_not_rounded_to_fit_export():
    row,_=browser_row(24.86)
    row['raw_record_json']=row['raw_record_json'].replace('"displayed_price": 24.86', '"displayed_price": 24.8600000000000000001')
    with pytest.raises(ValidationFailure,match='RAW_EXPORT_MISMATCH'): product(row)
    for literal in ('NaN', 'Infinity', '-Infinity'):
        row,_=browser_row(24.86)
        row['raw_record_json']=row['raw_record_json'].replace('"displayed_price": 24.86','"displayed_price": '+literal)
        with pytest.raises(ValidationFailure): product(row)


def test_readonly_batch_validation_never_acknowledges_or_mutates():
    row,batch=browser_row()
    snapshot={'Walmart_Intake':[FIELDS,[row[k] for k in FIELDS]],'Walmart_Batches':[BATCH_FIELDS,batch]}
    before=deepcopy(snapshot)
    class Client:
        def read(self,tab,_):return deepcopy(snapshot[tab])
        def ack(self,*_):pytest.fail('Read-only check must not acknowledge')
    result=process(Client())
    assert result['accepted']==1 and result['rejected']==0
    assert snapshot==before
