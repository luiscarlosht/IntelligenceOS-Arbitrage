from app.pipeline import evaluate

def test_roi_and_profit():
    row=dict(source='test',product='widget',upc='123',source_url='',amazon_asin='',destination='Amazon',buy_cost='8',sale_price='25',referral_fee='3.75',fulfillment_fee='4.5',inbound_shipping='1.25',other_cost='0.5',eligible='yes',exact_match='yes')
    r=evaluate(row)
    assert r['profit']==7.0
    assert r['status']=='REVIEW'

def test_eligibility_gate():
    row=dict(buy_cost='8',sale_price='25',referral_fee='3.75',fulfillment_fee='4.5',inbound_shipping='1.25',other_cost='0.5',eligible='no',exact_match='yes')
    assert evaluate(row)['status']=='REJECT'
