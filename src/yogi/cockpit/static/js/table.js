/**
 * Cockpit Table Controller — Dynamic tabular presentation of QueryResultOut.
 *
 * Implements high-information density, interactive sorting, prototype pill strips,
 * and responsive selection highlight.
 */

class CockpitTable {
    constructor(tableId, onRowSelect) {
        this.table = document.getElementById(tableId);
        this.theadRow = document.getElementById('tableHeadRow');
        this.tbody = document.getElementById('tableBody');
        this.onRowSelect = onRowSelect;
        this.columns = [];
        this.rawRows = [];
        this.displayRows = [];
        this.activeSymbol = null;
        this.currentFilterQuery = '';
        this.sortCol = null;
        this.sortAsc = true;
        this.secondarySortCol = null;
    }

    setSecondarySort(colKey) {
        this.secondarySortCol = colKey || null;
        this._applySortAndFilter();
    }

    render(payload) {
        if (!payload || !this.theadRow || !this.tbody) return;

        this.columns = payload.columns || [];
        this.rawRows = [...(payload.rows || [])];
        this.displayRows = [...this.rawRows];

        this._renderHeaders();
        this._applySortAndFilter();
    }

    _renderHeaders() {
        this.theadRow.innerHTML = '';
        this.columns.forEach(col => {
            const th = document.createElement('th');
            th.className = 'sortable-th';
            const label = col.label || col.key;

            let sortIndicator = '';
            if (this.sortCol === col.key) {
                sortIndicator = this.sortAsc ? ' <span class="sort-icon">▲</span>' : ' <span class="sort-icon">▼</span>';
            }

            th.innerHTML = `<span class="th-content">${this._escapeHtml(label)}${sortIndicator}</span>`;
            th.title = `${col.key} (${col.category || 'Metric'})\nClick to sort`;

            th.addEventListener('click', () => {
                if (this.sortCol === col.key) {
                    this.sortAsc = !this.sortAsc;
                } else {
                    this.sortCol = col.key;
                    this.sortAsc = col.is_numeric !== false ? false : true;
                }
                this._renderHeaders();
                this._applySortAndFilter();
            });
            this.theadRow.appendChild(th);
        });
    }

    _applySortAndFilter() {
        let rows = [...this.rawRows];

        // 1. Text filter
        if (this.currentFilterQuery) {
            const q = this.currentFilterQuery.toLowerCase();
            rows = rows.filter(r => {
                for (const k of Object.keys(r)) {
                    const v = r[k];
                    if (v !== null && v !== undefined && String(v).toLowerCase().includes(q)) {
                        return true;
                    }
                }
                return false;
            });
        }

        // 2. Client-side sort
        if (this.sortCol) {
            const col = this.sortCol;
            const asc = this.sortAsc;
            const secCol = this.secondarySortCol;
            rows.sort((a, b) => {
                const va = a[col];
                const vb = b[col];
                if (va !== vb) {
                    if (va === null || va === undefined) return 1;
                    if (vb === null || vb === undefined) return -1;
                    if (typeof va === 'number' && typeof vb === 'number') {
                        return asc ? va - vb : vb - va;
                    }
                    const sa = String(va);
                    const sb = String(vb);
                    return asc ? sa.localeCompare(sb) : sb.localeCompare(sa);
                }

                // Primary is equal -> Secondary tie-breaker
                if (secCol && a[secCol] !== undefined && b[secCol] !== undefined && a[secCol] !== b[secCol]) {
                    const sva = a[secCol];
                    const svb = b[secCol];
                    if (sva === null || sva === undefined) return 1;
                    if (svb === null || svb === undefined) return -1;
                    if (typeof sva === 'number' && typeof svb === 'number') {
                        return svb - sva; // Default secondary sort is descending (highest value first)
                    }
                    return String(sva).localeCompare(String(svb));
                }

                // Deterministic fallback by symbol
                return String(a['symbol'] || '').localeCompare(String(b['symbol'] || ''));
            });
        }

        this.displayRows = rows;
        this._renderBody();
    }

    _renderBody() {
        this.tbody.innerHTML = '';
        if (this.displayRows.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = Math.max(this.columns.length, 1);
            td.className = 'empty-state';
            td.textContent = this.rawRows.length === 0
                ? 'No records matched the qualification/selection criteria.'
                : 'No stocks matched your search filter in current results.';
            tr.appendChild(td);
            this.tbody.appendChild(tr);
            return;
        }

        this.displayRows.forEach(row => {
            const tr = document.createElement('tr');
            const sym = row['symbol'] || '';
            if (sym && sym === this.activeSymbol) {
                tr.classList.add('active-row');
            }

            tr.addEventListener('click', () => {
                this.setActiveSymbol(sym);
                if (this.onRowSelect && sym) {
                    this.onRowSelect(sym);
                }
            });

            this.columns.forEach(col => {
                const td = document.createElement('td');
                const val = row[col.key];
                td.innerHTML = this._formatCell(col.key, val, row);
                tr.appendChild(td);
            });

            this.tbody.appendChild(tr);
        });
    }

    filter(query) {
        this.currentFilterQuery = (query || '').trim();
        this._applySortAndFilter();
    }

    setActiveSymbol(symbol) {
        this.activeSymbol = symbol;
        const allRows = this.tbody.querySelectorAll('tr');
        allRows.forEach(tr => {
            const firstCell = tr.querySelector('td');
            if (firstCell && firstCell.textContent.trim().startsWith(symbol)) {
                tr.classList.add('active-row');
            } else {
                tr.classList.remove('active-row');
            }
        });
    }

    _escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    _formatCell(key, val, row) {
        if (val === null || val === undefined) {
            return '<span class="val-null">—</span>';
        }

        const safeVal = this._escapeHtml(val);

        if (key === 'symbol') {
            return `<strong class="sym-ticker">${safeVal}</strong>`;
        }

        if (key === 'EMA_STRIP' || key === 'EMA_ALL') {
            return this._renderEmaStrip(row);
        }

        if (key === 'BAND_STRIP' || key === 'BANDST_ALL') {
            return this._renderBandStrip(row);
        }

        // Indicator badges
        if (key.startsWith('BANDST_') || key === 'BANDST') {
            const upper = String(val).toUpperCase();
            if (upper === 'ABOVE') return `<span class="badge badge-above" title="Above Upper Band">ABOVE</span>`;
            if (upper === 'BELOW') return `<span class="badge badge-below" title="Below Lower Band">BELOW</span>`;
            return `<span class="badge badge-in" title="Inside Bands">IN</span>`;
        }

        if (key.startsWith('EMA_') || key === 'UPCUT') {
            const lower = String(val).toLowerCase();
            if (lower === 'upcut') return `<span class="badge badge-upcut" title="Fresh Trend Crossover (EMA3 > EMA5)">UPCUT</span>`;
            if (lower === 'yes') return `<span class="badge badge-above" title="Positive Trend (EMA3 >= EMA5)">UP</span>`;
            if (lower === 'downcut') return `<span class="badge badge-downcut" title="Fresh Downcut">DOWNCUT</span>`;
            if (lower === 'no') return `<span class="badge badge-below" title="Negative Trend (EMA3 < EMA5)">DOWN</span>`;
            return safeVal;
        }

        if (key === 'IC') {
            const upper = String(val).toUpperCase();
            if (upper === 'IP') return `<span class="badge badge-ip" title="Impulse Leg Confirmed">IMPULSE</span>`;
            if (upper === 'CR') return `<span class="badge badge-cr" title="Correction Leg">CORRECT</span>`;
            if (upper === 'UP') return `<span class="badge badge-up" title="Trending Up">UP</span>`;
            return `<span class="badge badge-neutral">${safeVal}</span>`;
        }

        if (key.startsWith('DMI_') || key === 'DMI_STATE_D') {
            const st = String(val).toLowerCase();
            if (st === 'bullish') return `<span class="badge badge-dmi-bullish" title="DMI Trend: Bullish (+DI > -DI and ADX strong)">BULLISH</span>`;
            if (st === 'bearish') return `<span class="badge badge-dmi-bearish" title="DMI Trend: Bearish (-DI > +DI)">BEARISH</span>`;
            if (st === 'neutral') return `<span class="badge badge-dmi-neutral" title="DMI Trend: Neutral">NEUTRAL</span>`;
            return safeVal;
        }

        // Candlestick pattern flags (Y/N)
        if (key.startsWith('CD_') || key.startsWith('CW_') || key.startsWith('CM_') || key.startsWith('CQ_') || key.startsWith('CH_') || key.startsWith('CY_')) {
            const isPattern = String(val).toUpperCase() === 'Y';
            if (isPattern) {
                const patName = key.replace(/^(CD_|CW_|CM_|CQ_|CH_|CY_)/, '');
                return `<span class="badge badge-above" title="${patName} Active">★ ${patName}</span>`;
            } else if (String(val).toUpperCase() === 'N') {
                return '<span class="val-null">—</span>';
            }
        }

        if (key === 'fno') {
            const isFno = String(val).toUpperCase() === 'Y';
            return isFno
                ? `<span class="badge badge-fno" title="F&O Derivatives Listed">F&O</span>`
                : `<span class="badge badge-cash" title="Cash Segment Only">CASH</span>`;
        }

        if (key === 'OUT_ABOVE' || key === 'OUT_BELOW') {
            if (!val || val === '') return '<span class="val-null">—</span>';
            const cls = key === 'OUT_ABOVE' ? 'badge-above' : 'badge-below';
            return `<span class="badge ${cls}">${safeVal}</span>`;
        }

        // Numeric percentage / ROC formatting
        if (typeof val === 'number') {
            if (key.startsWith('ADX_')) {
                const formatted = val.toFixed(1);
                const strong = val >= 25;
                return `<span class="${strong ? 'badge badge-adx-strong' : 'val-neutral'}" title="${strong ? 'Strong Trend (ADX >= 25)' : 'Weak / Ranging Trend (ADX < 25)'}">${formatted}</span>`;
            }
            if (key.startsWith('DIP_') || key.startsWith('DIM_')) {
                const cls = key.startsWith('DIP_') ? 'val-positive' : 'val-negative';
                return `<span class="${cls}">${val.toFixed(1)}</span>`;
            }
            if (key === 'mcap') {
                return `<span>₹${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr</span>`;
            }
            if (key.startsWith('SPA_A')) {
                const formatted = val.toFixed(1);
                return `<span class="${val >= 0 ? 'val-positive' : 'val-negative'}">${val >= 0 ? '+' : ''}${formatted}%</span>`;
            }
            if (key.includes('ROC') || key.includes('CUR') || key.includes('DIFF') || key.startsWith('ACCEL_') || key.startsWith('BD_') || key.startsWith('CAGR_')) {
                const formatted = val.toFixed(2);
                if (val > 0) return `<span class="val-positive">+${formatted}%</span>`;
                if (val < 0) return `<span class="val-negative">${formatted}%</span>`;
                return `<span class="val-neutral">${formatted}%</span>`;
            }
            if (key.startsWith('RANK_') || key === 'rank') {
                return `<span class="rank-tag">#${val}</span>`;
            }
            if (key === 'price') {
                return `<span class="price-val">₹${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
            }
            if (key.startsWith('S') && !isNaN(Number(key.slice(1)))) {
                const formatted = val.toFixed(2);
                return `<span class="${val > 0 ? 'val-positive' : 'val-neutral'}">${val > 0 ? '+' : ''}${formatted}%/wk</span>`;
            }
            if (key === 'SPR_CONSIST') {
                return `<span class="badge badge-in">${val.toFixed(0)}%</span>`;
            }
            return Number.isInteger(val) ? val.toString() : val.toFixed(2);
        }

        return safeVal;
    }

    _renderEmaStrip(row) {
        const tfs = ['D', 'W', 'M', 'Q', 'H', 'Y'];
        const pills = tfs.map(tf => {
            const st = String(row[`EMA_${tf}`] || '').toLowerCase();
            let cls = 'pill-na';
            if (st === 'upcut' || st === 'yes') cls = 'pill-up';
            else if (st === 'downcut' || st === 'no') cls = 'pill-down';
            return `<span class="tf-pill ${cls}" title="${tf}: ${st || 'na'}">${tf}</span>`;
        }).join('');
        return `<div class="tf-pill-strip">${pills}</div>`;
    }

    _renderBandStrip(row) {
        const tfs = ['D', 'W', 'M', 'Q', 'H', 'Y'];
        const pills = tfs.map(tf => {
            const st = String(row[`BANDST_${tf}`] || '').toUpperCase();
            let cls = 'pill-na';
            if (st === 'ABOVE') cls = 'pill-above';
            else if (st === 'BELOW') cls = 'pill-below';
            else if (st === 'IN') cls = 'pill-in';
            return `<span class="tf-pill ${cls}" title="${tf}: ${st || 'na'}">${tf}</span>`;
        }).join('');
        return `<div class="tf-pill-strip">${pills}</div>`;
    }
}

window.CockpitTable = CockpitTable;
