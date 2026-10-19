/**
 * Cockpit API Client — Thin fetch wrapper for all Cockpit endpoints.
 */

async function _handleError(res, defaultMsg) {
    let detail = '';
    try {
        const data = await res.json();
        if (data && data.detail) {
            if (typeof data.detail === 'string') {
                detail = data.detail;
            } else if (Array.isArray(data.detail)) {
                detail = data.detail.map(e => {
                    const loc = (e.loc || []).join('.');
                    return loc ? `${loc}: ${e.msg}` : e.msg;
                }).join('; ');
            } else {
                detail = JSON.stringify(data.detail);
            }
        }
    } catch (_) {}
    const msg = detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status}: ${defaultMsg}`;
    throw new Error(msg);
}

const API = {
    async getStatus() {
        const res = await fetch('/api/status');
        if (!res.ok) await _handleError(res, 'Failed to fetch status');
        return await res.json();
    },

    async refreshDataset(symbols = null, symbolLimit = null, provider = null, background = null, forceRefreshBars = false) {
        const payload = {};
        if (symbols) payload.symbols = symbols;
        if (symbolLimit) payload.symbol_limit = symbolLimit;
        if (provider) payload.provider = provider;
        if (background !== null) payload.background = background;
        if (forceRefreshBars) payload.force_refresh_bars = forceRefreshBars;

        const res = await fetch('/api/dataset/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) await _handleError(res, 'Failed to refresh dataset');
        return await res.json();
    },


    async getTable(columns = null) {
        const url = columns ? `/api/table?columns=${encodeURIComponent(columns)}` : '/api/table';
        const res = await fetch(url);
        if (!res.ok) await _handleError(res, 'Failed to fetch table');
        return await res.json();
    },

    async runScreen(screenRequest, signal = null) {
        const fetchOpts = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(screenRequest)
        };
        if (signal) {
            fetchOpts.signal = signal;
        }
        const res = await fetch('/api/screen', fetchOpts);
        if (!res.ok) await _handleError(res, 'Failed to run screen');
        return await res.json();
    },

    async getScreenProgress(requestId) {
        const res = await fetch(`/api/screen/progress/${encodeURIComponent(requestId)}`);
        if (!res.ok) await _handleError(res, 'Failed to fetch screen progress');
        return await res.json();
    },

    async cancelScreen(requestId) {
        const res = await fetch(`/api/screen/cancel/${encodeURIComponent(requestId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!res.ok) await _handleError(res, 'Failed to cancel screen');
        return await res.json();
    },

    async getStrategies(includeUser = true) {
        const url = includeUser ? '/api/strategies?include_user=true' : '/api/strategies';
        const res = await fetch(url);
        if (!res.ok) await _handleError(res, 'Failed to fetch strategies');
        return await res.json();
    },

    async getStrategyDetail(name) {
        const res = await fetch(`/api/strategies/${encodeURIComponent(name)}`);
        if (!res.ok) await _handleError(res, `Failed to fetch strategy detail for '${name}'`);
        return await res.json();
    },

    async getUserPresets() {
        const res = await fetch('/api/user-presets');
        if (!res.ok) await _handleError(res, 'Failed to fetch user presets');
        return await res.json();
    },

    async saveUserPreset(presetData) {
        const res = await fetch('/api/user-presets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(presetData)
        });
        if (!res.ok) await _handleError(res, 'Failed to save preset');
        return await res.json();
    },

    async deleteUserPreset(name) {
        const res = await fetch(`/api/user-presets/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        if (!res.ok) await _handleError(res, `Failed to delete preset '${name}'`);
        return await res.json();
    },

    async getStockPanel(symbol) {
        const res = await fetch(`/api/panel/${encodeURIComponent(symbol)}`);
        if (!res.ok) await _handleError(res, `Failed to fetch analysis panel for '${symbol}'`);
        return await res.json();
    },

    async runStrategy(strategyName, limit = null, columns = null) {
        const res = await fetch('/api/strategy/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                strategy_name: strategyName,
                limit: limit,
                columns: columns
            })
        });
        if (!res.ok) await _handleError(res, 'Failed to run strategy');
        return await res.json();
    },

    async getCandles(symbol, tf = 'D', bandTf = null, exchange = 'NSE', years = 2) {
        let url = `/api/candles/${encodeURIComponent(symbol)}?tf=${encodeURIComponent(tf)}&exchange=${encodeURIComponent(exchange)}&years=${years}`;
        if (bandTf !== null && bandTf !== undefined && bandTf !== '') {
            url += `&band_tf=${encodeURIComponent(bandTf)}`;
        }
        const res = await fetch(url);
        if (!res.ok) await _handleError(res, 'Failed to fetch candles');
        return await res.json();
    },

    async getBands(symbol) {
        const res = await fetch(`/api/bands/${encodeURIComponent(symbol)}`);
        if (!res.ok) await _handleError(res, 'Failed to fetch bands');
        return await res.json();
    },

    async updateBand(symbol, timeframe, value) {
        const res = await fetch(`/api/bands/${encodeURIComponent(symbol)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timeframe, value: parseFloat(value) })
        });
        if (!res.ok) await _handleError(res, 'Failed to update band');
        return await res.json();
    },

    async getBandLog(symbol = null, limit = 60) {
        const hasSymbol = symbol !== null && symbol !== undefined && String(symbol).trim() !== '';
        const url = hasSymbol
            ? `/api/bands/log/${encodeURIComponent(symbol)}?limit=${limit}`
            : `/api/bands/log?limit=${limit}`;
        const res = await fetch(url);
        if (!res.ok) await _handleError(res, hasSymbol ? `Failed to fetch band history for '${symbol}'` : 'Failed to fetch global band history');
        return await res.json();
    },

    async getGlobalBandLog(limit = 100) {
        return await this.getBandLog(null, limit);
    },

    async getBandBackups() {
        const res = await fetch('/api/bands/backups');
        if (!res.ok) await _handleError(res, 'Failed to fetch band backups');
        return await res.json();
    },

    async restoreBandBackup(filename) {
        const res = await fetch(`/api/bands/restore/${encodeURIComponent(filename)}`, {
            method: 'POST'
        });
        if (!res.ok) await _handleError(res, `Failed to restore band backup '${filename}'`);
        return await res.json();
    },

    async getMetadata(symbol, exchange = 'NSE') {
        const res = await fetch(`/api/meta/${encodeURIComponent(symbol)}?exchange=${encodeURIComponent(exchange)}`);
        if (!res.ok) await _handleError(res, `Failed to fetch metadata for '${symbol}'`);
        return await res.json();
    },

    async updateMetadata(symbol, field, value, exchange = 'NSE') {
        const res = await fetch(`/api/meta/${encodeURIComponent(symbol)}?exchange=${encodeURIComponent(exchange)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ field, value })
        });
        if (!res.ok) await _handleError(res, `Failed to update metadata for '${symbol}'`);
        return await res.json();
    },

    async getRace({ symbols = null, anchor = '2021-01-01', top = 15, metric = 'SPA_A21', exchange = null } = {}) {
        let url = `/api/race?anchor=${encodeURIComponent(anchor)}&top=${top}&metric=${encodeURIComponent(metric)}`;
        if (symbols) url += `&symbols=${encodeURIComponent(symbols)}`;
        if (exchange) url += `&exchange=${encodeURIComponent(exchange)}`;
        const res = await fetch(url);
        if (!res.ok) await _handleError(res, 'Failed to fetch sprint race data');
        return await res.json();
    },

    async exportScreen(exportRequest, filename = 'yogi_export') {
        const res = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(exportRequest)
        });
        if (!res.ok) await _handleError(res, 'Failed to export');
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const ext = exportRequest.format || 'xlsx';
        a.download = `${filename}.${ext}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    },

    async getSettings() {
        const res = await fetch('/api/settings');
        if (!res.ok) await _handleError(res, 'Failed to fetch settings');
        return await res.json();
    },

    async updateSettings(settings) {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        if (!res.ok) await _handleError(res, 'Failed to update settings');
        return await res.json();
    }
};

window.API = API;
