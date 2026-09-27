"""Comprehensive Acceptance Verification Script for Step 11 Cockpit MVP."""

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from tests.cockpit.test_cockpit_api import AsgiTestClient


def main():
    app = create_app(app_state=AppState(), auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Static and Index
    res_index = client.get('/')
    assert res_index.status_code == 200, f'Index failed: {res_index.status_code}'
    assert 'YOGI COCKPIT' in res_index.text
    print('[PASS] 1. Index HTML served successfully')

    # 2. Status initially empty
    status = client.get('/api/status').json()
    assert status['universe_count'] == 0
    assert status['is_demo'] is False
    print('[PASS] 2. Initial system status verified: 0 stocks, is_demo=False')

    # 3. Load Demo Data
    refresh = client.post('/api/dataset/refresh', json={'provider': 'demo'}).json()
    assert refresh['universe_count'] == 5
    assert refresh['is_demo'] is True
    print('[PASS] 3. Demo dataset loaded: 5 golden stocks, is_demo=True')

    # 4. Table fetch
    table = client.get('/api/table').json()
    assert len(table['rows']) == 5
    symbols = [r['symbol'] for r in table['rows']]
    print(f'[PASS] 4. Table retrieved 5 stocks: {symbols}')
    first_row = table['rows'][0]
    print(f'   Sample metrics for {first_row["symbol"]}: Price={first_row.get("price")}, M_CUR={first_row.get("M_CUR")}, BANDST_M={first_row.get("BANDST_M")}')

    # 5. Screen with ranking_order='desc' and filter rules (proves 422 resolved)
    screen_res = client.post('/api/screen', json={
        'ranking_metric': 'M_CUR',
        'ranking_order': 'desc',
        'filter_group': {
            'match': 'all',
            'rules': [{'field': 'price', 'op': '>', 'value': 50.0}]
        },
        'limit': 10
    })
    assert screen_res.status_code == 200, f'Screen failed: {screen_res.status_code} {screen_res.text}'
    s_data = screen_res.json()
    print(f'[PASS] 5. Screen executed without 422: qualified={s_data["qualified_count"]}, selected={s_data["selected_count"]}')

    # 6. Multi-timeframe candles & bands for all 6 timeframes
    for tf in ('D', 'W', 'M', 'Q', 'H', 'Y'):
        c_res = client.get('/api/candles/MANYAVAR', params={'tf': tf, 'exchange': 'NSE', 'years': 2})
        assert c_res.status_code == 200
        c_data = c_res.json()
        assert len(c_data['candles']) > 0
        assert len(c_data['band_upper_curve']) > 0
    print('[PASS] 6. Candlestick & band envelope curves verified across all 6 timeframes: D, W, M, Q, H, Y')

    # 7. Discretionary band tuning
    b_update = client.put('/api/bands/MANYAVAR', json={'timeframe': 'M', 'value': 0.14}).json()
    assert b_update['value'] == 0.14
    b_get = client.get('/api/bands/MANYAVAR').json()
    assert b_get['bands']['M'] == 0.14
    print('[PASS] 7. Interactive band tuning verified: M band updated to 14%')

    # 8. Strategy preset execution
    strat_res = client.post('/api/strategy/run', json={'strategy_name': 'A1_IMPULSE_CONFIRMED'}).json()
    print(f'[PASS] 8. Strategy recipe A1_IMPULSE_CONFIRMED executed: qualified={strat_res["qualified_count"]}, selected={strat_res["selected_count"]}')

    # 9. Screen export
    exp_res = client.post('/api/export', json={'ranking_metric': 'M_CUR', 'ranking_order': 'desc', 'format': 'csv'})
    assert exp_res.status_code == 200
    assert 'Symbol' in exp_res.text or 'MANYAVAR' in exp_res.text
    print('[PASS] 9. Export CSV generated successfully')

    print('\n*** ALL ACCEPTANCE CHECKS PASSED PERFECTLY! ***')


if __name__ == '__main__':
    main()
