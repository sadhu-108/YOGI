/**
 * YOGI Cockpit — Unified Screener & Momentum Intelligence Controller.
 *
 * Full Control Without Complexity.
 * Single-screen workspace with progressive disclosure, multi-timeframe condition builder,
 * preset management, live analysis matrix, and TradingView charts.
 */

document.addEventListener('DOMContentLoaded', async () => {
    // -------------------------------------------------------------------------
    // 1. Metric Catalog & Human-Friendly Mapping
    // -------------------------------------------------------------------------
    const METRICS_CATALOG = [
        {
            category: "Returns & Rate of Change",
            metrics: [
                { key: "M_CUR", label: "Current Month Return %", tf: "M", type: "number", unit: "%" },
                { key: "DROC", label: "Daily Return % (DROC)", tf: "D", type: "number", unit: "%" },
                { key: "WROC", label: "Weekly Return % (WROC)", tf: "W", type: "number", unit: "%" },
                { key: "MROC", label: "Monthly Return % (MROC)", tf: "M", type: "number", unit: "%" },
                { key: "QROC", label: "Quarterly Return % (QROC)", tf: "Q", type: "number", unit: "%" },
                { key: "HROC", label: "Half-Yearly Return % (HROC)", tf: "H", type: "number", unit: "%" },
                { key: "YROC", label: "1-Year Return % (YROC)", tf: "Y", type: "number", unit: "%" },
                { key: "M_P1", label: "Previous Month Return % (M_P1)", tf: "M", type: "number", unit: "%" },
                { key: "M_P2", label: "Month -2 Return % (M_P2)", tf: "M", type: "number", unit: "%" },
                { key: "M_P3", label: "Month -3 Return % (M_P3)", tf: "M", type: "number", unit: "%" },
                { key: "Q_CUR", label: "Current Quarter Return %", tf: "Q", type: "number", unit: "%" },
                { key: "H_CUR", label: "Current Half-Year Return %", tf: "H", type: "number", unit: "%" },
                { key: "CAGR_1", label: "1-Year CAGR %", tf: "Y", type: "number", unit: "%" },
                { key: "CAGR_3", label: "3-Year CAGR %", tf: "Y", type: "number", unit: "%" },
                { key: "CAGR_5", label: "5-Year CAGR %", tf: "Y", type: "number", unit: "%" },
            ]
        },
        {
            category: "Sprint & Momentum Velocity",
            metrics: [
                { key: "S4", label: "4-Week Speed (S4)", tf: "W", type: "number", unit: "%/wk" },
                { key: "S13", label: "13-Week Speed (S13)", tf: "W", type: "number", unit: "%/wk" },
                { key: "S26", label: "26-Week Speed (S26)", tf: "W", type: "number", unit: "%/wk" },
                { key: "S52", label: "52-Week Speed (S52)", tf: "W", type: "number", unit: "%/wk" },
                { key: "ACCEL_L", label: "Long Acceleration (S4 - S52)", tf: "W", type: "number", unit: "pts" },
                { key: "ACCEL_S", label: "Short Acceleration (S4 - S13)", tf: "W", type: "number", unit: "pts" },
                { key: "SPR_CONSIST", label: "Sprint Consistency % (12w)", tf: "W", type: "number", unit: "%" },
                { key: "SPD_W", label: "Weekly Speed", tf: "W", type: "number", unit: "%" },
                { key: "SPD_M", label: "Monthly Speed", tf: "M", type: "number", unit: "%" },
                { key: "SPD_Q", label: "Quarterly Speed", tf: "Q", type: "number", unit: "%" },
                { key: "SPD_H", label: "Half-Yearly Speed", tf: "H", type: "number", unit: "%" },
                { key: "SPD_Y", label: "Yearly Speed", tf: "Y", type: "number", unit: "%" },
                { key: "SPA_A21", label: "Sprint Anchored Jan 2021", tf: "Y", type: "number", unit: "%" },
                { key: "SPA_A22", label: "Sprint Anchored Jan 2022", tf: "Y", type: "number", unit: "%" },
                { key: "SPA_A23", label: "Sprint Anchored Jan 2023", tf: "Y", type: "number", unit: "%" },
                { key: "SPA_A24", label: "Sprint Anchored Jan 2024", tf: "Y", type: "number", unit: "%" },
                { key: "SPA_A25", label: "Sprint Anchored Jan 2025", tf: "Y", type: "number", unit: "%" },
                { key: "SPA_A26", label: "Sprint Anchored Jan 2026", tf: "Y", type: "number", unit: "%" },
            ]
        },
        {
            category: "Trend & EMA Ribbons (3 vs 5)",
            metrics: [
                { key: "EMA_D", label: "Daily EMA State", tf: "D", type: "enum", options: ["upcut", "yes", "downcut", "no"] },
                { key: "EMA_W", label: "Weekly EMA State", tf: "W", type: "enum", options: ["upcut", "yes", "downcut", "no"] },
                { key: "EMA_M", label: "Monthly EMA State", tf: "M", type: "enum", options: ["upcut", "yes", "downcut", "no"] },
                { key: "EMA_Q", label: "Quarterly EMA State", tf: "Q", type: "enum", options: ["upcut", "yes", "downcut", "no"] },
                { key: "EMA_H", label: "Half-Yearly EMA State", tf: "H", type: "enum", options: ["upcut", "yes", "downcut", "no"] },
                { key: "EMA_Y", label: "Yearly EMA State", tf: "Y", type: "enum", options: ["upcut", "yes", "downcut", "no"] },
                { key: "EMA_UP_COUNT", label: "Count of EMA UP Timeframes (0-6)", tf: "ALL", type: "number" },
                { key: "UPCUT", label: "Fresh Monthly Upcut Flag", tf: "M", type: "enum", options: ["yes", "no"] },
                { key: "IC", label: "Impulse Leg (Zigzag 50%)", tf: "W", type: "enum", options: ["IP", "CR", "up", "na"] },
                { key: "IC_PCT", label: "Impulse Leg % Move", tf: "W", type: "number", unit: "%" },
                { key: "IC_BARS", label: "Impulse Leg Duration Bars", tf: "W", type: "number" },
                { key: "IC_RATIO", label: "Impulse Recovery Ratio", tf: "W", type: "number" },
            ]
        },
        {
            category: "Discretionary Envelopes & Bands",
            metrics: [
                { key: "BANDST_D", label: "Daily Band State", tf: "D", type: "enum", options: ["ABOVE", "IN", "BELOW"] },
                { key: "BANDST_W", label: "Weekly Band State", tf: "W", type: "enum", options: ["ABOVE", "IN", "BELOW"] },
                { key: "BANDST_M", label: "Monthly Band State", tf: "M", type: "enum", options: ["ABOVE", "IN", "BELOW"] },
                { key: "BANDST_Q", label: "Quarterly Band State", tf: "Q", type: "enum", options: ["ABOVE", "IN", "BELOW"] },
                { key: "BANDST_H", label: "Half-Yearly Band State", tf: "H", type: "enum", options: ["ABOVE", "IN", "BELOW"] },
                { key: "BANDST_Y", label: "Yearly Band State", tf: "Y", type: "enum", options: ["ABOVE", "IN", "BELOW"] },
                { key: "BD_D", label: "Daily Band Distance %", tf: "D", type: "number", unit: "%" },
                { key: "BD_W", label: "Weekly Band Distance %", tf: "W", type: "number", unit: "%" },
                { key: "BD_M", label: "Monthly Band Distance %", tf: "M", type: "number", unit: "%" },
                { key: "BD_Q", label: "Quarterly Band Distance %", tf: "Q", type: "number", unit: "%" },
                { key: "BD_H", label: "Half-Yearly Band Distance %", tf: "H", type: "number", unit: "%" },
                { key: "BD_Y", label: "Yearly Band Distance %", tf: "Y", type: "number", unit: "%" },
                { key: "OUT_ABOVE", label: "Broke Above Band Timeframes", tf: "ALL", type: "string" },
                { key: "OUT_BELOW", label: "Broke Below Band Timeframes", tf: "ALL", type: "string" },
                { key: "N_ABOVE", label: "Number of Bands Broken Above", tf: "ALL", type: "number" },
                { key: "N_BELOW", label: "Number of Bands Broken Below", tf: "ALL", type: "number" },
            ]
        },
        {
            category: "Price, Market & Technical",
            metrics: [
                { key: "price", label: "Current Price (₹)", tf: "D", type: "number", unit: "₹" },
                { key: "ATH_DIFF", label: "Distance from All-Time High %", tf: "D", type: "number", unit: "%" },
                { key: "ADX_D", label: "ADX Trend Strength Daily", tf: "D", type: "number" },
                { key: "DIP_D", label: "+DI Daily", tf: "D", type: "number" },
                { key: "DIM_D", label: "-DI Daily", tf: "D", type: "number" },
                { key: "DMI_STATE_D", label: "DMI State Daily", tf: "D", type: "enum", options: ["bullish", "bearish", "neutral"] },
                { key: "fno", label: "F&O Derivatives Listed", tf: "STATIC", type: "enum", options: ["Y", "N"] },
                { key: "mcap", label: "Market Capitalization (Cr)", tf: "STATIC", type: "number", unit: "Cr" },
                { key: "sector", label: "Sector", tf: "STATIC", type: "string" },
                { key: "grade", label: "Grade", tf: "STATIC", type: "string" },
                { key: "RANK_CHG", label: "Monthly Rank Change Delta", tf: "M", type: "number" },
            ]
        }
    ];

    const MENTOR_CATEGORIES = {
        "Impulse / Rally": ["A1_IMPULSE_CONFIRMED", "A2_ALL_6_TF_EMA_UP", "A3_FRESH_MONTHLY_UPCUT", "A4_FRESH_WEEKLY_UPCUT"],
        "Sprint / Momentum": ["B1_SPRINTERS_MONTH", "B2_SPRINTERS_QUARTER", "B3_SPRINTERS_YEAR", "B4_ACCELERATING", "B5_ACCEL_AND_EMA_UP", "B6_CONSISTENT_RUNNERS", "B7_IN_IMPULSE", "B8_IN_CORRECTION"],
        "Band Breakouts": ["C1_BROKE_ABOVE_BAND", "C2_BROKE_BELOW_BAND", "C3_OUTSIDE_BAND_2PLUS_TF", "C4_REACTION_TRADE"],
        "Exit Signals": ["D1_EXIT_FNO", "D2_EXIT_CASH"],
        "Ranking & Cutoffs": ["E1_TOP_100_MONTH", "E2_TOP_100_YEAR", "E3_RANK_CLIMBERS"]
    };

    const COLUMN_PRESETS = {
        summary: ["symbol", "name", "price", "M_CUR", "RANK_M", "EMA_W", "EMA_M", "BANDST_M", "BD_M", "S4", "ACCEL_L", "ATH_DIFF"],
        returns: ["symbol", "price", "DROC", "WROC", "MROC", "QROC", "HROC", "YROC", "M_CUR"],
        sprint: ["symbol", "price", "S4", "S13", "S26", "S52", "ACCEL_L", "ACCEL_S", "SPR_CONSIST", "SPA_A21", "SPA_A26"],
        bands: ["symbol", "price", "BANDST_D", "BANDST_W", "BANDST_M", "BANDST_Q", "BD_D", "BD_W", "BD_M", "OUT_ABOVE", "OUT_BELOW"],
        emas: ["symbol", "price", "EMA_D", "EMA_W", "EMA_M", "EMA_Q", "EMA_H", "EMA_Y", "IC", "IC_RATIO"],
        strength: ["symbol", "price", "ADX_D", "DIP_D", "DIM_D", "DMI_STATE_D", "EMA_D", "EMA_W", "IC"],
        all: []
    };

    function getMetricMeta(key) {
        for (const cat of METRICS_CATALOG) {
            for (const m of cat.metrics) {
                if (m.key === key) return m;
            }
        }
        return { key, label: key, tf: "—", type: "string" };
    }

    // -------------------------------------------------------------------------
    // 2. Global State Variables
    // -------------------------------------------------------------------------
    let activeSymbol = '';
    let activeChartTimeframe = 'D';
    let loadedPresetName = '';
    let isPresetModified = false;
    let allStrategies = [];
    let currentUniverseCount = 0;

    // Initialize Chart & Table
    const chart = new CockpitChart('chartContainer');
    const table = new CockpitTable('resultsTable', async (sym) => {
        if (!sym) return;
        await openStockDrawer(sym);
    });

    // Wire up results table instant search filter
    const filterInput = document.getElementById('tableFilterInput');
    if (filterInput) {
        filterInput.addEventListener('input', (e) => {
            table.filter(e.target.value);
        });
    }

    // Toast notifications helper
    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    }

    // -------------------------------------------------------------------------
    // 3. System Status & Dataset Refresh
    // -------------------------------------------------------------------------
    async function updateStatus() {
        try {
            const status = await API.getStatus();
            currentUniverseCount = status.universe_count;

            const universeEl = document.getElementById('universeText');
            const lastBuiltEl = document.getElementById('lastBuiltText');
            const modeBadge = document.getElementById('modeBadge');
            const statusDot = document.getElementById('statusDot');
            const funnelUniverse = document.getElementById('funnelUniverse');

            if (universeEl) universeEl.textContent = `Universe: ${status.universe_count} stocks`;
            if (funnelUniverse) funnelUniverse.textContent = status.universe_count;
            if (lastBuiltEl) {
                lastBuiltEl.textContent = status.last_built_at
                    ? `As of: ${new Date(status.last_built_at).toLocaleTimeString()}`
                    : 'As of: Not built';
            }

            if (modeBadge) {
                if (status.is_demo) {
                    modeBadge.className = 'badge badge-demo';
                    modeBadge.textContent = 'MODE: DEMO (5 STOCKS)';
                } else if (status.universe_count > 0) {
                    modeBadge.className = 'badge badge-live';
                    const providerLabel = (status.provider === 'twelvedata' || status.provider === 'twelve_data')
                        ? 'TWELVE DATA'
                        : (status.provider || 'LIVE').toUpperCase();
                    modeBadge.textContent = `MODE: LIVE (${providerLabel} / ${status.exchange || 'NSE'})`;
                } else {
                    modeBadge.className = 'badge';
                    const providerLabel = (status.provider === 'twelvedata' || status.provider === 'twelve_data')
                        ? 'TWELVE DATA'
                        : (status.provider || 'LIVE').toUpperCase();
                    modeBadge.textContent = `MODE: ${providerLabel} (EMPTY)`;
                }
            }

            if (statusDot) statusDot.className = 'status-indicator ready';
            updateSummaryBanner();
            return status;
        } catch (err) {
            console.error('Failed to load status:', err);
            return null;
        }
    }

    async function loadDemoData() {
        const btn = document.getElementById('loadDemoBtn');
        if (btn) btn.disabled = true;
        try {
            showToast('Loading offline demo dataset...', 'info');
            await API.refreshDataset(null, null, 'demo');
            await updateStatus();
            await runScreen();
            showToast('Loaded demo dataset (5 stocks) successfully!', 'success');
        } catch (err) {
            showToast(`Failed to load demo: ${err.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function rebuildLiveDataset() {
        const btn = document.getElementById('refreshBtn');
        if (btn) btn.disabled = true;
        try {
            showToast('Rebuilding live market dataset from Twelve Data...', 'info');
            await API.refreshDataset(null, null, 'twelvedata');
            await updateStatus();
            await runScreen();
            showToast('Live Twelve Data dataset refreshed successfully!', 'success');
        } catch (err) {
            showToast(`Failed to rebuild live dataset: ${err.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    document.getElementById('loadDemoBtn')?.addEventListener('click', loadDemoData);
    document.getElementById('refreshBtn')?.addEventListener('click', rebuildLiveDataset);

    // -------------------------------------------------------------------------
    // 4. Populate Dropdowns (Ranking Metrics & Presets)
    // -------------------------------------------------------------------------
    function populateRankingSelects() {
        const primarySelect = document.getElementById('rankingMetric');
        const secondarySelect = document.getElementById('secondaryRankingMetric');
        if (!primarySelect) return;

        let optionsHtml = '<option value="">None (Unranked)</option>';
        METRICS_CATALOG.forEach(cat => {
            optionsHtml += `<optgroup label="${cat.category}">`;
            cat.metrics.forEach(m => {
                optionsHtml += `<option value="${m.key}">${m.label}</option>`;
            });
            optionsHtml += `</optgroup>`;
        });

        primarySelect.innerHTML = optionsHtml;
        primarySelect.value = 'M_CUR';
        primarySelect.addEventListener('change', onConditionChanged);

        if (secondarySelect) {
            secondarySelect.innerHTML = '<option value="">Default (Symbol Ascending)</option>' + optionsHtml.replace('<option value="">None (Unranked)</option>', '');
            secondarySelect.addEventListener('change', () => {
                table.setSecondarySort(secondarySelect.value);
                onConditionChanged();
            });
        }
    }

    async function loadPresetsList() {
        const select = document.getElementById('presetSelect');
        if (!select) return;

        try {
            allStrategies = await API.getStrategies(true);
            select.innerHTML = '<option value="">-- Choose a Preset to Load --</option>';

            // Group mentor presets by category
            Object.entries(MENTOR_CATEGORIES).forEach(([catTitle, names]) => {
                const group = document.createElement('optgroup');
                group.label = `⚡ ${catTitle}`;
                names.forEach(name => {
                    const strat = allStrategies.find(s => s.name === name);
                    if (strat) {
                        const opt = document.createElement('option');
                        opt.value = strat.name;
                        opt.textContent = strat.name;
                        group.appendChild(opt);
                    }
                });
                if (group.children.length > 0) select.appendChild(group);
            });

            // Group user presets
            const userStrats = allStrategies.filter(s => !s.is_mentor_preset);
            if (userStrats.length > 0) {
                const group = document.createElement('optgroup');
                group.label = '💾 User Presets';
                userStrats.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.name;
                    opt.textContent = `★ ${s.name}`;
                    group.appendChild(opt);
                });
                select.appendChild(group);
            }
        } catch (err) {
            console.error('Failed to load presets:', err);
        }
    }

    // -------------------------------------------------------------------------
    // 5. Preset Loading into Cockpit Form Controls
    // -------------------------------------------------------------------------
    const presetSelect = document.getElementById('presetSelect');
    const loadPresetBtn = document.getElementById('loadPresetBtn');

    if (presetSelect) {
        presetSelect.addEventListener('change', (e) => {
            const name = e.target.value;
            const strat = allStrategies.find(s => s.name === name);
            const descDiv = document.getElementById('presetDesc');
            if (descDiv) {
                descDiv.textContent = strat ? (strat.description || 'Verified preset recipe.') : '';
            }
        });
    }

    async function applyPresetToEditor(name) {
        if (!name) return;
        try {
            showToast(`Loading preset '${name}'...`, 'info');
            const detail = await API.getStrategyDetail(name);
            loadedPresetName = detail.name;
            isPresetModified = false;

            // 1. Clear rules container
            const rulesContainer = document.getElementById('filterRulesContainer');
            if (rulesContainer) rulesContainer.innerHTML = '';

            // 2. Set root match
            const rootMatch = document.getElementById('rootGroupMatch');
            if (rootMatch && detail.filter_group) {
                rootMatch.value = detail.filter_group.match || 'all';
            }

            // 3. Load rules recursively
            if (detail.filter_group && detail.filter_group.rules) {
                detail.filter_group.rules.forEach(r => {
                    if (r.rules && Array.isArray(r.rules)) {
                        createNestedGroupCard(rulesContainer, r);
                    } else {
                        createRuleRow(rulesContainer, r);
                    }
                });
            }

            // 4. Set ranking & limits
            if (detail.target_ranking_metric) {
                const rankingSelect = document.getElementById('rankingMetric');
                if (rankingSelect) rankingSelect.value = detail.target_ranking_metric;
            }

            if (detail.target_cutoff_limit) {
                const limitInput = document.getElementById('screenLimit');
                if (limitInput) limitInput.value = detail.target_cutoff_limit;
                syncLimitPills(detail.target_cutoff_limit);
            }

            // 5. Sync EMA quick toggles based on rules
            syncEmaTogglesFromRules();

            updateActiveRuleCount();
            updateSummaryBanner();
            showToast(`Loaded preset '${name}' into editor`, 'success');
        } catch (err) {
            showToast(`Failed to load preset: ${err.message}`, 'error');
        }
    }

    if (loadPresetBtn) {
        loadPresetBtn.addEventListener('click', () => {
            const name = document.getElementById('presetSelect').value;
            if (!name) {
                showToast('Please select a preset from the dropdown first.', 'error');
                return;
            }
            applyPresetToEditor(name);
        });
    }

    // -------------------------------------------------------------------------
    // 6. Condition Builder (Multi-Timeframe & Nested Groups)
    // -------------------------------------------------------------------------
    const rulesContainer = document.getElementById('filterRulesContainer');
    const addRuleBtn = document.getElementById('addRuleBtn');
    const addGroupBtn = document.getElementById('addGroupBtn');

    function createRuleRow(parentEl, initialData = null) {
        const card = document.createElement('div');
        card.className = 'rule-card';

        const defaultField = initialData ? initialData.field : 'M_CUR';
        const defaultOp = initialData ? initialData.op : '>';
        let defaultVal = initialData ? initialData.value : '0';
        if (Array.isArray(defaultVal)) defaultVal = defaultVal.join(', ');
        const defaultField2 = initialData ? (initialData.field2 || '') : '';
        const defaultNegated = initialData ? Boolean(initialData.is_negated) : false;

        card.innerHTML = `
            <div class="rule-top-row">
                <span class="rule-tf-badge">M</span>
                <select class="form-control form-control-sm rule-metric-select"></select>
                <button class="rule-not-toggle ${defaultNegated ? 'active' : ''}" title="Invert rule (NOT logic)">NOT</button>
                <button class="rule-mode-toggle ${defaultField2 ? 'active' : ''}" title="Toggle between Constant Value and Column-to-Column comparison">vs Col</button>
                <button class="btn-remove" title="Remove condition">×</button>
            </div>
            <div class="rule-controls-row">
                <select class="form-control form-control-sm rule-op-select">
                    <option value="==">== (Equals)</option>
                    <option value="!=">!= (Not Equals)</option>
                    <option value=">">&gt; (Greater)</option>
                    <option value=">=">&gt;= (Greater/Eq)</option>
                    <option value="<">&lt; (Less)</option>
                    <option value="<=">&lt;= (Less/Eq)</option>
                    <option value="in">IN (List)</option>
                    <option value="not_in">NOT IN</option>
                    <option value="between">BETWEEN</option>
                    <option value="not_blank">NOT BLANK</option>
                    <option value="blank">BLANK</option>
                </select>
                <div class="rule-val-wrap">
                    <input type="text" class="form-control form-control-sm rule-val-input" placeholder="Value">
                    <select class="form-control form-control-sm rule-val-select" style="display: none;"></select>
                    <select class="form-control form-control-sm rule-field2-select" style="display: none;"></select>
                </div>
            </div>
        `;

        const tfBadge = card.querySelector('.rule-tf-badge');
        const metricSelect = card.querySelector('.rule-metric-select');
        const notToggle = card.querySelector('.rule-not-toggle');
        const modeToggle = card.querySelector('.rule-mode-toggle');
        const opSelect = card.querySelector('.rule-op-select');
        const valInput = card.querySelector('.rule-val-input');
        const valSelect = card.querySelector('.rule-val-select');
        const field2Select = card.querySelector('.rule-field2-select');
        const removeBtn = card.querySelector('.btn-remove');

        // Populate metric select
        let metricOptions = '';
        METRICS_CATALOG.forEach(cat => {
            metricOptions += `<optgroup label="${cat.category}">`;
            cat.metrics.forEach(m => {
                metricOptions += `<option value="${m.key}">${m.label}</option>`;
            });
            metricOptions += `</optgroup>`;
        });
        metricSelect.innerHTML = metricOptions;
        metricSelect.value = defaultField;
        field2Select.innerHTML = metricOptions;
        if (defaultField2) field2Select.value = defaultField2;

        opSelect.value = defaultOp;

        function updateInputState() {
            const selectedKey = metricSelect.value;
            const meta = getMetricMeta(selectedKey);
            tfBadge.textContent = meta.tf || '—';

            const isColMode = modeToggle.classList.contains('active');
            if (isColMode) {
                valInput.style.display = 'none';
                valSelect.style.display = 'none';
                field2Select.style.display = '';
            } else if (meta.type === 'enum' && meta.options) {
                field2Select.style.display = 'none';
                valInput.style.display = 'none';
                valSelect.style.display = '';
                valSelect.innerHTML = meta.options.map(o => `<option value="${o}">${o}</option>`).join('');
                if (defaultVal) valSelect.value = defaultVal;
            } else {
                field2Select.style.display = 'none';
                valSelect.style.display = 'none';
                valInput.style.display = '';
                valInput.placeholder = meta.unit ? `Value (${meta.unit})` : 'Value';
                if (defaultVal !== undefined && defaultVal !== null) valInput.value = defaultVal;
            }
            onConditionChanged();
        }

        metricSelect.addEventListener('change', () => {
            defaultVal = '';
            updateInputState();
        });

        notToggle.addEventListener('click', () => {
            notToggle.classList.toggle('active');
            onConditionChanged();
        });

        modeToggle.addEventListener('click', () => {
            modeToggle.classList.toggle('active');
            updateInputState();
        });

        opSelect.addEventListener('change', onConditionChanged);
        valInput.addEventListener('input', onConditionChanged);
        valSelect.addEventListener('change', onConditionChanged);
        field2Select.addEventListener('change', onConditionChanged);

        removeBtn.addEventListener('click', () => {
            card.remove();
            onConditionChanged();
            syncEmaTogglesFromRules();
        });

        updateInputState();
        parentEl.appendChild(card);
        onConditionChanged();
        return card;
    }

    function createNestedGroupCard(parentEl, initialGroup = null) {
        const groupCard = document.createElement('div');
        groupCard.className = 'nested-group-card';

        const matchVal = initialGroup ? (initialGroup.match || 'any') : 'any';

        groupCard.innerHTML = `
            <div class="nested-group-header">
                <div class="group-match-bar">
                    <span>Nested Group Match:</span>
                    <select class="form-control form-control-sm group-match-select match-select">
                        <option value="all" ${matchVal === 'all' ? 'selected' : ''}>ALL (AND)</option>
                        <option value="any" ${matchVal === 'any' ? 'selected' : ''}>ANY (OR)</option>
                    </select>
                </div>
                <button class="btn-remove" title="Remove nested group">×</button>
            </div>
            <div class="nested-rules-list rules-container"></div>
            <div class="rule-builder-actions">
                <button class="btn btn-xs btn-outline btn-add-nested-rule">+ Add Rule</button>
            </div>
        `;

        const nestedRulesContainer = groupCard.querySelector('.nested-rules-list');
        const addNestedRuleBtn = groupCard.querySelector('.btn-add-nested-rule');
        const removeGroupBtn = groupCard.querySelector('.btn-remove');
        const matchSelect = groupCard.querySelector('.group-match-select');

        matchSelect.addEventListener('change', onConditionChanged);
        removeGroupBtn.addEventListener('click', () => {
            groupCard.remove();
            onConditionChanged();
        });

        addNestedRuleBtn.addEventListener('click', () => {
            createRuleRow(nestedRulesContainer);
        });

        if (initialGroup && initialGroup.rules) {
            initialGroup.rules.forEach(r => {
                createRuleRow(nestedRulesContainer, r);
            });
        }

        parentEl.appendChild(groupCard);
        onConditionChanged();
        return groupCard;
    }

    if (addRuleBtn && rulesContainer) {
        addRuleBtn.addEventListener('click', () => {
            createRuleRow(rulesContainer);
        });
    }

    if (addGroupBtn && rulesContainer) {
        addGroupBtn.addEventListener('click', () => {
            createNestedGroupCard(rulesContainer);
        });
    }

    function onConditionChanged() {
        isPresetModified = true;
        updateActiveRuleCount();
        updateSummaryBanner();
    }

    function updateActiveRuleCount() {
        const badge = document.getElementById('activeRuleCountBadge');
        if (!badge) return;
        const count = document.querySelectorAll('.rule-card').length;
        badge.textContent = `${count} ${count === 1 ? 'rule' : 'rules'}`;
    }

    // -------------------------------------------------------------------------
    // 7. Quick 1-Click Filter Shortcuts Logic
    // -------------------------------------------------------------------------
    const emaToggleButtons = document.querySelectorAll('#emaQuickToggles .ema-btn');

    emaToggleButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tf = btn.dataset.tf;
            const willBeActive = !btn.classList.contains('active');
            btn.classList.toggle('active');

            const ruleKey = `EMA_${tf}`;
            if (willBeActive) {
                // Add EMA rule if not already in root
                const existing = Array.from(rulesContainer.querySelectorAll('.rule-card')).find(card => {
                    const sel = card.querySelector('.rule-metric-select');
                    return sel && sel.value === ruleKey;
                });
                if (!existing) {
                    createRuleRow(rulesContainer, {
                        field: ruleKey,
                        op: 'in',
                        value: ['upcut', 'yes']
                    });
                }
            } else {
                // Remove EMA rule
                const existing = Array.from(rulesContainer.querySelectorAll('.rule-card')).find(card => {
                    const sel = card.querySelector('.rule-metric-select');
                    return sel && sel.value === ruleKey;
                });
                if (existing) existing.remove();
            }
            onConditionChanged();
        });
    });

    function syncEmaTogglesFromRules() {
        const activeEmaFields = new Set();
        document.querySelectorAll('.rule-card').forEach(card => {
            const sel = card.querySelector('.rule-metric-select');
            if (sel && sel.value.startsWith('EMA_')) {
                activeEmaFields.add(sel.value);
            }
        });

        emaToggleButtons.forEach(btn => {
            const tf = btn.dataset.tf;
            const hasRule = activeEmaFields.has(`EMA_${tf}`);
            if (hasRule) btn.classList.add('active');
            else btn.classList.remove('active');
        });
    }

    // Quick Band Shortcuts
    document.getElementById('quickBandAboveBtn')?.addEventListener('click', () => {
        createRuleRow(rulesContainer, { field: 'BANDST_M', op: '==', value: 'ABOVE' });
    });

    document.getElementById('quickBandOutsideBtn')?.addEventListener('click', () => {
        createRuleRow(rulesContainer, { field: 'OUT_ABOVE', op: '!=', value: '' });
    });

    document.getElementById('quickReactionTradeBtn')?.addEventListener('click', () => {
        createRuleRow(rulesContainer, { field: 'BANDST_Y', op: '==', value: 'BELOW' });
        createRuleRow(rulesContainer, { field: 'EMA_W', op: '==', value: 'upcut' });
    });

    // -------------------------------------------------------------------------
    // 8. Ranking, Limit & Cutoffs
    // -------------------------------------------------------------------------
    const limitPills = document.querySelectorAll('.limit-pill');
    limitPills.forEach(pill => {
        pill.addEventListener('click', () => {
            limitPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            const val = parseInt(pill.dataset.limit, 10);
            const input = document.getElementById('screenLimit');
            if (input) input.value = val === 0 ? '' : val;
            onConditionChanged();
        });
    });

    function syncLimitPills(val) {
        limitPills.forEach(pill => {
            const pVal = parseInt(pill.dataset.limit, 10);
            if (pVal === val || (val === null && pVal === 0)) {
                pill.classList.add('active');
            } else {
                pill.classList.remove('active');
            }
        });
    }

    document.getElementById('screenLimit')?.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10) || null;
        syncLimitPills(val);
        onConditionChanged();
    });

    // Rank Cutoffs Builder
    const cutoffsContainer = document.getElementById('cutoffsContainer');
    document.getElementById('addCutoffBtn')?.addEventListener('click', () => {
        if (!cutoffsContainer) return;
        const row = document.createElement('div');
        row.className = 'cutoff-row';
        row.innerHTML = `
            <select class="form-control form-control-sm cutoff-metric">
                <option value="RANK_M">Month Rank (RANK_M)</option>
                <option value="RANK_Y">Year Rank (RANK_Y)</option>
                <option value="RANK_W">Week Rank (RANK_W)</option>
            </select>
            <span style="font-size:11px">&le;</span>
            <input type="number" class="form-control form-control-sm cutoff-max" value="100" style="width: 70px;">
            <button class="btn-remove" title="Remove cutoff">×</button>
        `;
        row.querySelector('.btn-remove').addEventListener('click', () => {
            row.remove();
            onConditionChanged();
        });
        cutoffsContainer.appendChild(row);
        onConditionChanged();
    });

    // -------------------------------------------------------------------------
    // 9. Display Columns Picker
    // -------------------------------------------------------------------------
    const colPresetButtons = document.querySelectorAll('.col-preset-btn');
    colPresetButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            colPresetButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const presetKey = btn.dataset.preset;
            const cols = COLUMN_PRESETS[presetKey];
            const customInput = document.getElementById('customColumns');
            if (customInput) {
                customInput.value = (cols && cols.length > 0) ? cols.join(', ') : '';
            }
            onConditionChanged();
        });
    });

    // -------------------------------------------------------------------------
    // 10. Summary Banner Updater
    // -------------------------------------------------------------------------
    function updateSummaryBanner() {
        const universeEl = document.getElementById('summaryUniverse');
        const presetEl = document.getElementById('summaryPreset');
        const condEl = document.getElementById('summaryConditions');
        const rankEl = document.getElementById('summaryRanking');
        const selEl = document.getElementById('summarySelection');

        const exch = document.getElementById('universeExchange')?.value || 'NSE';
        const seg = document.getElementById('universeSegment')?.value || 'ALL';
        const segLabel = seg === 'FNO' ? ' (F&O)' : (seg === 'CASH' ? ' (Cash)' : '');
        if (universeEl) universeEl.textContent = `Universe: ${exch}${segLabel}`;

        if (presetEl) {
            if (loadedPresetName) {
                presetEl.textContent = `Preset: ${loadedPresetName}${isPresetModified ? ' (Modified)' : ''}`;
            } else {
                presetEl.textContent = 'Preset: Custom';
            }
        }

        const ruleCount = document.querySelectorAll('.rule-card').length;
        if (condEl) condEl.textContent = `${ruleCount} ${ruleCount === 1 ? 'Condition' : 'Conditions'}`;

        const rankMetric = document.getElementById('rankingMetric')?.value;
        const rankOrder = document.getElementById('rankingOrder')?.value || 'desc';
        const secMetric = document.getElementById('secondaryRankingMetric')?.value;
        if (rankEl) {
            if (rankMetric) {
                const meta = getMetricMeta(rankMetric);
                let text = `Rank: ${meta.label} ${rankOrder === 'desc' ? '↓' : '↑'}`;
                if (secMetric) {
                    const secMeta = getMetricMeta(secMetric);
                    text += ` (then ${secMeta.label})`;
                }
                rankEl.textContent = text;
            } else {
                rankEl.textContent = 'Rank: Unranked';
            }
        }

        const limitVal = parseInt(document.getElementById('screenLimit')?.value, 10);
        if (selEl) {
            selEl.textContent = limitVal ? `Top ${limitVal}` : 'All Qualified';
        }
    }

    // -------------------------------------------------------------------------
    // 11. Screen Execution Pipeline & Funnel Telemetry
    // -------------------------------------------------------------------------
    function extractFilterGroup(containerEl, matchType = 'all') {
        const rules = [];

        // Direct rule cards
        const directCards = Array.from(containerEl.children).filter(el => el.classList.contains('rule-card'));
        directCards.forEach(card => {
            const metricKey = card.querySelector('.rule-metric-select').value;
            const op = card.querySelector('.rule-op-select').value;
            const notActive = card.querySelector('.rule-not-toggle').classList.contains('active');
            const colMode = card.querySelector('.rule-mode-toggle').classList.contains('active');

            if (!metricKey) return;

            if (colMode) {
                const field2 = card.querySelector('.rule-field2-select').value;
                rules.push({
                    field: metricKey,
                    op: op,
                    value: null,
                    field2: field2,
                    is_negated: notActive
                });
            } else {
                const meta = getMetricMeta(metricKey);
                let val;
                if (meta.type === 'enum' && meta.options) {
                    val = card.querySelector('.rule-val-select').value;
                } else {
                    val = card.querySelector('.rule-val-input').value.trim();
                }

                if (op === 'in' || op === 'not_in') {
                    if (typeof val === 'string') {
                        val = val.split(',').map(s => s.trim()).filter(Boolean);
                    }
                } else if (!isNaN(Number(val)) && val !== '') {
                    val = Number(val);
                }

                rules.push({
                    field: metricKey,
                    op: op,
                    value: val,
                    is_negated: notActive
                });
            }
        });

        // Nested groups
        const nestedGroups = Array.from(containerEl.children).filter(el => el.classList.contains('nested-group-card'));
        nestedGroups.forEach(grpCard => {
            const subMatch = grpCard.querySelector('.group-match-select').value;
            const subContainer = grpCard.querySelector('.nested-rules-list');
            const subGroup = extractFilterGroup(subContainer, subMatch);
            if (subGroup && subGroup.rules.length > 0) {
                rules.push(subGroup);
            }
        });

        return rules.length > 0 ? { match: matchType, rules } : null;
    }

    function buildScreenPayload() {
        const rootMatch = document.getElementById('rootGroupMatch')?.value || 'all';
        const filterGroup = extractFilterGroup(rulesContainer, rootMatch);

        // Segment filtering (F&O vs Cash)
        let activeFilterGroup = filterGroup;
        const segment = document.getElementById('universeSegment')?.value || 'ALL';
        const segmentRules = [];
        if (segment === 'FNO') {
            segmentRules.push({ field: 'fno', op: '==', value: 'Y' });
        } else if (segment === 'CASH') {
            segmentRules.push({ field: 'fno', op: '==', value: 'N' });
        }

        if (segmentRules.length > 0) {
            if (!activeFilterGroup) {
                activeFilterGroup = { match: 'all', rules: segmentRules };
            } else if (activeFilterGroup.match === 'all') {
                activeFilterGroup = {
                    match: 'all',
                    rules: [...activeFilterGroup.rules, ...segmentRules]
                };
            } else {
                activeFilterGroup = {
                    match: 'all',
                    rules: [activeFilterGroup, ...segmentRules]
                };
            }
        }

        const rankingMetric = document.getElementById('rankingMetric')?.value || null;
        const rankingOrder = document.getElementById('rankingOrder')?.value || 'desc';
        const limitVal = parseInt(document.getElementById('screenLimit')?.value, 10) || null;

        // Cutoffs
        const cutoffs = [];
        document.querySelectorAll('.cutoff-row').forEach(row => {
            const m = row.querySelector('.cutoff-metric').value;
            const max = parseInt(row.querySelector('.cutoff-max').value, 10);
            if (m && max > 0) {
                cutoffs.push({ metric: m, max_rank: max });
            }
        });

        // Columns
        const colsVal = document.getElementById('customColumns')?.value.trim();
        const cols = colsVal ? colsVal.split(',').map(c => c.trim()).filter(Boolean) : null;

        return {
            filter_group: activeFilterGroup,
            ranking_metric: rankingMetric,
            ranking_order: rankingOrder,
            selection_cutoffs: cutoffs,
            limit: limitVal,
            columns: cols
        };
    }

    async function runScreen() {
        const btn = document.getElementById('runScreenBtn');
        if (btn) btn.disabled = true;

        try {
            const req = buildScreenPayload();
            showToast('Running multi-timeframe screen...', 'info');

            const payload = await API.runScreen(req);
            updateTableResults(payload);
            showToast(`Screen matched ${payload.qualified_count} stocks (${payload.selected_count} selected)`, 'success');
        } catch (err) {
            showToast(`Screening failed: ${err.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    document.getElementById('runScreenBtn')?.addEventListener('click', runScreen);

    function updateTableResults(payload) {
        // Update Funnel Telemetry
        const fUniverse = document.getElementById('funnelUniverse');
        const fQualified = document.getElementById('funnelQualified');
        const fSelected = document.getElementById('funnelSelected');

        if (fUniverse) fUniverse.textContent = payload.universe_count;
        if (fQualified) fQualified.textContent = payload.qualified_count;
        if (fSelected) fSelected.textContent = payload.selected_count;

        if (!payload.rows || payload.rows.length === 0) {
            const tbody = document.getElementById('tableBody');
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="16" class="empty-state">
                            <div class="empty-guide-card">
                                <h3>${payload.universe_count === 0 ? 'Dataset Not Materialized' : 'No Stocks Matched Conditions'}</h3>
                                <p>${payload.universe_count === 0
                                    ? 'The in-memory market dataset is currently empty. Click below to load demo data or rebuild from live market feeds.'
                                    : 'No stocks satisfied your filter criteria. Try relaxing condition thresholds or running an unconstrained screen.'}</p>
                                <div class="empty-guide-buttons">
                                    <button class="btn btn-accent btn-demo-action">★ Load Demo Golden Fixtures (5 Stocks)</button>
                                    <button class="btn btn-secondary btn-live-action">↻ Rebuild Live Dataset</button>
                                </div>
                            </div>
                        </td>
                    </tr>
                `;
                tbody.querySelector('.btn-demo-action')?.addEventListener('click', loadDemoData);
                tbody.querySelector('.btn-live-action')?.addEventListener('click', rebuildLiveDataset);
            }
            return;
        }

        table.render(payload);

        // If the drawer is currently open, verify if active stock is still in results
        const drawer = document.getElementById('stockDetailDrawer');
        const isDrawerOpen = drawer && drawer.classList.contains('open');
        if (isDrawerOpen && activeSymbol) {
            const hasActiveInRows = payload.rows.some(r => r.symbol === activeSymbol);
            if (hasActiveInRows) {
                table.setActiveSymbol(activeSymbol);
                loadChartData(activeSymbol);
                loadStockPanel(activeSymbol);
            }
        }
    }

    // -------------------------------------------------------------------------
    // 12. Stock Detail Slide-Over Drawer & Chart Viewport
    // -------------------------------------------------------------------------
    async function openStockDrawer(symbol) {
        if (!symbol) return;
        activeSymbol = symbol;
        table.setActiveSymbol(symbol);

        const drawer = document.getElementById('stockDetailDrawer');
        if (drawer) {
            drawer.classList.add('open');
            drawer.setAttribute('aria-hidden', 'false');
        }
        document.body.classList.add('drawer-open');

        // Immediately clear previous chart and indicators to avoid stale display
        chart.clear();

        const symbolEl = document.getElementById('activeSymbol');
        const priceEl = document.getElementById('activePrice');
        const athBadge = document.getElementById('activeAthDiff');
        const icBadge = document.getElementById('activeIcBadge');
        const bandStatusBadge = document.getElementById('activeBandStatus');
        const basisEl = document.getElementById('valBasis');
        const upperEl = document.getElementById('valUpper');
        const lowerEl = document.getElementById('valLower');
        const widthEl = document.getElementById('valWidth');
        const widthInput = document.getElementById('bandWidthInput');
        const matrixBody = document.getElementById('liveMatrixBody');
        const signalsStrip = document.getElementById('drawerSignalsStrip');
        const loadingOverlay = document.getElementById('drawerLoadingOverlay');
        const errorMsg = document.getElementById('drawerErrorMsg');

        if (symbolEl) symbolEl.textContent = symbol;
        if (priceEl) priceEl.textContent = '—';
        if (athBadge) athBadge.style.display = 'none';
        if (icBadge) icBadge.style.display = 'none';
        if (bandStatusBadge) bandStatusBadge.style.display = 'none';
        if (basisEl) basisEl.textContent = '—';
        if (upperEl) upperEl.textContent = '—';
        if (lowerEl) lowerEl.textContent = '—';
        if (widthEl) widthEl.textContent = '—';
        if (widthInput) widthInput.value = '';
        if (errorMsg) {
            errorMsg.textContent = '';
            errorMsg.style.display = 'none';
        }
        if (signalsStrip) signalsStrip.innerHTML = '';
        if (matrixBody) {
            matrixBody.innerHTML = `<tr><td colspan="7" class="empty-matrix">Loading live multi-timeframe analytics for ${symbol}...</td></tr>`;
        }
        if (loadingOverlay) loadingOverlay.style.display = 'flex';

        // Trigger chart resize for the drawer container
        chart.resize();

        const reqSym = symbol;
        try {
            await Promise.all([
                loadChartData(reqSym),
                loadStockPanel(reqSym)
            ]);
        } catch (err) {
            if (activeSymbol === reqSym) {
                if (errorMsg) {
                    errorMsg.textContent = `Unable to load data for ${reqSym}: ${err.message}`;
                    errorMsg.style.display = 'block';
                }
            }
        } finally {
            if (activeSymbol === reqSym && loadingOverlay) {
                loadingOverlay.style.display = 'none';
            }
            chart.resize();
        }
    }

    function closeStockDrawer() {
        const drawer = document.getElementById('stockDetailDrawer');
        if (drawer) {
            drawer.classList.remove('open');
            drawer.setAttribute('aria-hidden', 'true');
        }
        document.body.classList.remove('drawer-open');
    }

    document.getElementById('drawerCloseBtn')?.addEventListener('click', closeStockDrawer);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const drawer = document.getElementById('stockDetailDrawer');
            if (drawer && drawer.classList.contains('open')) {
                closeStockDrawer();
            }
        }
    });

    const tfButtons = document.querySelectorAll('#tfButtons .tf-btn');
    tfButtons.forEach(btn => {
        btn.addEventListener('click', async () => {
            tfButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeChartTimeframe = btn.dataset.tf;
            if (activeSymbol) {
                await loadChartData(activeSymbol);
            }
        });
    });

    async function loadChartData(symbol) {
        const target = symbol || activeSymbol;
        if (!target) return;
        try {
            const series = await API.getCandles(target, activeChartTimeframe);
            if (activeSymbol !== target) return; // Discard stale response
            chart.render(series);

            const priceBadge = document.getElementById('activePrice');
            if (series.candles && series.candles.length > 0) {
                const latest = series.candles[series.candles.length - 1];
                if (priceBadge) priceBadge.textContent = `₹${latest.close.toFixed(2)}`;
            } else {
                if (priceBadge) priceBadge.textContent = '—';
            }

            const basisEl = document.getElementById('valBasis');
            const upperEl = document.getElementById('valUpper');
            const lowerEl = document.getElementById('valLower');
            const widthEl = document.getElementById('valWidth');
            const widthInput = document.getElementById('bandWidthInput');

            if (series.latest_band) {
                const b = series.latest_band;
                if (basisEl) basisEl.textContent = b.basis !== null ? `₹${b.basis}` : '—';
                if (upperEl) upperEl.textContent = b.upper !== null ? `₹${b.upper}` : '—';
                if (lowerEl) lowerEl.textContent = b.lower !== null ? `₹${b.lower}` : '—';
                if (widthEl) widthEl.textContent = b.width !== null ? `${(b.width * 100).toFixed(1)}%` : '—';
                if (widthInput) widthInput.value = b.width !== null ? (b.width * 100).toFixed(1) : '';
            } else {
                if (basisEl) basisEl.textContent = '—';
                if (upperEl) upperEl.textContent = '—';
                if (lowerEl) lowerEl.textContent = '—';
                if (widthEl) widthEl.textContent = '—';
                if (widthInput) widthInput.value = '';
            }
        } catch (err) {
            if (activeSymbol === target) {
                console.error('Failed to load chart data:', err);
                const errorMsg = document.getElementById('drawerErrorMsg');
                if (errorMsg) {
                    errorMsg.textContent = `Chart Error: ${err.message}`;
                    errorMsg.style.display = 'block';
                }
            }
        }
    }

    const saveBandBtn = document.getElementById('saveBandBtn');
    if (saveBandBtn) {
        saveBandBtn.addEventListener('click', async () => {
            if (!activeSymbol) {
                showToast('Please select a stock first.', 'error');
                return;
            }
            const pctVal = parseFloat(document.getElementById('bandWidthInput').value);
            if (isNaN(pctVal) || pctVal < 0 || pctVal > 100) {
                showToast('Please enter a valid band width percentage (e.g. 12.0).', 'error');
                return;
            }
            const fraction = pctVal / 100.0;
            saveBandBtn.disabled = true;
            try {
                await API.updateBand(activeSymbol, activeChartTimeframe, fraction);
                await loadChartData(activeSymbol);
                await loadStockPanel(activeSymbol);
                showToast(`Band width for ${activeSymbol} (${activeChartTimeframe}) saved at ${pctVal}%`, 'success');
            } catch (err) {
                showToast(`Failed to save band: ${err.message}`, 'error');
            } finally {
                saveBandBtn.disabled = false;
            }
        });
    }

    async function loadStockPanel(symbol) {
        const target = symbol || activeSymbol;
        if (!target) return;
        const matrixBody = document.getElementById('liveMatrixBody');
        const drawerMeta = document.getElementById('drawerMeta');
        const athDiffBadge = document.getElementById('activeAthDiff');
        const icBadge = document.getElementById('activeIcBadge');
        const bandStatusBadge = document.getElementById('activeBandStatus');
        if (!matrixBody) return;

        try {
            const panel = await API.getStockPanel(target);
            if (activeSymbol !== target) return; // Discard stale response

            if (drawerMeta) {
                drawerMeta.textContent = `${panel.symbol} · ${panel.exchange || 'NSE'} · Live Analytical Matrix`;
            }

            if (athDiffBadge) {
                if (panel.ath_diff !== null && panel.ath_diff !== undefined) {
                    athDiffBadge.style.display = '';
                    athDiffBadge.textContent = `ATH ${panel.ath_diff.toFixed(1)}%`;
                } else {
                    athDiffBadge.style.display = 'none';
                }
            }

            if (icBadge) {
                if (panel.ic && panel.ic !== 'na') {
                    icBadge.style.display = '';
                    icBadge.className = panel.ic === 'IP' ? 'badge badge-ip' : 'badge badge-cr';
                    icBadge.textContent = panel.ic === 'IP' ? 'IMPULSE LEG' : 'CORRECTION';
                } else {
                    icBadge.style.display = 'none';
                }
            }

            if (bandStatusBadge) {
                const km = panel.key_metrics || {};
                if (km.OUT_ABOVE) {
                    bandStatusBadge.style.display = '';
                    bandStatusBadge.className = 'badge badge-above';
                    bandStatusBadge.textContent = `ABOVE BAND (${km.OUT_ABOVE})`;
                } else if (km.OUT_BELOW) {
                    bandStatusBadge.style.display = '';
                    bandStatusBadge.className = 'badge badge-below';
                    bandStatusBadge.textContent = `BELOW BAND (${km.OUT_BELOW})`;
                } else {
                    const mRow = (panel.timeframes || []).find(r => r.timeframe === 'M');
                    if (mRow && mRow.band_state) {
                        bandStatusBadge.style.display = '';
                        bandStatusBadge.className = mRow.band_state === 'ABOVE' ? 'badge badge-above' : (mRow.band_state === 'BELOW' ? 'badge badge-below' : 'badge badge-in');
                        bandStatusBadge.textContent = `${mRow.band_state} MONTHLY BAND`;
                    } else {
                        bandStatusBadge.style.display = 'none';
                    }
                }
            }

            // Build Matrix Rows
            const tfs = panel.timeframes || [];

            function renderEmaCell(row) {
                const st = (row.ema_state || '').toLowerCase();
                if (st === 'upcut') return '<span class="badge badge-upcut">UPCUT</span>';
                if (st === 'yes') return '<span class="badge badge-above">UP</span>';
                if (st === 'downcut') return '<span class="badge badge-downcut">DOWNCUT</span>';
                if (st === 'no') return '<span class="badge badge-below">DOWN</span>';
                return '<span class="val-null">—</span>';
            }

            function renderBandStateCell(row) {
                const st = (row.band_state || '').toUpperCase();
                const dist = row.band_distance !== null ? ` (${row.band_distance > 0 ? '+' : ''}${row.band_distance.toFixed(1)}%)` : '';
                if (st === 'ABOVE') return `<span class="badge badge-above">ABOVE${dist}</span>`;
                if (st === 'BELOW') return `<span class="badge badge-below">BELOW${dist}</span>`;
                if (st === 'IN') return `<span class="badge badge-in">IN${dist}</span>`;
                return '<span class="val-null">—</span>';
            }

            function renderRocCell(row) {
                if (row.roc === null || row.roc === undefined) return '<span class="val-null">—</span>';
                const f = row.roc.toFixed(2);
                return `<span class="${row.roc >= 0 ? 'val-positive' : 'val-negative'}">${row.roc >= 0 ? '+' : ''}${f}%</span>`;
            }

            function renderSpeedCell(row) {
                if (row.speed === null || row.speed === undefined) return '<span class="val-null">—</span>';
                const f = row.speed.toFixed(2);
                return `<span class="${row.speed >= 0 ? 'val-positive' : 'val-neutral'}">${row.speed >= 0 ? '+' : ''}${f}%</span>`;
            }

            function renderBandWidthCell(row) {
                if (row.band_width === null || row.band_width === undefined) return '<span class="val-null">—</span>';
                return `<span>${(row.band_width * 100).toFixed(1)}%</span>`;
            }

            matrixBody.innerHTML = `
                <tr>
                    <td>EMA 3/5 Trend</td>
                    ${tfs.map(r => `<td>${renderEmaCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td>Band State & Dist</td>
                    ${tfs.map(r => `<td>${renderBandStateCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td>Band Width %</td>
                    ${tfs.map(r => `<td>${renderBandWidthCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td>Return / ROC %</td>
                    ${tfs.map(r => `<td>${renderRocCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td>Speed / Momentum</td>
                    ${tfs.map(r => `<td>${renderSpeedCell(r)}</td>`).join('')}
                </tr>
            `;

            // Build Key Technical Signals Strip
            const signalsStrip = document.getElementById('drawerSignalsStrip');
            if (signalsStrip) {
                const km = panel.key_metrics || {};
                let chipsHtml = '';

                // 1. Sprint Consistency
                if (panel.spr_consist !== null && panel.spr_consist !== undefined) {
                    chipsHtml += `
                        <div class="signal-chip">
                            <span class="signal-chip-label">Sprint Consistency:</span>
                            <span class="signal-chip-val ${panel.spr_consist >= 75 ? 'val-positive' : 'val-neutral'}">${panel.spr_consist.toFixed(0)}% (12w)</span>
                        </div>
                    `;
                }

                // 2. Impulse & Recovery Ratio
                if (panel.ic && panel.ic !== 'na') {
                    const ratioStr = panel.ic_ratio !== null && panel.ic_ratio !== undefined ? ` (Ratio: ${panel.ic_ratio.toFixed(2)})` : '';
                    chipsHtml += `
                        <div class="signal-chip">
                            <span class="signal-chip-label">Zigzag Leg:</span>
                            <span class="signal-chip-val ${panel.ic === 'IP' ? 'val-positive' : 'val-negative'}">${panel.ic === 'IP' ? 'Impulse' : 'Correction'}${ratioStr}</span>
                        </div>
                    `;
                }

                // 3. DMI Trend & ADX
                if (km.DMI_STATE_D) {
                    const adxStr = km.ADX_D !== null && km.ADX_D !== undefined ? ` (ADX: ${km.ADX_D.toFixed(1)})` : '';
                    const dipStr = km.DIP_D !== null && km.DIP_D !== undefined ? ` +DI: ${km.DIP_D.toFixed(1)}` : '';
                    const dimStr = km.DIM_D !== null && km.DIM_D !== undefined ? ` -DI: ${km.DIM_D.toFixed(1)}` : '';
                    chipsHtml += `
                        <div class="signal-chip">
                            <span class="signal-chip-label">DMI Daily:</span>
                            <span class="signal-chip-val ${km.DMI_STATE_D === 'bullish' ? 'val-positive' : (km.DMI_STATE_D === 'bearish' ? 'val-negative' : 'val-neutral')}">${km.DMI_STATE_D.toUpperCase()}${adxStr}${dipStr}${dimStr}</span>
                        </div>
                    `;
                }

                // 4. Acceleration
                if (panel.accel_l !== null && panel.accel_l !== undefined) {
                    chipsHtml += `
                        <div class="signal-chip">
                            <span class="signal-chip-label">Long Accel (S4 - S52):</span>
                            <span class="signal-chip-val ${panel.accel_l >= 0 ? 'val-positive' : 'val-negative'}">${panel.accel_l >= 0 ? '+' : ''}${panel.accel_l.toFixed(2)} pts/wk</span>
                        </div>
                    `;
                }

                signalsStrip.innerHTML = chipsHtml;
            }
        } catch (err) {
            if (activeSymbol === target) {
                console.error('Failed to load stock panel:', err);
            }
        }
    }

    // -------------------------------------------------------------------------
    // 13. User Preset Management Modal
    // -------------------------------------------------------------------------
    const presetModal = document.getElementById('presetModal');
    const saveAsPresetBtn = document.getElementById('saveAsPresetBtn');
    const modalCloseBtn = document.getElementById('modalCloseBtn');
    const modalCancelBtn = document.getElementById('modalCancelBtn');
    const modalSavePresetBtn = document.getElementById('modalSavePresetBtn');
    const userPresetsList = document.getElementById('userPresetsList');

    function openPresetModal() {
        if (!presetModal) return;
        presetModal.style.display = 'flex';
        const nameInput = document.getElementById('presetNameInput');
        if (nameInput) {
            nameInput.value = loadedPresetName ? `${loadedPresetName} Copy` : 'My Screen Setup';
            nameInput.focus();
        }
        renderSavedPresetsList();
    }

    function closePresetModal() {
        if (presetModal) presetModal.style.display = 'none';
    }

    async function renderSavedPresetsList() {
        if (!userPresetsList) return;
        userPresetsList.innerHTML = '<li style="padding: 8px; color: var(--text-muted);">Loading presets...</li>';
        try {
            const presets = await API.getUserPresets();
            if (presets.length === 0) {
                userPresetsList.innerHTML = '<li style="padding: 8px; color: var(--text-muted);">No user presets saved yet.</li>';
                return;
            }
            userPresetsList.innerHTML = '';
            presets.forEach(p => {
                const li = document.createElement('li');
                li.className = 'user-preset-item';
                li.innerHTML = `
                    <span><strong>${p.name}</strong> <small class="text-muted">(${p.description || 'User preset'})</small></span>
                    <button class="btn btn-xs btn-outline btn-del-preset" title="Delete preset">Delete</button>
                `;
                li.querySelector('.btn-del-preset').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (confirm(`Delete user preset '${p.name}'?`)) {
                        await API.deleteUserPreset(p.name);
                        showToast(`Deleted preset '${p.name}'`, 'info');
                        await renderSavedPresetsList();
                        await loadPresetsList();
                    }
                });
                li.addEventListener('click', () => {
                    applyPresetToEditor(p.name);
                    closePresetModal();
                });
                userPresetsList.appendChild(li);
            });
        } catch (err) {
            userPresetsList.innerHTML = `<li style="padding: 8px; color: var(--accent-red-bright);">Failed: ${err.message}</li>`;
        }
    }

    if (saveAsPresetBtn) saveAsPresetBtn.addEventListener('click', openPresetModal);
    if (modalCloseBtn) modalCloseBtn.addEventListener('click', closePresetModal);
    if (modalCancelBtn) modalCancelBtn.addEventListener('click', closePresetModal);

    if (modalSavePresetBtn) {
        modalSavePresetBtn.addEventListener('click', async () => {
            const nameInput = document.getElementById('presetNameInput');
            const descInput = document.getElementById('presetDescInput');
            const name = (nameInput ? nameInput.value : '').trim();
            const desc = (descInput ? descInput.value : '').trim();

            if (!name) {
                showToast('Please provide a name for the preset.', 'error');
                return;
            }

            modalSavePresetBtn.disabled = true;
            try {
                const screenPayload = buildScreenPayload();
                const presetPayload = {
                    name: name,
                    description: desc || 'Custom user screening setup',
                    filter_group: screenPayload.filter_group,
                    ranking_metric: screenPayload.ranking_metric,
                    ranking_order: screenPayload.ranking_order,
                    selection_cutoffs: screenPayload.selection_cutoffs,
                    limit: screenPayload.limit,
                    columns: screenPayload.columns
                };

                await API.saveUserPreset(presetPayload);
                loadedPresetName = name;
                isPresetModified = false;
                await loadPresetsList();
                updateSummaryBanner();
                closePresetModal();
                showToast(`Saved preset '${name}' successfully!`, 'success');
            } catch (err) {
                showToast(`Failed to save preset: ${err.message}`, 'error');
            } finally {
                modalSavePresetBtn.disabled = false;
            }
        });
    }

    // Quick Find Stock button & Enter key
    const searchInput = document.getElementById('stockQuickSearch');
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('stockSearchBtn')?.click();
            }
        });
    }

    document.getElementById('stockSearchBtn')?.addEventListener('click', async () => {
        const query = (document.getElementById('stockQuickSearch')?.value || '').trim().toUpperCase();
        if (!query) return;
        await openStockDrawer(query);
    });

    // Universe selectors change listeners
    document.getElementById('universeExchange')?.addEventListener('change', onConditionChanged);
    document.getElementById('universeSegment')?.addEventListener('change', onConditionChanged);

    // Static guide buttons in initial empty table state
    document.getElementById('guideDemoBtn')?.addEventListener('click', loadDemoData);
    document.getElementById('guideLiveBtn')?.addEventListener('click', rebuildLiveDataset);

    // Reset Form button
    document.getElementById('resetFormBtn')?.addEventListener('click', () => {
        if (confirm('Reset all screening conditions and settings?')) {
            rulesContainer.innerHTML = '';
            document.getElementById('rankingMetric').value = 'M_CUR';
            document.getElementById('rankingOrder').value = 'desc';
            document.getElementById('screenLimit').value = '20';
            syncLimitPills(20);
            emaToggleButtons.forEach(b => b.classList.remove('active'));
            loadedPresetName = '';
            isPresetModified = false;
            onConditionChanged();
            showToast('Screening workbench reset', 'info');
        }
    });

    // Export Handlers
    async function triggerExport(format) {
        try {
            const req = buildScreenPayload();
            req.format = format;
            showToast(`Generating ${format.toUpperCase()} export...`, 'info');
            await API.exportScreen(req, `yogi_screen_${format}`);
            showToast(`Exported ${format.toUpperCase()} successfully!`, 'success');
        } catch (err) {
            showToast(`Export failed: ${err.message}`, 'error');
        }
    }

    document.getElementById('exportXlsxBtn')?.addEventListener('click', () => triggerExport('xlsx'));
    document.getElementById('exportCsvBtn')?.addEventListener('click', () => triggerExport('csv'));
    document.getElementById('exportJsonBtn')?.addEventListener('click', () => triggerExport('json'));

    // -------------------------------------------------------------------------
    // 14. Initialization Boot Sequence
    // -------------------------------------------------------------------------
    populateRankingSelects();
    await loadPresetsList();
    const initialStatus = await updateStatus();

    // If dataset has rows, run default screen immediately
    if (initialStatus && initialStatus.universe_count > 0) {
        await runScreen();
    } else {
        // Automatically pre-load demo dataset for offline demonstration
        await loadDemoData();
    }
});
