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
            category: "Strength & Technical (DMI)",
            metrics: [
                { key: "ADX_D", label: "ADX Daily", tf: "D", type: "number" },
                { key: "ADX_W", label: "ADX Weekly", tf: "W", type: "number" },
                { key: "ADX_M", label: "ADX Monthly", tf: "M", type: "number" },
                { key: "ADX_Q", label: "ADX Quarterly", tf: "Q", type: "number" },
                { key: "ADX_H", label: "ADX Half-Yearly", tf: "H", type: "number" },
                { key: "ADX_Y", label: "ADX Yearly", tf: "Y", type: "number" },
                { key: "DIP_D", label: "+DI Daily", tf: "D", type: "number" },
                { key: "DIP_W", label: "+DI Weekly", tf: "W", type: "number" },
                { key: "DIP_M", label: "+DI Monthly", tf: "M", type: "number" },
                { key: "DIM_D", label: "-DI Daily", tf: "D", type: "number" },
                { key: "DIM_W", label: "-DI Weekly", tf: "W", type: "number" },
                { key: "DIM_M", label: "-DI Monthly", tf: "M", type: "number" },
                { key: "DMI_D", label: "DMI State Daily", tf: "D", type: "enum", options: ["bullish", "bearish", "neutral"] },
                { key: "DMI_W", label: "DMI State Weekly", tf: "W", type: "enum", options: ["bullish", "bearish", "neutral"] },
                { key: "DMI_M", label: "DMI State Monthly", tf: "M", type: "enum", options: ["bullish", "bearish", "neutral"] },
                { key: "DMI_STATE_D", label: "DMI State Daily (Alias)", tf: "D", type: "enum", options: ["bullish", "bearish", "neutral"] },
            ]
        },
        {
            category: "Candlestick Patterns",
            metrics: [
                { key: "CD_BREAKOUT", label: "Daily Breakout (Close > Prev High)", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_BREAKOUT", label: "Weekly Breakout", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_BREAKOUT", label: "Monthly Breakout", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_HAMMER", label: "Daily Hammer", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_HAMMER", label: "Weekly Hammer", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_HAMMER", label: "Monthly Hammer", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_BULL_ENGULF", label: "Daily Bullish Engulfing", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_BULL_ENGULF", label: "Weekly Bullish Engulfing", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_BULL_ENGULF", label: "Monthly Bullish Engulfing", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_INSIDE", label: "Daily Inside Bar", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_INSIDE", label: "Weekly Inside Bar", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_INSIDE", label: "Monthly Inside Bar", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_DOJI", label: "Daily Doji", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_DOJI", label: "Weekly Doji", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_DOJI", label: "Monthly Doji", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_SHOOTSTAR", label: "Daily Shooting Star", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_SHOOTSTAR", label: "Weekly Shooting Star", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_SHOOTSTAR", label: "Monthly Shooting Star", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_MARUBOZU", label: "Daily Marubozu", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_MARUBOZU", label: "Weekly Marubozu", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_MARUBOZU", label: "Monthly Marubozu", tf: "M", type: "enum", options: ["Y", "N"] },
                { key: "CD_VOL_SPIKE", label: "Daily Volume Spike (≥2x)", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_VOL_SPIKE", label: "Weekly Volume Spike", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CD_CLOSE_STRONG", label: "Daily Close Strong (Top 20%)", tf: "D", type: "enum", options: ["Y", "N"] },
                { key: "CW_CLOSE_STRONG", label: "Weekly Close Strong", tf: "W", type: "enum", options: ["Y", "N"] },
                { key: "CM_CLOSE_STRONG", label: "Monthly Close Strong", tf: "M", type: "enum", options: ["Y", "N"] },
            ]
        },
        {
            category: "Price, Market & Rankings",
            metrics: [
                { key: "price", label: "Current Price (₹)", tf: "D", type: "number", unit: "₹" },
                { key: "ATH_DIFF", label: "Distance from All-Time High %", tf: "D", type: "number", unit: "%" },
                { key: "fno", label: "F&O Derivatives Listed", tf: "STATIC", type: "enum", options: ["Y", "N"] },
                { key: "mcap", label: "Market Capitalization (Cr)", tf: "STATIC", type: "number", unit: "Cr" },
                { key: "sector", label: "Sector", tf: "STATIC", type: "string" },
                { key: "grade", label: "Grade", tf: "STATIC", type: "string" },
                { key: "RANK_M", label: "Monthly Rank (1 = Top)", tf: "M", type: "number" },
                { key: "RANK_Y", label: "Yearly Rank", tf: "Y", type: "number" },
                { key: "RANK_W", label: "Weekly Rank", tf: "W", type: "number" },
                { key: "RANK_Q", label: "Quarterly Rank", tf: "Q", type: "number" },
                { key: "RANK_H", label: "Half-Yearly Rank", tf: "H", type: "number" },
                { key: "RANK_D", label: "Daily Rank", tf: "D", type: "number" },
                { key: "RANK_CHG", label: "Monthly Rank Change Delta", tf: "M", type: "number" },
            ]
        }
    ];

    // Multi-Timeframe Family Mapping for Segmented Controls [D, W, M, Q, H, Y]
    const MULTI_TF_FAMILIES = {
        ROC: {
            family: "ROC",
            label: "Rate of Change (ROC %)",
            keys: { D: "DROC", W: "WROC", M: "MROC", Q: "QROC", H: "HROC", Y: "YROC" }
        },
        SPD: {
            family: "SPD",
            label: "Speed / Velocity",
            keys: { W: "SPD_W", M: "SPD_M", Q: "SPD_Q", H: "SPD_H", Y: "SPD_Y" }
        },
        EMA: {
            family: "EMA",
            label: "EMA Ribbon (3 vs 5)",
            keys: { D: "EMA_D", W: "EMA_W", M: "EMA_M", Q: "EMA_Q", H: "EMA_H", Y: "EMA_Y" }
        },
        BANDST: {
            family: "BANDST",
            label: "Band Position",
            keys: { D: "BANDST_D", W: "BANDST_W", M: "BANDST_M", Q: "BANDST_Q", H: "BANDST_H", Y: "BANDST_Y" }
        },
        BD: {
            family: "BD",
            label: "Band Distance %",
            keys: { D: "BD_D", W: "BD_W", M: "BD_M", Q: "BD_Q", H: "BD_H", Y: "BD_Y" }
        },
        ADX: {
            family: "ADX",
            label: "ADX Trend Strength",
            keys: { D: "ADX_D", W: "ADX_W", M: "ADX_M", Q: "ADX_Q", H: "ADX_H", Y: "ADX_Y" }
        },
        DIP: {
            family: "DIP",
            label: "+DI Directional",
            keys: { D: "DIP_D", W: "DIP_W", M: "DIP_M", Q: "DIP_Q", H: "DIP_H", Y: "DIP_Y" }
        },
        DIM: {
            family: "DIM",
            label: "-DI Directional",
            keys: { D: "DIM_D", W: "DIM_W", M: "DIM_M", Q: "DIM_Q", H: "DIM_H", Y: "DIM_Y" }
        },
        DMI: {
            family: "DMI",
            label: "DMI Trend State",
            keys: { D: "DMI_D", W: "DMI_W", M: "DMI_M", Q: "DMI_Q", H: "DMI_H", Y: "DMI_Y" }
        },
        RANK: {
            family: "RANK",
            label: "Timeframe Rank",
            keys: { D: "RANK_D", W: "RANK_W", M: "RANK_M", Q: "RANK_Q", H: "RANK_H", Y: "RANK_Y" }
        },
        CDL_BREAKOUT: {
            family: "CDL_BREAKOUT",
            label: "Candle: Breakout",
            keys: { D: "CD_BREAKOUT", W: "CW_BREAKOUT", M: "CM_BREAKOUT" }
        },
        CDL_HAMMER: {
            family: "CDL_HAMMER",
            label: "Candle: Hammer",
            keys: { D: "CD_HAMMER", W: "CW_HAMMER", M: "CM_HAMMER" }
        },
        CDL_BULL_ENGULF: {
            family: "CDL_BULL_ENGULF",
            label: "Candle: Bull Engulf",
            keys: { D: "CD_BULL_ENGULF", W: "CW_BULL_ENGULF", M: "CM_BULL_ENGULF" }
        },
        CDL_INSIDE: {
            family: "CDL_INSIDE",
            label: "Candle: Inside Bar",
            keys: { D: "CD_INSIDE", W: "CW_INSIDE", M: "CM_INSIDE" }
        },
        CDL_DOJI: {
            family: "CDL_DOJI",
            label: "Candle: Doji",
            keys: { D: "CD_DOJI", W: "CW_DOJI", M: "CM_DOJI" }
        },
        CDL_SHOOTSTAR: {
            family: "CDL_SHOOTSTAR",
            label: "Candle: Shoot Star",
            keys: { D: "CD_SHOOTSTAR", W: "CW_SHOOTSTAR", M: "CM_SHOOTSTAR" }
        },
        CDL_MARUBOZU: {
            family: "CDL_MARUBOZU",
            label: "Candle: Marubozu",
            keys: { D: "CD_MARUBOZU", W: "CW_MARUBOZU", M: "CM_MARUBOZU" }
        },
        CDL_VOL_SPIKE: {
            family: "CDL_VOL_SPIKE",
            label: "Candle: Vol Spike",
            keys: { D: "CD_VOL_SPIKE", W: "CW_VOL_SPIKE" }
        },
        CDL_CLOSE_STRONG: {
            family: "CDL_CLOSE_STRONG",
            label: "Candle: Close Strong",
            keys: { D: "CD_CLOSE_STRONG", W: "CW_CLOSE_STRONG", M: "CM_CLOSE_STRONG" }
        }
    };

    function getFamilyForMetricKey(key) {
        for (const famKey in MULTI_TF_FAMILIES) {
            const fam = MULTI_TF_FAMILIES[famKey];
            for (const tf in fam.keys) {
                if (fam.keys[tf] === key) {
                    return { family: fam, tf: tf };
                }
            }
        }
        return null;
    }

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
    let activeBandTimeframe = '';
    let activePanel = 'none';
    let currentStockDrawerRequestId = 0;
    let loadedPresetName = '';
    let isPresetModified = false;
    let allStrategies = [];
    let currentUniverseCount = 0;

    // Initialize Chart & Table
    const chart = new CockpitChart('chartContainer', 'subChartCanvas');
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
    let _buildPollingInterval = null;

    function _startBuildPolling() {
        if (_buildPollingInterval) return;
        _buildPollingInterval = setInterval(async () => {
            const st = await updateStatus();
            if (!st || st.status !== 'BUILDING') {
                clearInterval(_buildPollingInterval);
                _buildPollingInterval = null;
                if (st && st.status === 'READY') {
                    showToast('Live market dataset rebuild complete!', 'success');
                    await runScreen();
                } else if (st && st.status === 'FAILED') {
                    showToast(`Rebuild failed: ${st.error || 'Unknown error'}`, 'error');
                }
            }
        }, 2000);
    }

    async function updateStatus() {
        try {
            const status = await API.getStatus();
            currentUniverseCount = status.universe_count;

            const universeEl = document.getElementById('universeText');
            const lastBuiltEl = document.getElementById('lastBuiltText');
            const modeBadge = document.getElementById('modeBadge');
            const statusDot = document.getElementById('statusDot');
            const statusText = document.getElementById('statusText');
            const funnelUniverse = document.getElementById('funnelUniverse');

            if (status.status === 'BUILDING') {
                if (statusDot) statusDot.className = 'status-indicator building';
                const pct = Math.round((status.progress || 0) * 100);
                if (statusText) statusText.textContent = `System: BUILDING (${pct}%)`;
                if (universeEl) universeEl.textContent = status.progress_stage || 'Building market dataset...';
                if (modeBadge) {
                    modeBadge.className = 'badge badge-warning';
                    modeBadge.textContent = `MODE: LIVE (BUILDING ${pct}%)`;
                }
                _startBuildPolling();
            } else {
                if (statusDot) statusDot.className = (status.status === 'FAILED') ? 'status-indicator error' : 'status-indicator ready';
                if (statusText) statusText.textContent = `System: ${status.status}`;
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
                        const providerLabel = (status.provider === 'yfinance')
                            ? 'YAHOO FINANCE'
                            : (status.provider || 'LIVE').toUpperCase();
                        const cacheTag = status.is_cached ? ' (CACHED)' : '';
                        modeBadge.textContent = `MODE: LIVE (${providerLabel}${cacheTag} / ${status.exchange || 'NSE'})`;
                    } else {
                        modeBadge.className = 'badge';
                        const providerLabel = (status.provider === 'yfinance')
                            ? 'YAHOO FINANCE'
                            : (status.provider || 'LIVE').toUpperCase();
                        modeBadge.textContent = `MODE: ${providerLabel} (EMPTY)`;
                    }
                }
            }

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
            await updateStatus();
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function rebuildLiveDataset() {
        const btn = document.getElementById('refreshBtn');
        if (btn) btn.disabled = true;
        try {
            showToast('Initiating background live rebuild from Yahoo Finance...', 'info');
            const res = await API.refreshDataset(null, null, 'yfinance', true);
            await updateStatus();
            _startBuildPolling();
            showToast('Rebuild running in background. Status and progress will update live.', 'info');
        } catch (err) {
            showToast(`Failed to trigger rebuild: ${err.message}`, 'error');
            await updateStatus();
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
    // 5. Preset Loading, Revert & Reset Controls
    // -------------------------------------------------------------------------
    const presetSelect = document.getElementById('presetSelect');
    const loadPresetBtn = document.getElementById('loadPresetBtn');
    const revertPresetBtn = document.getElementById('revertPresetBtn');
    const resetFormBtn = document.getElementById('resetFormBtn');
    const rootGroupNotToggle = document.getElementById('rootGroupNotToggle');

    if (presetSelect) {
        presetSelect.addEventListener('change', async (e) => {
            const name = e.target.value;
            const strat = allStrategies.find(s => s.name === name);
            const descDiv = document.getElementById('presetDesc');
            if (descDiv) {
                descDiv.textContent = strat ? (strat.description || 'Verified preset recipe.') : '';
            }
            if (name) {
                await applyPresetToEditor(name);
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

            // 1. Clear rules container & EMA builder container
            const rulesContainer = document.getElementById('filterRulesContainer');
            if (rulesContainer) rulesContainer.innerHTML = '';
            const emaContainer = document.getElementById('emaConditionsContainer');
            if (emaContainer) emaContainer.innerHTML = '';

            // 2. Set root match & root negation
            const rootMatch = document.getElementById('rootGroupMatch');
            if (rootMatch && detail.filter_group) {
                rootMatch.value = detail.filter_group.match || 'all';
            }
            if (rootGroupNotToggle) {
                rootGroupNotToggle.classList.toggle('active', Boolean(detail.filter_group && detail.filter_group.is_negated));
            }

            // 3. Load rules recursively
            if (detail.filter_group && detail.filter_group.rules) {
                detail.filter_group.rules.forEach(r => {
                    if (r.rules && Array.isArray(r.rules)) {
                        createNestedGroupCard(rulesContainer, r);
                    } else if (r.condition_type === 'ema') {
                        createEmaConditionCard(emaContainer, r);
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
            if (detail.ranking_order) {
                const rankingOrderSelect = document.getElementById('rankingOrder');
                if (rankingOrderSelect) rankingOrderSelect.value = detail.ranking_order;
            }

            const limitInput = document.getElementById('screenLimit');
            if (limitInput) {
                const lim = detail.target_cutoff_limit !== undefined && detail.target_cutoff_limit !== null
                    ? detail.target_cutoff_limit
                    : (detail.limit !== undefined && detail.limit !== null ? detail.limit : 20);
                limitInput.value = lim;
                syncLimitPills(lim);
            }

            // 5. Set Rank Cutoffs
            const cutoffsContainer = document.getElementById('cutoffsContainer');
            if (cutoffsContainer) {
                cutoffsContainer.innerHTML = '';
                if (detail.selection_cutoffs && Array.isArray(detail.selection_cutoffs)) {
                    detail.selection_cutoffs.forEach(c => {
                        addCutoffRow(c.metric, c.max_rank);
                    });
                }
            }

            // 6. Set Columns if provided
            if (detail.columns && Array.isArray(detail.columns) && detail.columns.length > 0) {
                const customInput = document.getElementById('customColumns');
                if (customInput) customInput.value = detail.columns.join(', ');
            }

            // 7. Sync EMA quick toggles based on rules
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
            const name = document.getElementById('presetSelect')?.value;
            if (!name) {
                showToast('Please select a preset from the dropdown first.', 'error');
                return;
            }
            applyPresetToEditor(name);
        });
    }

    if (revertPresetBtn) {
        revertPresetBtn.addEventListener('click', async () => {
            if (!loadedPresetName) return;
            await applyPresetToEditor(loadedPresetName);
            showToast(`Reverted back to pristine preset '${loadedPresetName}'`, 'info');
        });
    }

    if (resetFormBtn) {
        resetFormBtn.addEventListener('click', () => {
            const rulesContainer = document.getElementById('filterRulesContainer');
            if (rulesContainer) rulesContainer.innerHTML = '';
            const emaContainer = document.getElementById('emaConditionsContainer');
            if (emaContainer) {
                emaContainer.innerHTML = '';
                if (typeof createEmaConditionCard === 'function') {
                    createEmaConditionCard(emaContainer);
                }
            }
            const emaMatch = document.getElementById('emaGroupMatch');
            if (emaMatch) emaMatch.value = 'all';
            const rootMatch = document.getElementById('rootGroupMatch');
            if (rootMatch) rootMatch.value = 'all';
            if (rootGroupNotToggle) rootGroupNotToggle.classList.remove('active');
            const rankSelect = document.getElementById('rankingMetric');
            if (rankSelect) rankSelect.value = 'M_CUR';
            const rankOrder = document.getElementById('rankingOrder');
            if (rankOrder) rankOrder.value = 'desc';
            const secRank = document.getElementById('secondaryRankingMetric');
            if (secRank) secRank.value = '';
            const limitInput = document.getElementById('screenLimit');
            if (limitInput) limitInput.value = '20';
            syncLimitPills(20);
            const cutoffsContainer = document.getElementById('cutoffsContainer');
            if (cutoffsContainer) cutoffsContainer.innerHTML = '';
            const customCols = document.getElementById('customColumns');
            if (customCols) customCols.value = '';
            document.querySelectorAll('.col-preset-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.preset === 'summary');
            });
            if (presetSelect) presetSelect.value = '';
            const descDiv = document.getElementById('presetDesc');
            if (descDiv) descDiv.textContent = '';
            loadedPresetName = '';
            isPresetModified = false;
            if (revertPresetBtn) revertPresetBtn.disabled = true;
            syncEmaTogglesFromRules();
            updateActiveRuleCount();
            updateSummaryBanner();
            showToast('Reset all screening criteria to default', 'info');
        });
    }

    if (rootGroupNotToggle) {
        rootGroupNotToggle.addEventListener('click', () => {
            rootGroupNotToggle.classList.toggle('active');
            onConditionChanged();
        });
    }

    // -------------------------------------------------------------------------
    // 6. Condition Builder (Multi-Timeframe Segmented Controls & Nested Groups)
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
                <div class="rule-tf-segmented" style="display: none;">
                    <button type="button" class="rule-tf-btn" data-tf="D">D</button>
                    <button type="button" class="rule-tf-btn" data-tf="W">W</button>
                    <button type="button" class="rule-tf-btn" data-tf="M">M</button>
                    <button type="button" class="rule-tf-btn" data-tf="Q">Q</button>
                    <button type="button" class="rule-tf-btn" data-tf="H">H</button>
                    <button type="button" class="rule-tf-btn" data-tf="Y">Y</button>
                </div>
                <span class="rule-field-resolved">${defaultField}</span>
                <select class="form-control form-control-sm rule-metric-select"></select>
                <button type="button" class="rule-not-toggle ${defaultNegated ? 'active' : ''}" title="Invert rule (NOT logic)">NOT</button>
                <button type="button" class="rule-mode-toggle ${defaultField2 ? 'active' : ''}" title="Toggle between Constant Value and Column comparison">vs Col</button>
                <button type="button" class="btn-remove" title="Remove condition">×</button>
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
                    <option value="contains">CONTAINS</option>
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

        const tfSegmented = card.querySelector('.rule-tf-segmented');
        const tfButtons = card.querySelectorAll('.rule-tf-btn');
        const fieldResolvedBadge = card.querySelector('.rule-field-resolved');
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
            fieldResolvedBadge.textContent = selectedKey;

            // Timeframe segmented control synchronization
            const famInfo = getFamilyForMetricKey(selectedKey);
            if (famInfo) {
                tfSegmented.style.display = 'inline-flex';
                tfButtons.forEach(btn => {
                    const tf = btn.dataset.tf;
                    const hasTf = Boolean(famInfo.family.keys[tf]);
                    btn.style.display = hasTf ? 'inline-block' : 'none';
                    btn.classList.toggle('active', tf === famInfo.tf);
                });
            } else {
                tfSegmented.style.display = 'none';
            }

            const isColMode = modeToggle.classList.contains('active');
            const curOp = opSelect.value;

            if (curOp === 'blank' || curOp === 'not_blank') {
                valInput.style.display = 'none';
                valSelect.style.display = 'none';
                field2Select.style.display = 'none';
            } else if (isColMode) {
                valInput.style.display = 'none';
                valSelect.style.display = 'none';
                field2Select.style.display = '';
            } else if (meta.type === 'enum' && meta.options && curOp !== 'in' && curOp !== 'not_in') {
                field2Select.style.display = 'none';
                valInput.style.display = 'none';
                valSelect.style.display = '';
                valSelect.innerHTML = meta.options.map(o => `<option value="${o}">${o}</option>`).join('');
                if (defaultVal) valSelect.value = defaultVal;
            } else {
                field2Select.style.display = 'none';
                valSelect.style.display = 'none';
                valInput.style.display = '';
                valInput.placeholder = (curOp === 'in' || curOp === 'not_in')
                    ? 'e.g. upcut, yes'
                    : (meta.unit ? `Value (${meta.unit})` : 'Value');
                if (defaultVal !== undefined && defaultVal !== null) valInput.value = defaultVal;
            }
            onConditionChanged();
        }

        tfButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const tf = btn.dataset.tf;
                const famInfo = getFamilyForMetricKey(metricSelect.value);
                if (famInfo && famInfo.family.keys[tf]) {
                    metricSelect.value = famInfo.family.keys[tf];
                    defaultVal = '';
                    updateInputState();
                    syncEmaTogglesFromRules();
                }
            });
        });

        metricSelect.addEventListener('change', () => {
            defaultVal = '';
            updateInputState();
            syncEmaTogglesFromRules();
        });

        notToggle.addEventListener('click', () => {
            notToggle.classList.toggle('active');
            onConditionChanged();
        });

        modeToggle.addEventListener('click', () => {
            modeToggle.classList.toggle('active');
            updateInputState();
        });

        opSelect.addEventListener('change', () => {
            updateInputState();
        });

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
        const isNegated = initialGroup ? Boolean(initialGroup.is_negated) : false;

        groupCard.innerHTML = `
            <div class="nested-group-header">
                <div class="group-match-bar">
                    <span>Nested Group:</span>
                    <select class="form-control form-control-sm group-match-select match-select">
                        <option value="all" ${matchVal === 'all' ? 'selected' : ''}>ALL (AND)</option>
                        <option value="any" ${matchVal === 'any' ? 'selected' : ''}>ANY (OR)</option>
                    </select>
                    <button type="button" class="group-not-toggle ${isNegated ? 'active' : ''}" title="Invert nested group (NOT logic)">NOT</button>
                </div>
                <button type="button" class="btn-remove" title="Remove nested group">×</button>
            </div>
            <div class="nested-rules-list rules-container"></div>
            <div class="rule-builder-actions">
                <button type="button" class="btn btn-xs btn-outline btn-add-nested-rule">+ Add Rule</button>
                <button type="button" class="btn btn-xs btn-ghost btn-add-nested-subgroup">+ Add Subgroup</button>
            </div>
        `;

        const nestedRulesContainer = groupCard.querySelector('.nested-rules-list');
        const addNestedRuleBtn = groupCard.querySelector('.btn-add-nested-rule');
        const addNestedSubgroupBtn = groupCard.querySelector('.btn-add-nested-subgroup');
        const removeGroupBtn = groupCard.querySelector('.btn-remove');
        const matchSelect = groupCard.querySelector('.group-match-select');
        const groupNotBtn = groupCard.querySelector('.group-not-toggle');

        matchSelect.addEventListener('change', onConditionChanged);
        groupNotBtn.addEventListener('click', () => {
            groupNotBtn.classList.toggle('active');
            onConditionChanged();
        });

        removeGroupBtn.addEventListener('click', () => {
            groupCard.remove();
            onConditionChanged();
            syncEmaTogglesFromRules();
        });

        addNestedRuleBtn.addEventListener('click', () => {
            createRuleRow(nestedRulesContainer);
        });

        addNestedSubgroupBtn.addEventListener('click', () => {
            createNestedGroupCard(nestedRulesContainer);
        });

        if (initialGroup && initialGroup.rules) {
            initialGroup.rules.forEach(r => {
                if (r.rules && Array.isArray(r.rules)) {
                    createNestedGroupCard(nestedRulesContainer, r);
                } else {
                    createRuleRow(nestedRulesContainer, r);
                }
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
        const stdCount = document.querySelectorAll('.rule-card').length;
        const emaCount = document.querySelectorAll('.ema-condition-card').length;
        const total = stdCount + emaCount;
        badge.textContent = `${total} ${total === 1 ? 'rule' : 'rules'}`;
    }

    // -------------------------------------------------------------------------
    // 7. Dynamic EMA Condition Builder
    // -------------------------------------------------------------------------
    const EMA_TF_CAPS = {
        D: 31,
        W: 52,
        M: 12,
        Q: 4,
        H: 2,
        Y: 1
    };

    const EMA_TF_LABELS = {
        D: 'Daily',
        W: 'Weekly',
        M: 'Monthly',
        Q: 'Quarterly',
        H: 'Half-Yearly',
        Y: 'Yearly'
    };

    const EMA_TF_ADJECTIVES = {
        D: 'daily',
        W: 'weekly',
        M: 'monthly',
        Q: 'quarterly',
        H: 'half-yearly',
        Y: 'yearly'
    };

    const emaConditionsContainer = document.getElementById('emaConditionsContainer');
    const addEmaConditionBtn = document.getElementById('addEmaConditionBtn');
    const emaGroupMatchSelect = document.getElementById('emaGroupMatch');

    function updateEmaCardIndices() {
        const cards = document.querySelectorAll('.ema-condition-card');
        const container = document.getElementById('emaConditionsContainer');
        const matchWrap = document.getElementById('emaMatchControlWrap');

        if (cards.length > 1) {
            if (container) container.classList.add('has-multiple');
            if (matchWrap) matchWrap.style.display = 'inline-flex';
        } else {
            if (container) container.classList.remove('has-multiple');
            if (matchWrap) matchWrap.style.display = 'none';
        }

        cards.forEach((card, idx) => {
            const badge = card.querySelector('.ema-card-badge');
            if (badge) {
                badge.textContent = `Condition #${idx + 1}`;
            }
            if (cards.length > 1) {
                card.classList.add('multi-card');
            } else {
                card.classList.remove('multi-card');
                card.classList.remove('is-collapsed');
            }
        });
    }

    function populatePeriodOptions(selectEl, maxPeriod, currentVal, fallbackVal) {
        selectEl.innerHTML = '';
        for (let i = 1; i <= maxPeriod; i++) {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = `EMA ${i}`;
            selectEl.appendChild(opt);
        }
        let targetVal = currentVal !== undefined ? parseInt(currentVal, 10) : fallbackVal;
        if (isNaN(targetVal) || targetVal < 1) targetVal = fallbackVal;
        if (targetVal > maxPeriod) targetVal = maxPeriod;
        selectEl.value = String(targetVal);
    }

    function updateEmaCardPreview(card) {
        if (!card) return;
        const tfBtn = card.querySelector('.ema-tf-btn.active');
        const tf = tfBtn ? tfBtn.dataset.tf : 'M';
        const cap = EMA_TF_CAPS[tf] || 12;
        const tfLabel = EMA_TF_LABELS[tf] || tf;
        const tfAdj = EMA_TF_ADJECTIVES[tf] || 'monthly';

        const p1Sel = card.querySelector('.ema-p1-select');
        const p2Sel = card.querySelector('.ema-p2-select');
        const p1 = p1Sel ? parseInt(p1Sel.value, 10) : 3;
        const p2 = p2Sel ? parseInt(p2Sel.value, 10) : 5;

        const stateBtn = card.querySelector('.ema-state-btn.active');
        const state = stateBtn ? stateBtn.dataset.state : 'UP';

        const tfLimitNotice = card.querySelector('.ema-tf-limit-notice');
        const p1Label = card.querySelector('.ema-p1-label');
        const p2Label = card.querySelector('.ema-p2-label');
        const combHelperText = card.querySelector('.ema-comb-helper-text');
        const combErrorNotice = card.querySelector('.ema-comb-error-notice');
        const previewSummary = card.querySelector('.ema-preview-summary');
        const previewExplanation = card.querySelector('.ema-preview-explanation');
        const previewFooter = card.querySelector('.ema-preview-footer');
        const summaryChip = card.querySelector('.ema-card-summary-chip');

        // 1. Timeframe Limit Notice (compact helper line matching reference)
        if (tfLimitNotice) {
            if (tf === 'Y') {
                tfLimitNotice.textContent = 'Maximum period for Y: 1 candle (requires 2 distinct periods)';
                tfLimitNotice.classList.add('warning');
            } else {
                tfLimitNotice.textContent = `Maximum period for ${tf}: ${cap} ${cap === 1 ? 'candle' : 'candles'}`;
                tfLimitNotice.classList.remove('warning');
            }
        }

        // 2. Period Labels
        if (p1Label) p1Label.textContent = 'First EMA';
        if (p2Label) p2Label.textContent = 'Second EMA';

        // 3. Helper Text: "Both EMAs use {timeframe} candles."
        if (combHelperText) {
            combHelperText.textContent = `Both EMAs use ${tfAdj} candles.`;
        }

        // 4. Validation for equal periods or Yearly timeframe
        const isYearly = (tf === 'Y');
        const isEqualPeriods = (!isNaN(p1) && !isNaN(p2) && p1 === p2);
        const isInvalid = isYearly || isEqualPeriods;

        if (p1Sel) p1Sel.classList.toggle('is-invalid', isInvalid);
        if (p2Sel) p2Sel.classList.toggle('is-invalid', isInvalid);

        if (combErrorNotice) {
            if (isYearly) {
                combErrorNotice.textContent = 'Yearly timeframe only has 1 candle; two distinct EMA periods are not possible.';
                combErrorNotice.style.display = 'flex';
            } else if (isEqualPeriods) {
                combErrorNotice.textContent = 'First EMA and Second EMA periods must be distinct.';
                combErrorNotice.style.display = 'flex';
            } else {
                combErrorNotice.style.display = 'none';
            }
        }

        // 5. Live Condition Preview Panel (White summary, green/red/gold explanation)
        const isBearish = (state === 'DOWN' || state === 'DOWNCUT');
        let summaryText = '';
        if (isYearly) {
            summaryText = 'EMA 1 vs EMA 1 · Y · INVALID';
            if (previewSummary) {
                previewSummary.textContent = summaryText;
                previewSummary.className = 'ema-preview-summary is-invalid';
            }
            if (summaryChip) {
                summaryChip.textContent = summaryText;
                summaryChip.className = 'ema-card-summary-chip is-invalid';
            }
        } else if (isEqualPeriods) {
            summaryText = `EMA ${p1} vs EMA ${p2} · ${tf} · INVALID`;
            if (previewSummary) {
                previewSummary.textContent = summaryText;
                previewSummary.className = 'ema-preview-summary is-invalid';
            }
            if (summaryChip) {
                summaryChip.textContent = summaryText;
                summaryChip.className = 'ema-card-summary-chip is-invalid';
            }
        } else {
            summaryText = `EMA ${p1} vs EMA ${p2} · ${tf} · ${state}`;
            if (previewSummary) {
                previewSummary.textContent = summaryText;
                previewSummary.className = 'ema-preview-summary';
            }
            if (summaryChip) {
                summaryChip.textContent = summaryText;
                summaryChip.className = `ema-card-summary-chip${isBearish ? ' is-bearish' : ''}`;
            }
        }

        if (previewExplanation) {
            if (isYearly) {
                previewExplanation.textContent = 'Yearly timeframe requires 2 distinct periods.';
                previewExplanation.className = 'ema-preview-explanation is-invalid';
            } else if (isEqualPeriods) {
                previewExplanation.textContent = 'First EMA and Second EMA periods must be distinct.';
                previewExplanation.className = 'ema-preview-explanation is-invalid';
            } else if (state === 'UP') {
                previewExplanation.textContent = 'First EMA is above the second EMA.';
                previewExplanation.className = 'ema-preview-explanation';
            } else if (state === 'DOWN') {
                previewExplanation.textContent = 'First EMA is below the second EMA.';
                previewExplanation.className = 'ema-preview-explanation is-bearish';
            } else if (state === 'UPCUT') {
                previewExplanation.textContent = 'First EMA crossed above the second EMA.';
                previewExplanation.className = 'ema-preview-explanation';
            } else if (state === 'DOWNCUT') {
                previewExplanation.textContent = 'First EMA crossed below the second EMA.';
                previewExplanation.className = 'ema-preview-explanation is-bearish';
            }
        }

        if (previewFooter) {
            previewFooter.textContent = `${tfLabel} timeframe · EMA period range 1–${cap}`;
        }
    }

    function createEmaConditionCard(parentEl, initialConfig = null) {
        if (!parentEl) return null;

        const card = document.createElement('div');
        card.className = 'ema-condition-card';

        const initTf = (initialConfig && (initialConfig.timeframe || initialConfig.tf)) ? (initialConfig.timeframe || initialConfig.tf).toUpperCase() : 'M';
        const initP1 = (initialConfig && initialConfig.p1 !== undefined) ? parseInt(initialConfig.p1, 10) : 3;
        const initP2 = (initialConfig && initialConfig.p2 !== undefined) ? parseInt(initialConfig.p2, 10) : 5;
        const initState = (initialConfig && (initialConfig.state || initialConfig.value)) ? (initialConfig.state || initialConfig.value).toUpperCase() : 'UP';

        card.innerHTML = `
            <div class="ema-card-header">
                <div class="ema-card-header-left">
                    <span class="ema-card-badge">Condition #1</span>
                    <span class="ema-card-summary-chip"></span>
                </div>
                <div class="ema-card-header-right">
                    <button type="button" class="btn-toggle-ema-card" title="Collapse / Expand condition">▾</button>
                    <button type="button" class="btn-remove-ema-card" title="Remove EMA condition">✕</button>
                </div>
            </div>

            <div class="ema-card-body">
                <!-- Section 1: Select Timeframe -->
                <div class="ema-step-section">
                    <div class="ema-step-title">1. Select timeframe</div>
                    <div class="ema-tf-segmented-grid">
                        <button type="button" class="ema-tf-btn ${initTf === 'D' ? 'active' : ''}" data-tf="D">D</button>
                        <button type="button" class="ema-tf-btn ${initTf === 'W' ? 'active' : ''}" data-tf="W">W</button>
                        <button type="button" class="ema-tf-btn ${initTf === 'M' ? 'active' : ''}" data-tf="M">M</button>
                        <button type="button" class="ema-tf-btn ${initTf === 'Q' ? 'active' : ''}" data-tf="Q">Q</button>
                        <button type="button" class="ema-tf-btn ${initTf === 'H' ? 'active' : ''}" data-tf="H">H</button>
                        <button type="button" class="ema-tf-btn ${initTf === 'Y' ? 'active' : ''}" data-tf="Y">Y</button>
                    </div>
                    <div class="ema-tf-limit-notice"></div>
                </div>

                <!-- Section 2: Choose EMA combination -->
                <div class="ema-step-section">
                    <div class="ema-step-title">2. Choose EMA combination</div>
                    <div class="ema-comb-grid">
                        <div class="ema-comb-field">
                            <label class="ema-comb-label ema-p1-label">First EMA</label>
                            <select class="ema-select-large ema-p1-select"></select>
                        </div>
                        <div class="ema-comb-field">
                            <label class="ema-comb-label ema-p2-label">Second EMA</label>
                            <select class="ema-select-large ema-p2-select"></select>
                        </div>
                    </div>
                    <div class="ema-comb-helper-text"></div>
                    <div class="ema-comb-error-notice" style="display: none;">First EMA and Second EMA periods must be distinct.</div>
                </div>

                <!-- Section 3: Select desired state -->
                <div class="ema-step-section section-state">
                    <div class="ema-step-title">3. Select desired state</div>
                    <div class="ema-state-grid">
                        <button type="button" class="ema-state-btn state-up ${initState === 'UP' ? 'active' : ''}" data-state="UP">UP</button>
                        <button type="button" class="ema-state-btn state-down ${initState === 'DOWN' ? 'active' : ''}" data-state="DOWN">DOWN</button>
                        <button type="button" class="ema-state-btn state-upcut ${initState === 'UPCUT' ? 'active' : ''}" data-state="UPCUT">UPCUT</button>
                        <button type="button" class="ema-state-btn state-downcut ${initState === 'DOWNCUT' ? 'active' : ''}" data-state="DOWNCUT">DOWNCUT</button>
                    </div>
                </div>

                <!-- Live Condition Preview Panel -->
                <div class="ema-preview-panel">
                    <div class="ema-preview-badge">CONDITION PREVIEW</div>
                    <div class="ema-preview-summary"></div>
                    <div class="ema-preview-explanation"></div>
                    <div class="ema-preview-footer"></div>
                </div>
            </div>
        `;

        const p1Sel = card.querySelector('.ema-p1-select');
        const p2Sel = card.querySelector('.ema-p2-select');
        const tfButtons = card.querySelectorAll('.ema-tf-btn');
        const stateButtons = card.querySelectorAll('.ema-state-btn');
        const removeBtn = card.querySelector('.btn-remove-ema-card');
        const toggleBtn = card.querySelector('.btn-toggle-ema-card');
        const cardHeader = card.querySelector('.ema-card-header');

        function updatePeriodsForTf(selectedTf, preferredP1, preferredP2) {
            const cap = EMA_TF_CAPS[selectedTf] || 31;
            let p1Val = preferredP1 !== undefined ? preferredP1 : parseInt(p1Sel.value, 10);
            let p2Val = preferredP2 !== undefined ? preferredP2 : parseInt(p2Sel.value, 10);

            if (isNaN(p1Val) || p1Val < 1) p1Val = Math.min(3, cap);
            if (p1Val > cap) p1Val = cap;

            if (isNaN(p2Val) || p2Val < 1) p2Val = Math.min(5, cap);
            if (p2Val > cap) p2Val = cap;

            // Deterministic adjustment if p1 === p2 on timeframe switch (when cap >= 2)
            if (p1Val === p2Val && cap >= 2) {
                if (p1Val < cap) {
                    p2Val = p1Val + 1;
                } else {
                    p2Val = p1Val - 1;
                }
            }

            populatePeriodOptions(p1Sel, cap, p1Val, Math.min(3, cap));
            populatePeriodOptions(p2Sel, cap, p2Val, Math.min(5, cap));

            // Ensure period labels remain clean
            const p1Label = card.querySelector('.ema-p1-label');
            const p2Label = card.querySelector('.ema-p2-label');
            if (p1Label) p1Label.textContent = 'First EMA';
            if (p2Label) p2Label.textContent = 'Second EMA';
        }

        // Initialize periods
        updatePeriodsForTf(initTf, initP1, initP2);

        // Timeframe button clicks
        tfButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                tfButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const tf = btn.dataset.tf;
                updatePeriodsForTf(tf);
                updateEmaCardPreview(card);
                onConditionChanged();
            });
        });

        // Period select changes (strictly preserve selection order; do not swap)
        p1Sel.addEventListener('change', () => {
            updateEmaCardPreview(card);
            onConditionChanged();
        });

        p2Sel.addEventListener('change', () => {
            updateEmaCardPreview(card);
            onConditionChanged();
        });

        // State button clicks
        stateButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                stateButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                updateEmaCardPreview(card);
                onConditionChanged();
            });
        });

        // Expand / Collapse functionality
        function toggleCollapse() {
            card.classList.toggle('is-collapsed');
            const isCollapsed = card.classList.contains('is-collapsed');
            if (toggleBtn) {
                toggleBtn.textContent = isCollapsed ? '▸' : '▾';
                toggleBtn.title = isCollapsed ? 'Expand condition' : 'Collapse condition';
            }
        }

        if (toggleBtn) {
            toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleCollapse();
            });
        }

        // Clicking the header when collapsed expands it
        if (cardHeader) {
            cardHeader.addEventListener('click', (e) => {
                if (e.target.closest('.btn-remove-ema-card')) return;
                if (card.classList.contains('is-collapsed')) {
                    toggleCollapse();
                }
            });
        }

        // Remove button click
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            card.remove();
            updateEmaCardIndices();
            updateActiveRuleCount();
            onConditionChanged();
        });

        updateEmaCardPreview(card);
        parentEl.appendChild(card);
        updateEmaCardIndices();
        updateActiveRuleCount();
        return card;
    }

    if (addEmaConditionBtn && emaConditionsContainer) {
        addEmaConditionBtn.addEventListener('click', () => {
            // Collapse existing cards so new card takes prominence
            document.querySelectorAll('.ema-condition-card').forEach(c => {
                c.classList.add('is-collapsed');
                const tBtn = c.querySelector('.btn-toggle-ema-card');
                if (tBtn) {
                    tBtn.textContent = '▸';
                    tBtn.title = 'Expand condition';
                }
            });
            createEmaConditionCard(emaConditionsContainer);
            onConditionChanged();
        });
    }

    if (emaGroupMatchSelect) {
        emaGroupMatchSelect.addEventListener('change', () => {
            onConditionChanged();
        });
    }

    function extractEmaConditions() {
        const cards = document.querySelectorAll('.ema-condition-card');
        const rules = [];
        cards.forEach(card => {
            const tf = card.querySelector('.ema-tf-btn.active')?.dataset.tf || 'D';
            const p1 = parseInt(card.querySelector('.ema-p1-select')?.value, 10);
            const p2 = parseInt(card.querySelector('.ema-p2-select')?.value, 10);
            const state = card.querySelector('.ema-state-btn.active')?.dataset.state || 'UPCUT';

            if (isNaN(p1) || isNaN(p2) || p1 === p2 || p1 < 1 || p2 < 1 || tf === 'Y') {
                return;
            }

            rules.push({
                field: `EMA_${tf}_${p1}_${p2}`,
                op: '==',
                value: state,
                condition_type: 'ema',
                timeframe: tf,
                p1: p1,
                p2: p2,
                state: state,
                lookback: 1
            });
        });
        return rules;
    }

    // Initialize 1 default EMA condition card if container is empty
    if (emaConditionsContainer && emaConditionsContainer.children.length === 0) {
        createEmaConditionCard(emaConditionsContainer);
    }

    // Retain legacy shortcut buttons & sync functions for backward test compatibility
    const emaToggleButtons = document.querySelectorAll('#emaQuickToggles .ema-btn');
    function syncEmaTogglesFromRules() {
        if (!emaToggleButtons.length) return;
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

    // Grouped Band Position Shortcut Handler (Batch U3)
    document.getElementById('applyBandPositionBtn')?.addEventListener('click', () => {
        const select = document.getElementById('quickBandPositionSelect');
        const pos = select?.value;
        if (!pos) {
            showToast('Please select a band position shortcut first.', 'info');
            return;
        }

        if (pos === 'above_m') {
            createRuleRow(rulesContainer, { field: 'BANDST_M', op: '==', value: 'ABOVE' });
        } else if (pos === 'inside_m') {
            createRuleRow(rulesContainer, { field: 'BANDST_M', op: '==', value: 'IN' });
        } else if (pos === 'below_m') {
            createRuleRow(rulesContainer, { field: 'BANDST_M', op: '==', value: 'BELOW' });
        } else if (pos === 'outside_2plus') {
            createNestedGroupCard(rulesContainer, {
                match: 'any',
                rules: [
                    { field: 'N_ABOVE', op: '>=', value: 2 },
                    { field: 'N_BELOW', op: '>=', value: 2 }
                ]
            });
        } else if (pos === 'reaction') {
            createRuleRow(rulesContainer, { field: 'BANDST_Y', op: '==', value: 'BELOW' });
            createRuleRow(rulesContainer, { field: 'EMA_W', op: '==', value: 'upcut' });
        }

        select.value = '';
        onConditionChanged();
        showToast('Applied band position shortcut rule.', 'info');
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

    // Rank Cutoffs Builder Helper
    const cutoffsContainer = document.getElementById('cutoffsContainer');

    function addCutoffRow(metric = 'RANK_M', maxRank = 100) {
        if (!cutoffsContainer) return null;
        const row = document.createElement('div');
        row.className = 'cutoff-row';
        row.innerHTML = `
            <select class="form-control form-control-sm cutoff-metric">
                <option value="RANK_M" ${metric === 'RANK_M' ? 'selected' : ''}>Month Rank (RANK_M)</option>
                <option value="RANK_Y" ${metric === 'RANK_Y' ? 'selected' : ''}>Year Rank (RANK_Y)</option>
                <option value="RANK_W" ${metric === 'RANK_W' ? 'selected' : ''}>Week Rank (RANK_W)</option>
                <option value="RANK_Q" ${metric === 'RANK_Q' ? 'selected' : ''}>Quarter Rank (RANK_Q)</option>
                <option value="RANK_H" ${metric === 'RANK_H' ? 'selected' : ''}>Half-Year Rank (RANK_H)</option>
                <option value="RANK_D" ${metric === 'RANK_D' ? 'selected' : ''}>Day Rank (RANK_D)</option>
            </select>
            <span style="font-size:11px">&le;</span>
            <input type="number" class="form-control form-control-sm cutoff-max" value="${maxRank}" min="1" max="2000" style="width: 70px;">
            <button type="button" class="btn-remove" title="Remove cutoff">×</button>
        `;
        row.querySelector('.btn-remove').addEventListener('click', () => {
            row.remove();
            onConditionChanged();
        });
        row.querySelector('.cutoff-metric').addEventListener('change', onConditionChanged);
        row.querySelector('.cutoff-max').addEventListener('input', onConditionChanged);
        cutoffsContainer.appendChild(row);
        onConditionChanged();
        return row;
    }

    document.getElementById('addCutoffBtn')?.addEventListener('click', () => {
        addCutoffRow('RANK_M', 100);
    });

    // Multi-Period Rank Cutoff Convenience Templates (Batch U3)
    document.getElementById('cutoffTemplateSelect')?.addEventListener('change', (e) => {
        const val = e.target.value;
        if (!val) return;

        if (val === 'top100_m_y') {
            addCutoffRow('RANK_M', 100);
            addCutoffRow('RANK_Y', 100);
        } else if (val === 'top50_all_q') {
            addCutoffRow('RANK_Q', 50);
            addCutoffRow('RANK_H', 50);
        } else if (val === 'top100_all_tf') {
            addCutoffRow('RANK_W', 100);
            addCutoffRow('RANK_M', 100);
            addCutoffRow('RANK_Y', 100);
        }

        e.target.value = '';
        onConditionChanged();
        showToast('Applied rank cutoff template.', 'info');
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
        let universeText = `Universe: ${exch}${segLabel}`;
        const sector = document.getElementById('universeSectorSelect')?.value;
        if (sector) universeText += ` · ${sector}`;
        const instr = document.getElementById('universeInstrSelect')?.value;
        if (instr && instr !== 'ALL') universeText += ` · ${instr}`;
        if (document.getElementById('universeMicrocapToggle')?.checked) universeText += ' · <100cr';
        if (universeEl) universeEl.textContent = universeText;

        if (presetEl) {
            if (loadedPresetName) {
                presetEl.textContent = `Preset: ${loadedPresetName}${isPresetModified ? ' (Modified)' : ''}`;
            } else {
                presetEl.textContent = 'Preset: Custom';
            }
        }

        const ruleCount = document.querySelectorAll('.rule-card').length + document.querySelectorAll('.ema-condition-card').length;
        const isRootNegated = document.getElementById('rootGroupNotToggle')?.classList.contains('active');
        if (condEl) {
            const notPrefix = isRootNegated ? 'NOT ' : '';
            condEl.textContent = `${notPrefix}${ruleCount} ${ruleCount === 1 ? 'Condition' : 'Conditions'}`;
        }

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
        const cutoffCount = document.querySelectorAll('.cutoff-row').length;
        if (selEl) {
            let text = limitVal ? `Top ${limitVal}` : 'All Qualified';
            if (cutoffCount > 0) {
                text += ` (+${cutoffCount} Cutoff${cutoffCount > 1 ? 's' : ''})`;
            }
            selEl.textContent = text;
        }

        // Revert button state
        const revertBtn = document.getElementById('revertPresetBtn');
        if (revertBtn) {
            revertBtn.disabled = !loadedPresetName || !isPresetModified;
        }
    }

    // -------------------------------------------------------------------------
    // 11. Screen Execution Pipeline & Funnel Telemetry
    // -------------------------------------------------------------------------
    function extractFilterGroup(containerEl, matchType = 'all', isNegated = false) {
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
                if (op === 'blank' || op === 'not_blank') {
                    val = null;
                } else if (meta.type === 'enum' && meta.options && op !== 'in' && op !== 'not_in') {
                    val = card.querySelector('.rule-val-select').value;
                } else {
                    val = card.querySelector('.rule-val-input').value.trim();
                }

                if (op === 'in' || op === 'not_in') {
                    if (typeof val === 'string') {
                        val = val.split(',').map(s => s.trim()).filter(Boolean);
                    }
                } else if (val !== null && !isNaN(Number(val)) && val !== '') {
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
            const subNot = grpCard.querySelector('.group-not-toggle')?.classList.contains('active') || false;
            const subContainer = grpCard.querySelector('.nested-rules-list');
            const subGroup = extractFilterGroup(subContainer, subMatch, subNot);
            if (subGroup && subGroup.rules.length > 0) {
                rules.push(subGroup);
            }
        });

        return rules.length > 0 ? { match: matchType, rules, is_negated: isNegated } : null;
    }

    function buildScreenPayload(options = {}) {
        if (options && options.unconstrained) {
            const rankingMetric = document.getElementById('rankingMetric')?.value || null;
            const rankingOrder = document.getElementById('rankingOrder')?.value || 'desc';
            const limitVal = parseInt(document.getElementById('screenLimit')?.value, 10) || null;
            const colsVal = document.getElementById('customColumns')?.value.trim();
            const cols = colsVal ? colsVal.split(',').map(c => c.trim()).filter(Boolean) : null;
            return {
                filter_group: null,
                ranking_metric: rankingMetric,
                ranking_order: rankingOrder,
                selection_cutoffs: [],
                limit: limitVal,
                columns: cols
            };
        }

        const rootMatch = document.getElementById('rootGroupMatch')?.value || 'all';
        const rootNot = document.getElementById('rootGroupNotToggle')?.classList.contains('active') || false;
        const filterGroup = extractFilterGroup(rulesContainer, rootMatch, rootNot);

        // Universe filtering (Segment, Sector, Instrument Type, Microcap)
        let activeFilterGroup = filterGroup;
        const segment = document.getElementById('universeSegment')?.value || 'ALL';
        const universeRules = [];
        if (segment === 'FNO') {
            universeRules.push({ field: 'fno', op: '==', value: 'Y' });
        } else if (segment === 'CASH') {
            universeRules.push({ field: 'fno', op: '==', value: 'N' });
        }

        const sectorVal = document.getElementById('universeSectorSelect')?.value || '';
        if (sectorVal) {
            universeRules.push({ field: 'sector', op: '==', value: sectorVal });
        }

        const instrVal = document.getElementById('universeInstrSelect')?.value || '';
        if (instrVal && instrVal !== 'ALL') {
            universeRules.push({ field: 'instr', op: '==', value: instrVal });
        }

        const microcapChecked = document.getElementById('universeMicrocapToggle')?.checked || false;
        if (microcapChecked) {
            universeRules.push({ field: 'mcap', op: '<', value: 100 });
        }

        if (universeRules.length > 0) {
            if (!activeFilterGroup) {
                activeFilterGroup = { match: 'all', rules: universeRules, is_negated: false };
            } else if (activeFilterGroup.match === 'all' && !activeFilterGroup.is_negated) {
                activeFilterGroup = {
                    match: 'all',
                    rules: [...activeFilterGroup.rules, ...universeRules],
                    is_negated: false
                };
            } else {
                activeFilterGroup = {
                    match: 'all',
                    rules: [activeFilterGroup, ...universeRules],
                    is_negated: false
                };
            }
        }

        // EMA dynamic condition builder rules
        const emaRules = extractEmaConditions();
        if (emaRules.length > 0) {
            const emaMatch = document.getElementById('emaGroupMatch')?.value || 'all';
            let emaNode = null;
            if (emaRules.length === 1) {
                emaNode = emaRules[0];
            } else {
                emaNode = {
                    match: emaMatch,
                    rules: emaRules,
                    is_negated: false
                };
            }

            if (!activeFilterGroup) {
                activeFilterGroup = emaNode.rules ? emaNode : { match: 'all', rules: [emaNode], is_negated: false };
            } else if (activeFilterGroup.match === 'all' && !activeFilterGroup.is_negated) {
                if (emaRules.length === 1) {
                    activeFilterGroup.rules.push(emaRules[0]);
                } else if (emaMatch === 'all') {
                    activeFilterGroup.rules.push(...emaRules);
                } else {
                    activeFilterGroup.rules.push(emaNode);
                }
            } else {
                activeFilterGroup = {
                    match: 'all',
                    rules: [activeFilterGroup, emaNode],
                    is_negated: false
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

    let activeScreenRequestId = null;
    let activeScreenAbortController = null;
    let activeScreenPollTimer = null;
    let activeScreenState = 'idle'; // 'idle', 'running', 'cancelling', 'completed', 'cancelled', 'failed'

    async function runScreen(options = {}) {
        // Prevent accidental duplicate submissions while a request is active
        if (activeScreenState === 'running') {
            return;
        }

        const btn = document.getElementById('runScreenBtn');
        const runTextEl = document.getElementById('runScreenText');
        const cancelBtn = document.getElementById('cancelScreenBtn');
        const isInitial = Boolean(options && options.unconstrained);

        const requestId = 'scr_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
        activeScreenRequestId = requestId;
        activeScreenState = 'running';
        activeScreenAbortController = new AbortController();

        const prefix = isInitial ? 'Loading...' : 'Screening...';
        if (btn) {
            btn.disabled = true;
            if (runTextEl) runTextEl.textContent = prefix;
            else btn.textContent = prefix;
        }

        if (cancelBtn) {
            cancelBtn.style.display = 'inline-flex';
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = '<span class="icon">⏹</span> CANCEL';
        }

        const tbody = document.getElementById('tableBody');
        const hasExistingRows = tbody && tbody.querySelectorAll('tr:not(.empty-state)').length > 0 && !tbody.querySelector('.empty-guide-card');

        // Provide clean feedback: if no rows are present, show table loader
        if (tbody && !hasExistingRows) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="16" class="empty-state">
                        <div class="empty-guide-card">
                            <div class="spinner" style="margin: 0 auto 16px auto; width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.15); border-top-color: var(--accent, #6366f1); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
                            <h3>${isInitial ? 'Loading Stock Universe...' : 'Screening Stock Universe...'}</h3>
                            <p>${isInitial ? 'Retrieving market data from persistent cache.' : 'Evaluating screening conditions and ranking qualified stocks.'}</p>
                        </div>
                    </td>
                </tr>
            `;
        } else if (hasExistingRows) {
            document.getElementById('resultsTable')?.classList.add('table-screening-in-progress');
        }

        try {
            const req = buildScreenPayload(options);
            req.request_id = requestId;
            showToast(isInitial ? 'Loading market universe...' : 'Running multi-timeframe screen...', 'info');

            const payload = await API.runScreen(req, activeScreenAbortController.signal);

            // Stale check: ignore late responses belonging to older or cancelled requests
            if (activeScreenRequestId !== requestId) {
                return;
            }

            activeScreenState = 'completed';
            updateTableResults(payload);
            showToast(isInitial ? `Loaded ${payload.universe_count} stocks` : `Screen matched ${payload.qualified_count} stocks (${payload.selected_count} selected)`, 'success');
        } catch (err) {
            // If request was aborted or cancelled, do not publish errors or clear existing results
            if (activeScreenRequestId !== requestId || err.name === 'AbortError' || (err.message && err.message.includes('cancelled'))) {
                return;
            }

            activeScreenState = 'failed';
            showToast(`Screening failed: ${err.message}`, 'error');
            if (tbody && !hasExistingRows) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="16" class="empty-state">
                            <div class="empty-guide-card">
                                <h3 style="color: var(--danger, #ef4444);">Screening Error</h3>
                                <p>${err.message}</p>
                                <button type="button" class="btn btn-secondary btn-retry-screen">Retry Screen</button>
                            </div>
                        </td>
                    </tr>
                `;
                tbody.querySelector('.btn-retry-screen')?.addEventListener('click', () => runScreen(options));
            }
        } finally {
            if (activeScreenPollTimer) {
                clearInterval(activeScreenPollTimer);
                activeScreenPollTimer = null;
            }

            // If this request is still the active one, transition cleanly to idle
            if (activeScreenRequestId === requestId) {
                activeScreenRequestId = null;
                activeScreenAbortController = null;
                activeScreenState = 'idle';

                if (btn) {
                    btn.disabled = false;
                    if (runTextEl) runTextEl.textContent = 'RUN SCREEN';
                    else btn.textContent = 'RUN SCREEN';
                }
                if (cancelBtn) {
                    cancelBtn.style.display = 'none';
                    cancelBtn.disabled = false;
                    cancelBtn.innerHTML = '<span class="icon">⏹</span> CANCEL';
                }
            }
            document.getElementById('resultsTable')?.classList.remove('table-screening-in-progress');
        }
    }

    async function cancelActiveScreen() {
        if (!activeScreenRequestId || activeScreenState !== 'running') {
            return;
        }

        const reqId = activeScreenRequestId;
        activeScreenState = 'cancelling';

        const btn = document.getElementById('runScreenBtn');
        const runTextEl = document.getElementById('runScreenText');
        const cancelBtn = document.getElementById('cancelScreenBtn');

        if (cancelBtn) {
            cancelBtn.disabled = true;
            cancelBtn.innerHTML = '<span class="icon">⏳</span> CANCELLING...';
        }
        if (runTextEl) runTextEl.textContent = 'Cancelling...';
        else if (btn) btn.textContent = 'Cancelling...';

        showToast('Cancelling screen...', 'info');

        // Stop polling
        if (activeScreenPollTimer) {
            clearInterval(activeScreenPollTimer);
            activeScreenPollTimer = null;
        }

        // Notify backend to cancel the in-flight task
        try {
            await API.cancelScreen(reqId);
        } catch (backendCancelErr) {
            console.warn('Backend cancel error:', backendCancelErr);
        }

        // Abort the fetch request
        if (activeScreenAbortController) {
            try {
                activeScreenAbortController.abort();
            } catch (_) {}
            activeScreenAbortController = null;
        }

        activeScreenState = 'cancelled';
        activeScreenRequestId = null;

        // Return immediately to filter-selection workflow
        if (btn) {
            btn.disabled = false;
            if (runTextEl) runTextEl.textContent = 'RUN SCREEN';
            else btn.textContent = 'RUN SCREEN';
        }
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = '<span class="icon">⏹</span> CANCEL';
        }
        document.getElementById('resultsTable')?.classList.remove('table-screening-in-progress');
        showToast('Screening cancelled.', 'info');
    }

    document.getElementById('runScreenBtn')?.addEventListener('click', () => runScreen());
    document.getElementById('cancelScreenBtn')?.addEventListener('click', cancelActiveScreen);

    const discoveredSectors = new Set();

    function updateDiscoveredSectors(rows) {
        const sectorSelect = document.getElementById('universeSectorSelect');
        if (!sectorSelect || !rows || rows.length === 0) return;

        let addedNew = false;
        rows.forEach(r => {
            if (r.sector && typeof r.sector === 'string' && r.sector.trim()) {
                const s = r.sector.trim();
                if (!discoveredSectors.has(s)) {
                    discoveredSectors.add(s);
                    addedNew = true;
                }
            }
        });

        if (addedNew) {
            const currentVal = sectorSelect.value;
            const sortedSectors = Array.from(discoveredSectors).sort();
            sectorSelect.innerHTML = '<option value="">All Sectors</option>' +
                sortedSectors.map(s => `<option value="${s}">${s}</option>`).join('');
            sectorSelect.value = currentVal;
        }
    }

    function updateTableResults(payload) {
        // Update discovered sectors from incoming rows
        if (payload.rows && payload.rows.length > 0) {
            updateDiscoveredSectors(payload.rows);
        }

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
    // 12. Stock Detail Slide-Over Drawer & Chart Viewport (Batch U1 Workspace)
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

        // Increment request ID to guard against out-of-order async race conditions
        currentStockDrawerRequestId++;
        const reqId = currentStockDrawerRequestId;

        // Immediately clear previous chart and indicators to avoid stale display
        chart.clear();

        const symbolEl = document.getElementById('activeSymbol');
        const nameEl = document.getElementById('activeStockName');
        const priceEl = document.getElementById('activePrice');
        const sectorBadge = document.getElementById('activeSectorBadge');
        const capBadge = document.getElementById('activeCapBadge');
        const gradeBadge = document.getElementById('activeGradeBadge');
        const fnoBadge = document.getElementById('activeFnoBadge');
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
        const bandTfSelect = document.getElementById('bandTfSelect');

        if (symbolEl) symbolEl.textContent = symbol;
        if (nameEl) {
            nameEl.textContent = '';
            nameEl.style.display = 'none';
        }
        if (priceEl) priceEl.textContent = '—';
        if (sectorBadge) sectorBadge.style.display = 'none';
        if (capBadge) capBadge.style.display = 'none';
        if (gradeBadge) gradeBadge.style.display = 'none';
        if (fnoBadge) fnoBadge.style.display = 'none';
        if (athBadge) athBadge.style.display = 'none';
        if (icBadge) icBadge.style.display = 'none';
        if (bandStatusBadge) bandStatusBadge.style.display = 'none';
        if (basisEl) basisEl.textContent = '—';
        if (upperEl) upperEl.textContent = '—';
        if (lowerEl) lowerEl.textContent = '—';
        if (widthEl) widthEl.textContent = '—';
        if (widthInput) widthInput.value = '';
        if (bandTfSelect) bandTfSelect.value = activeBandTimeframe;
        if (errorMsg) {
            errorMsg.textContent = '';
            errorMsg.style.display = 'none';
        }
        if (signalsStrip) signalsStrip.innerHTML = '';
        if (matrixBody) {
            matrixBody.innerHTML = `<tr><td colspan="7" class="empty-matrix">Loading live multi-timeframe analytics for ${symbol}...</td></tr>`;
        }
        if (loadingOverlay) loadingOverlay.style.display = 'flex';

        // Synchronize active panel on chart controller
        chart.setActivePanel(activePanel);

        // Trigger chart resize for the drawer container
        chart.resize();

        const reqSym = symbol;
        try {
            await Promise.all([
                loadChartData(reqSym, reqId),
                loadStockPanel(reqSym, reqId)
            ]);
        } catch (err) {
            if (activeSymbol === reqSym && currentStockDrawerRequestId === reqId) {
                if (errorMsg) {
                    errorMsg.textContent = `Unable to load data for ${reqSym}: ${err.message}`;
                    errorMsg.style.display = 'block';
                }
            }
        } finally {
            if (activeSymbol === reqSym && currentStockDrawerRequestId === reqId && loadingOverlay) {
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
        closeAllDrawerPopovers();
        if (typeof chart.cancelMeasure === 'function') {
            chart.cancelMeasure();
        }
    }

    function closeAllDrawerPopovers() {
        const overlaysMenu = document.getElementById('overlaysMenu');
        const panelsMenu = document.getElementById('panelsMenu');
        const overlaysBtn = document.getElementById('overlaysToggleBtn');
        const panelsBtn = document.getElementById('panelsToggleBtn');

        if (overlaysMenu) overlaysMenu.style.display = 'none';
        if (panelsMenu) panelsMenu.style.display = 'none';
        if (overlaysBtn) overlaysBtn.setAttribute('aria-expanded', 'false');
        if (panelsBtn) panelsBtn.setAttribute('aria-expanded', 'false');
    }

    document.getElementById('drawerCloseBtn')?.addEventListener('click', closeStockDrawer);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const overlaysMenu = document.getElementById('overlaysMenu');
            const panelsMenu = document.getElementById('panelsMenu');
            const isOverlayOpen = overlaysMenu && overlaysMenu.style.display !== 'none';
            const isPanelsOpen = panelsMenu && panelsMenu.style.display !== 'none';

            if (isOverlayOpen || isPanelsOpen) {
                closeAllDrawerPopovers();
                return;
            }

            const drawer = document.getElementById('stockDetailDrawer');
            if (drawer && drawer.classList.contains('open')) {
                closeStockDrawer();
            }
        }
    });

    // Close popovers when clicking outside
    document.addEventListener('click', (e) => {
        const overlaysDropdown = document.getElementById('overlaysDropdown');
        const panelsDropdown = document.getElementById('panelsDropdown');
        if (overlaysDropdown && !overlaysDropdown.contains(e.target)) {
            const m = document.getElementById('overlaysMenu');
            if (m) m.style.display = 'none';
            document.getElementById('overlaysToggleBtn')?.setAttribute('aria-expanded', 'false');
        }
        if (panelsDropdown && !panelsDropdown.contains(e.target)) {
            const m = document.getElementById('panelsMenu');
            if (m) m.style.display = 'none';
            document.getElementById('panelsToggleBtn')?.setAttribute('aria-expanded', 'false');
        }
    });

    // 1. Chart Timeframe Toolbar Buttons
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

    // 2. Band Timeframe Selector
    const bandTfSelect = document.getElementById('bandTfSelect');
    if (bandTfSelect) {
        bandTfSelect.addEventListener('change', async () => {
            activeBandTimeframe = bandTfSelect.value;
            if (activeSymbol) {
                await loadChartData(activeSymbol);
            }
        });
    }

    // 3. Overlays Dropdown & Checkboxes
    const overlaysToggleBtn = document.getElementById('overlaysToggleBtn');
    const overlaysMenu = document.getElementById('overlaysMenu');
    if (overlaysToggleBtn && overlaysMenu) {
        overlaysToggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = overlaysMenu.style.display !== 'none';
            closeAllDrawerPopovers();
            if (!isOpen) {
                overlaysMenu.style.display = 'block';
                overlaysToggleBtn.setAttribute('aria-expanded', 'true');
            }
        });
    }

    const overlayCheckboxes = [
        { id: 'chkEma3', key: 'ema3' },
        { id: 'chkEma5', key: 'ema5' },
        { id: 'chkSma20', key: 'sma20' },
        { id: 'chkAvgPrice', key: 'avg_price' },
        { id: 'chkBands', key: 'bands' },
        { id: 'chkBollinger', key: 'bollinger' },
        { id: 'chkDonchian', key: 'donchian' },
        { id: 'chkAtrBands', key: 'atr_bands' },
        { id: 'chkVwap', key: 'vwap' },
        { id: 'chkVolume', key: 'volume' },
    ];

    overlayCheckboxes.forEach(({ id, key }) => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => {
                chart.setOverlay(key, el.checked);
            });
        }
    });

    // 4. Analytical Panels Dropdown
    const panelsToggleBtn = document.getElementById('panelsToggleBtn');
    const panelsMenu = document.getElementById('panelsMenu');
    const activePanelLabel = document.getElementById('activePanelLabel');
    if (panelsToggleBtn && panelsMenu) {
        panelsToggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = panelsMenu.style.display !== 'none';
            closeAllDrawerPopovers();
            if (!isOpen) {
                panelsMenu.style.display = 'block';
                panelsToggleBtn.setAttribute('aria-expanded', 'true');
            }
        });
    }

    const panelButtons = document.querySelectorAll('#panelsMenu .menu-option-btn');
    panelButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            panelButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activePanel = btn.dataset.panel || 'none';

            const panelNames = {
                none: 'None',
                rsi: 'RSI (14)',
                macd: 'MACD (12, 26, 9)',
                dmi: 'DMI / ADX',
                obv: 'OBV',
                mfi: 'MFI (14)',
                sprint: 'Sprint Speed',
                accel: 'Acceleration',
                band_dist: 'Band Distance',
                yogi_roc: 'YOGI ROC',
            };
            const label = panelNames[activePanel] || 'None';
            if (activePanelLabel) {
                activePanelLabel.textContent = `Panels: ${label} ▾`;
            }

            chart.setActivePanel(activePanel);
            closeAllDrawerPopovers();
        });
    });

    // Close sub-chart button
    document.getElementById('closeSubChartBtn')?.addEventListener('click', () => {
        activePanel = 'none';
        panelButtons.forEach(b => {
            if (b.dataset.panel === 'none') b.classList.add('active');
            else b.classList.remove('active');
        });
        if (activePanelLabel) activePanelLabel.textContent = 'Panels: None ▾';
        chart.setActivePanel('none');
    });

    // 5. Chart Point-to-Point Measurement Tool (Batch U4)
    const chartMeasureBtn = document.getElementById('chartMeasureBtn');
    const measureHud = document.getElementById('measureHud');
    const measureHudStep = document.getElementById('measureHudStep');
    const measureHudResult = document.getElementById('measureHudResult');
    const measureResetBtn = document.getElementById('measureResetBtn');

    if (chartMeasureBtn) {
        chartMeasureBtn.addEventListener('click', () => {
            const isMeasuring = chart.toggleMeasure();
            chartMeasureBtn.classList.toggle('active', isMeasuring);
        });
    }

    if (measureResetBtn) {
        measureResetBtn.addEventListener('click', () => {
            chart.cancelMeasure();
        });
    }

    chart.onMeasureChange = (state) => {
        if (chartMeasureBtn) {
            chartMeasureBtn.classList.toggle('active', !!state.active);
        }

        if (!measureHud) return;
        if (!state.active) {
            measureHud.style.display = 'none';
            if (measureHudResult) measureHudResult.style.display = 'none';
            return;
        }

        measureHud.style.display = 'inline-flex';
        if (state.step === 1) {
            if (measureHudStep) measureHudStep.textContent = 'Click 1st point (Start Price)';
            if (measureHudResult) measureHudResult.style.display = 'none';
        } else if (state.step === 2 && state.p1) {
            if (measureHudStep) measureHudStep.textContent = `P1: ₹${state.p1.price.toFixed(2)} — Click 2nd point`;
            if (measureHudResult) measureHudResult.style.display = 'none';
        } else if (state.step === 3 && state.p1 && state.p2) {
            const sign = state.deltaPct >= 0 ? '+' : '';
            if (measureHudStep) measureHudStep.textContent = `₹${state.p1.price.toFixed(2)} → ₹${state.p2.price.toFixed(2)}`;
            if (measureHudResult) {
                measureHudResult.style.display = 'inline-block';
                measureHudResult.className = `measure-hud-result ${state.deltaPct >= 0 ? 'val-positive' : 'val-negative'}`;
                measureHudResult.textContent = `Δ: ${sign}${state.deltaPct.toFixed(2)}% (${sign}₹${state.deltaAbs.toFixed(2)})`;
            }
        }
    };

    async function loadChartData(symbol, reqId = null) {
        const target = symbol || activeSymbol;
        if (!target) return;
        const currentId = reqId || currentStockDrawerRequestId;

        try {
            const series = await API.getCandles(target, activeChartTimeframe, activeBandTimeframe);
            if (activeSymbol !== target || currentStockDrawerRequestId !== currentId) return; // Discard stale response

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
                if (basisEl) basisEl.textContent = (b.basis !== null && b.basis !== undefined) ? `₹${Number(b.basis).toFixed(2)}` : '—';
                if (upperEl) upperEl.textContent = (b.upper !== null && b.upper !== undefined) ? `₹${Number(b.upper).toFixed(2)}` : '—';
                if (lowerEl) lowerEl.textContent = (b.lower !== null && b.lower !== undefined) ? `₹${Number(b.lower).toFixed(2)}` : '—';
                if (widthEl) widthEl.textContent = (b.width !== null && b.width !== undefined) ? `${(b.width * 100).toFixed(1)}%` : '—';
                if (widthInput) widthInput.value = (b.width !== null && b.width !== undefined) ? (b.width * 100).toFixed(1) : '';
            } else {
                if (basisEl) basisEl.textContent = '—';
                if (upperEl) upperEl.textContent = '—';
                if (lowerEl) lowerEl.textContent = '—';
                if (widthEl) widthEl.textContent = '—';
                if (widthInput) widthInput.value = '';
            }
        } catch (err) {
            if (activeSymbol === target && currentStockDrawerRequestId === currentId) {
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
                showToast(`Band width for ${activeSymbol} (${activeChartTimeframe}) saved at ${pctVal}%`, 'success');
                currentStockDrawerRequestId++;
                const reqId = currentStockDrawerRequestId;
                const [chartRes, panelRes] = await Promise.allSettled([
                    loadChartData(activeSymbol, reqId),
                    loadStockPanel(activeSymbol, reqId)
                ]);
                if (chartRes.status === 'rejected') {
                    showToast(`Band saved, but chart refresh failed: ${chartRes.reason?.message || 'Network error'}`, 'warning');
                }
                if (panelRes.status === 'rejected') {
                    showToast(`Band saved, but matrix refresh failed: ${panelRes.reason?.message || 'Network error'}`, 'warning');
                }
            } catch (err) {
                showToast(`Failed to save band: ${err.message}`, 'error');
            } finally {
                saveBandBtn.disabled = false;
            }
        });
    }

    async function loadStockPanel(symbol, reqId = null) {
        const target = symbol || activeSymbol;
        if (!target) return;
        const currentId = reqId || currentStockDrawerRequestId;

        const matrixBody = document.getElementById('liveMatrixBody');
        const drawerMeta = document.getElementById('drawerMeta');
        const nameEl = document.getElementById('activeStockName');
        const sectorBadge = document.getElementById('activeSectorBadge');
        const capBadge = document.getElementById('activeCapBadge');
        const gradeBadge = document.getElementById('activeGradeBadge');
        const fnoBadge = document.getElementById('activeFnoBadge');
        const athDiffBadge = document.getElementById('activeAthDiff');
        const icBadge = document.getElementById('activeIcBadge');
        const bandStatusBadge = document.getElementById('activeBandStatus');
        if (!matrixBody) return;

        try {
            const panel = await API.getStockPanel(target);
            if (activeSymbol !== target || currentStockDrawerRequestId !== currentId) return; // Discard stale response

            if (drawerMeta) {
                drawerMeta.textContent = `${panel.symbol} · ${panel.exchange || 'NSE'} · Live Analytical Matrix`;
            }

            // Populate Metadata Badges
            if (nameEl) {
                if (panel.name) {
                    nameEl.textContent = panel.name;
                    nameEl.style.display = 'inline';
                } else {
                    nameEl.style.display = 'none';
                }
            }

            if (sectorBadge) {
                if (panel.sector) {
                    sectorBadge.textContent = panel.sector;
                    sectorBadge.style.display = 'inline-block';
                } else {
                    sectorBadge.style.display = 'none';
                }
            }

            if (capBadge) {
                const grp = panel.grp || '';
                const mcap = panel.mcap;
                if (grp) {
                    let capText = grp;
                    if (mcap && typeof mcap === 'number') {
                        capText += ` · ₹${mcap.toFixed(1)} Cr`;
                    }
                    capBadge.textContent = capText;
                    capBadge.style.display = 'inline-block';
                } else {
                    capBadge.style.display = 'none';
                }
            }

            if (gradeBadge) {
                if (panel.grade) {
                    gradeBadge.textContent = `Grade ${panel.grade}`;
                    gradeBadge.style.display = 'inline-block';
                } else {
                    gradeBadge.style.display = 'none';
                }
            }

            if (fnoBadge) {
                if (panel.fno === 'Y' || panel.fno === 'YES') {
                    fnoBadge.style.display = 'inline-block';
                } else {
                    fnoBadge.style.display = 'none';
                }
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

            // Build Categorized Multi-Timeframe Matrix
            const tfs = panel.timeframes || [];
            const km = panel.key_metrics || {};

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
                const dist = row.band_distance !== null && row.band_distance !== undefined ? ` (${row.band_distance > 0 ? '+' : ''}${row.band_distance.toFixed(1)}%)` : '';
                if (st === 'ABOVE') return `<span class="badge badge-above">ABOVE${dist}</span>`;
                if (st === 'BELOW') return `<span class="badge badge-below">BELOW${dist}</span>`;
                if (st === 'IN') return `<span class="badge badge-in">IN${dist}</span>`;
                return '<span class="val-null">—</span>';
            }

            function renderDmiCell(row) {
                const tf = row.timeframe;
                const state = km[`DMI_STATE_${tf}`];
                const adx = km[`ADX_${tf}`];
                if (!state || state === 'na') return '<span class="val-null">—</span>';
                const adxPart = (typeof adx === 'number' && !isNaN(adx)) ? ` (${adx.toFixed(0)})` : '';
                if (state === 'bullish') {
                    return `<span class="badge badge-above">BULL${adxPart}</span>`;
                }
                if (state === 'bearish') {
                    return `<span class="badge badge-below">BEAR${adxPart}</span>`;
                }
                return `<span class="badge badge-in">NEUTRAL${adxPart}</span>`;
            }

            function renderRocCell(row) {
                if (row.roc === null || row.roc === undefined) return '<span class="val-null">—</span>';
                const f = row.roc.toFixed(2);
                return `<span class="${row.roc >= 0 ? 'val-positive' : 'val-negative'}">${row.roc >= 0 ? '+' : ''}${f}%</span>`;
            }

            function renderSpeedCell(row) {
                if (row.timeframe === 'D') return '<span class="val-null" title="Sprint velocity is defined for Weekly (W) and higher timeframes">N/A</span>';
                if (row.speed === null || row.speed === undefined) return '<span class="val-null">—</span>';
                const f = row.speed.toFixed(2);
                return `<span class="${row.speed >= 0 ? 'val-positive' : 'val-neutral'}">${row.speed >= 0 ? '+' : ''}${f}%</span>`;
            }

            function renderBandWidthCell(row) {
                const val = (row.band_width !== null && row.band_width !== undefined) ? (row.band_width * 100).toFixed(1) : '';
                return `
                    <div class="matrix-band-edit-wrap">
                        <input type="number" step="0.5" min="0" max="100" class="matrix-band-input" data-tf="${row.timeframe}" data-confirmed-val="${val}" value="${val}" placeholder="—" title="Press Enter to save ${row.timeframe} band width" />
                    </div>
                `;
            }

            function renderLevelCell(val) {
                if (val === null || val === undefined) return '<span class="val-null">—</span>';
                return `<span>₹${val.toFixed(2)}</span>`;
            }

            matrixBody.innerHTML = `
                <!-- Category 1: TREND & ALIGNMENT -->
                <tr class="matrix-section-header"><th colspan="7">TREND &amp; ALIGNMENT</th></tr>
                <tr>
                    <td class="matrix-metric-name">EMA 3/5 State</td>
                    ${tfs.map(r => `<td>${renderEmaCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td class="matrix-metric-name">Band State &amp; Dist</td>
                    ${tfs.map(r => `<td>${renderBandStateCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td class="matrix-metric-name">DMI Trend</td>
                    ${tfs.map(r => `<td>${renderDmiCell(r)}</td>`).join('')}
                </tr>

                <!-- Category 2: MOMENTUM & SPEED -->
                <tr class="matrix-section-header"><th colspan="7">MOMENTUM &amp; SPEED</th></tr>
                <tr>
                    <td class="matrix-metric-name">Return / ROC %</td>
                    ${tfs.map(r => `<td>${renderRocCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td class="matrix-metric-name">Speed / Velocity</td>
                    ${tfs.map(r => `<td>${renderSpeedCell(r)}</td>`).join('')}
                </tr>

                <!-- Category 3: BANDS & VOLATILITY -->
                <tr class="matrix-section-header"><th colspan="7">BANDS &amp; VOLATILITY</th></tr>
                <tr>
                    <td class="matrix-metric-name">Band Width %</td>
                    ${tfs.map(r => `<td>${renderBandWidthCell(r)}</td>`).join('')}
                </tr>
                <tr>
                    <td class="matrix-metric-name">Upper Level</td>
                    ${tfs.map(r => `<td>${renderLevelCell(r.band_upper)}</td>`).join('')}
                </tr>
                <tr>
                    <td class="matrix-metric-name">Lower Level</td>
                    ${tfs.map(r => `<td>${renderLevelCell(r.band_lower)}</td>`).join('')}
                </tr>
            `;

            // Inline 6-Timeframe Band Tuning Handlers (Enter-to-save)
            matrixBody.querySelectorAll('.matrix-band-input').forEach(input => {
                input.addEventListener('keydown', async (e) => {
                    if (e.key !== 'Enter') return;
                    e.preventDefault();

                    if (!activeSymbol || input.disabled) return;

                    const tf = input.getAttribute('data-tf');
                    const confirmedStr = input.getAttribute('data-confirmed-val') || '';
                    const rawVal = input.value.trim();

                    // Parse and validate numeric input
                    const val = parseFloat(rawVal);
                    if (isNaN(val) || !isFinite(val) || val <= 0 || val > 100) {
                        showToast('Please enter a valid band width percentage between 0 and 100 (e.g. 20 for 20%)', 'error');
                        input.value = confirmedStr;
                        return;
                    }

                    // Check if value is unchanged
                    const confirmedNum = parseFloat(confirmedStr);
                    if (!isNaN(confirmedNum) && Math.abs(val - confirmedNum) < 0.0001) {
                        return; // Avoid unnecessary request when unchanged
                    }

                    const targetSymbol = activeSymbol;
                    input.disabled = true;

                    try {
                        // 1. Commit band update to backend
                        await API.updateBand(targetSymbol, tf, val / 100.0);
                        input.setAttribute('data-confirmed-val', val.toFixed(1));
                        showToast(`${tf} band width updated to ${val}%`, 'success');

                        // 2. Concurrently refresh chart and matrix using current drawer request ID
                        currentStockDrawerRequestId++;
                        const reqId = currentStockDrawerRequestId;

                        const [chartRes, panelRes] = await Promise.allSettled([
                            loadChartData(targetSymbol, reqId),
                            loadStockPanel(targetSymbol, reqId)
                        ]);

                        if (chartRes.status === 'rejected') {
                            console.warn('Chart refresh warning:', chartRes.reason);
                            showToast(`Band width saved, but chart refresh failed: ${chartRes.reason?.message || 'Network error'}`, 'warning');
                        }
                        if (panelRes.status === 'rejected') {
                            console.warn('Panel refresh warning:', panelRes.reason);
                            showToast(`Band width saved, but matrix refresh failed: ${panelRes.reason?.message || 'Network error'}`, 'warning');
                        }
                    } catch (err) {
                        showToast(`Failed to update band: ${err.message}`, 'error');
                        input.value = confirmedStr;
                    } finally {
                        input.disabled = false;
                    }
                });
            });

            // Build Key Technical Signals Strip
            const signalsStrip = document.getElementById('drawerSignalsStrip');
            if (signalsStrip) {
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

                // 3. DMI Daily
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

                // 4. Accelerations
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

            // Historical Period Breakdown & Sprints (Batch U3)
            const historyContent = document.getElementById('drawerHistoryContent');
            if (historyContent) {
                let histHtml = '';

                // Sprints (S4, S13, S26, S52, Accel, Consistency)
                histHtml += `
                    <div class="history-block">
                        <div class="history-block-title">Sprint Velocity &amp; Consistency</div>
                        <div class="history-metrics-grid">
                            <div class="history-metric-card"><span class="hm-label">S4 (4w):</span><span class="hm-val">${km.S4 !== null && km.S4 !== undefined ? `${km.S4.toFixed(1)}%/wk` : '—'}</span></div>
                            <div class="history-metric-card"><span class="hm-label">S13 (13w):</span><span class="hm-val">${km.S13 !== null && km.S13 !== undefined ? `${km.S13.toFixed(1)}%/wk` : '—'}</span></div>
                            <div class="history-metric-card"><span class="hm-label">S26 (26w):</span><span class="hm-val">${km.S26 !== null && km.S26 !== undefined ? `${km.S26.toFixed(1)}%/wk` : '—'}</span></div>
                            <div class="history-metric-card"><span class="hm-label">S52 (52w):</span><span class="hm-val">${km.S52 !== null && km.S52 !== undefined ? `${km.S52.toFixed(1)}%/wk` : '—'}</span></div>
                            <div class="history-metric-card"><span class="hm-label">Short Accel:</span><span class="hm-val">${panel.accel_s !== null && panel.accel_s !== undefined ? `${panel.accel_s >= 0 ? '+' : ''}${panel.accel_s.toFixed(2)}` : '—'}</span></div>
                            <div class="history-metric-card"><span class="hm-label">Long Accel:</span><span class="hm-val">${panel.accel_l !== null && panel.accel_l !== undefined ? `${panel.accel_l >= 0 ? '+' : ''}${panel.accel_l.toFixed(2)}` : '—'}</span></div>
                            <div class="history-metric-card"><span class="hm-label">Sprint Consist:</span><span class="hm-val">${panel.spr_consist !== null && panel.spr_consist !== undefined ? `${panel.spr_consist.toFixed(0)}%` : '—'}</span></div>
                        </div>
                    </div>
                `;

                // Multi-Year CAGRs
                const cagrKeys = Object.keys(km).filter(k => k.startsWith('CAGR_')).sort();
                if (cagrKeys.length > 0) {
                    histHtml += `
                        <div class="history-block">
                            <div class="history-block-title">Compound Annual Growth (CAGR)</div>
                            <div class="history-metrics-grid">
                                ${cagrKeys.map(k => {
                                    const yrs = k.replace('CAGR_', '');
                                    const val = km[k];
                                    const formatted = (val !== null && val !== undefined) ? `${val >= 0 ? '+' : ''}${val.toFixed(1)}%` : '—';
                                    const cls = (val !== null && val !== undefined && val >= 0) ? 'val-positive' : 'val-negative';
                                    return `<div class="history-metric-card"><span class="hm-label">${yrs}Y CAGR:</span><span class="hm-val ${cls}">${formatted}</span></div>`;
                                }).join('')}
                            </div>
                        </div>
                    `;
                }

                // Fixed-Date Anchored Sprints (SPA_A21 .. SPA_A26)
                const spaKeys = Object.keys(km).filter(k => k.startsWith('SPA_A')).sort();
                if (spaKeys.length > 0) {
                    histHtml += `
                        <div class="history-block">
                            <div class="history-block-title">Fixed-Date Anchored Sprints</div>
                            <div class="history-metrics-grid">
                                ${spaKeys.map(k => {
                                    const yr = k.replace('SPA_A', '20');
                                    const val = km[k];
                                    const formatted = (val !== null && val !== undefined) ? `${val >= 0 ? '+' : ''}${val.toFixed(1)}%` : '—';
                                    const cls = (val !== null && val !== undefined && val >= 0) ? 'val-positive' : 'val-negative';
                                    return `<div class="history-metric-card"><span class="hm-label">Jan ${yr}:</span><span class="hm-val ${cls}">${formatted}</span></div>`;
                                }).join('')}
                            </div>
                        </div>
                    `;
                }

                // Annual Returns (Y2025, Y2024, etc.)
                const yearKeys = Object.keys(km).filter(k => k.startsWith('Y20') || k === 'Y_OLDER').sort().reverse();
                if (yearKeys.length > 0) {
                    histHtml += `
                        <div class="history-block">
                            <div class="history-block-title">Calendar Year Returns</div>
                            <div class="history-metrics-grid">
                                ${yearKeys.map(k => {
                                    const yr = k === 'Y_OLDER' ? 'Older' : k.replace('Y', '');
                                    const val = km[k];
                                    const formatted = (val !== null && val !== undefined) ? `${val >= 0 ? '+' : ''}${val.toFixed(1)}%` : '—';
                                    const cls = (val !== null && val !== undefined && val >= 0) ? 'val-positive' : 'val-negative';
                                    return `<div class="history-metric-card"><span class="hm-label">${yr}:</span><span class="hm-val ${cls}">${formatted}</span></div>`;
                                }).join('')}
                            </div>
                        </div>
                    `;
                }

                historyContent.innerHTML = histHtml;
            }

            // Sync metadata edit panel initial state
            const editSector = document.getElementById('metaEditSector') || document.getElementById('editMetaSector');
            const editGrade = document.getElementById('metaEditGrade') || document.getElementById('editMetaGrade');
            const editNotes = document.getElementById('metaEditNotes') || document.getElementById('editMetaNotes');
            if (editSector) editSector.value = panel.sector || '';
            if (editGrade) editGrade.value = panel.grade || '';
            if (editNotes) editNotes.value = '';

            const editBtn = document.getElementById('editMetaBtn');
            const editPanel = document.getElementById('metaEditPanel');
            if (editBtn && editPanel) {
                editBtn.onclick = async () => {
                    const isHidden = editPanel.style.display === 'none';
                    if (isHidden) {
                        editPanel.style.display = 'block';
                        try {
                            const meta = await API.getMetadata(activeSymbol, panel.exchange || 'NSE');
                            if (meta) {
                                if (editSector) editSector.value = meta.sector || '';
                                if (editGrade) editGrade.value = meta.grade || '';
                                if (editNotes) editNotes.value = meta.notes || '';
                            }
                        } catch (err) {
                            console.warn('Could not fetch extra metadata notes:', err);
                        }
                    } else {
                        editPanel.style.display = 'none';
                    }
                };
            }
        } catch (err) {
            if (activeSymbol === target && currentStockDrawerRequestId === currentId) {
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
    document.getElementById('universeSectorSelect')?.addEventListener('change', onConditionChanged);
    document.getElementById('universeInstrSelect')?.addEventListener('change', onConditionChanged);
    document.getElementById('universeMicrocapToggle')?.addEventListener('change', onConditionChanged);

    // Static guide buttons in initial empty table state
    document.getElementById('guideDemoBtn')?.addEventListener('click', loadDemoData);
    document.getElementById('guideLiveBtn')?.addEventListener('click', rebuildLiveDataset);

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
    // 13B. Batch U3 Power Controls: Metadata, History, Backups, Sprint Race
    // -------------------------------------------------------------------------
    // A. Security Metadata Editing
    document.getElementById('cancelMetaBtn')?.addEventListener('click', () => {
        const editPanel = document.getElementById('metaEditPanel');
        if (editPanel) editPanel.style.display = 'none';
    });

    document.getElementById('saveMetaBtn')?.addEventListener('click', async () => {
        if (!activeSymbol) return;
        const editPanel = document.getElementById('metaEditPanel');
        const saveBtn = document.getElementById('saveMetaBtn');
        const sectorVal = (document.getElementById('metaEditSector') || document.getElementById('editMetaSector'))?.value.trim();
        const gradeVal = (document.getElementById('metaEditGrade') || document.getElementById('editMetaGrade'))?.value.trim();
        const notesVal = (document.getElementById('metaEditNotes') || document.getElementById('editMetaNotes'))?.value.trim();

        try {
            if (saveBtn) saveBtn.disabled = true;
            await API.updateMetadata(activeSymbol, 'sector', sectorVal);
            await API.updateMetadata(activeSymbol, 'grade', gradeVal);
            await API.updateMetadata(activeSymbol, 'notes', notesVal);
            showToast(`Metadata saved for ${activeSymbol}`, 'success');
            if (editPanel) editPanel.style.display = 'none';
            await loadStockPanel(activeSymbol);
        } catch (err) {
            if (err.message && err.message.includes('403')) {
                showToast('Metadata update is disabled in Demo Mode.', 'warning');
            } else {
                showToast(`Metadata save failed: ${err.message}`, 'error');
            }
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    });

    // B. Band Change History Popover
    const bandHistoryModal = document.getElementById('bandHistoryModal');
    const closeBandHistoryBtn = document.getElementById('closeBandHistoryBtn');
    const bandHistoryBtn = document.getElementById('bandHistoryBtn');

    if (bandHistoryBtn) {
        bandHistoryBtn.addEventListener('click', async () => {
            if (!activeSymbol || !bandHistoryModal) return;
            bandHistoryModal.style.display = 'flex';
            const titleEl = document.getElementById('bandHistoryTitle');
            const bodyEl = document.getElementById('bandHistoryBody');
            if (titleEl) titleEl.textContent = `Band Change History — ${activeSymbol}`;
            if (bodyEl) bodyEl.innerHTML = '<div class="empty-state">Loading history...</div>';

            try {
                const data = await API.getBandLog(activeSymbol, 60);
                const changes = data.changes || [];
                if (changes.length === 0) {
                    bodyEl.innerHTML = `<div class="empty-state">No band adjustment history recorded for ${activeSymbol}.</div>`;
                    return;
                }
                bodyEl.innerHTML = `
                    <table class="history-table">
                        <thead>
                            <tr>
                                <th>Timestamp</th>
                                <th>TF</th>
                                <th>Old %</th>
                                <th>New %</th>
                                <th>User / Source</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${changes.map(c => `
                                <tr>
                                    <td>${c.when ? c.when.replace('T', ' ').substring(0, 19) : '—'}</td>
                                    <td><strong>${c.timeframe || '—'}</strong></td>
                                    <td>${c.old_pct !== null && c.old_pct !== undefined ? `${(c.old_pct * 100).toFixed(1)}%` : '—'}</td>
                                    <td><strong>${c.new_pct !== null && c.new_pct !== undefined ? `${(c.new_pct * 100).toFixed(1)}%` : '—'}</strong></td>
                                    <td>${c.changed_by || c.source || 'cockpit'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            } catch (err) {
                bodyEl.innerHTML = `<div class="empty-state" style="color: var(--accent-red-bright);">Failed to load history: ${err.message}</div>`;
            }
        });
    }

    if (closeBandHistoryBtn) {
        closeBandHistoryBtn.addEventListener('click', () => {
            if (bandHistoryModal) bandHistoryModal.style.display = 'none';
        });
    }

    // C. Data & Snapshots Management Console (Batch U3/U4)
    const bandBackupsModal = document.getElementById('bandBackupsModal');
    const closeBandBackupsBtn = document.getElementById('closeBandBackupsBtn') || document.getElementById('bandBackupsCloseBtn');
    const bandBackupsDoneBtn = document.getElementById('bandBackupsDoneBtn');
    const bandBackupsBtn = document.getElementById('bandBackupsBtn');

    const tabSnapshotsBtn = document.getElementById('tabSnapshotsBtn');
    const tabGlobalAuditBtn = document.getElementById('tabGlobalAuditBtn');
    const dataTabSnapshots = document.getElementById('dataTabSnapshots');
    const dataTabAudit = document.getElementById('dataTabAudit');
    const refreshGlobalAuditBtn = document.getElementById('refreshGlobalAuditBtn');

    function switchDataTab(tabName) {
        if (tabName === 'snapshots') {
            tabSnapshotsBtn?.classList.add('active');
            tabGlobalAuditBtn?.classList.remove('active');
            if (dataTabSnapshots) dataTabSnapshots.style.display = 'block';
            if (dataTabAudit) dataTabAudit.style.display = 'none';
        } else {
            tabGlobalAuditBtn?.classList.add('active');
            tabSnapshotsBtn?.classList.remove('active');
            if (dataTabSnapshots) dataTabSnapshots.style.display = 'none';
            if (dataTabAudit) dataTabAudit.style.display = 'block';
            loadGlobalBandLog();
        }
    }

    tabSnapshotsBtn?.addEventListener('click', () => switchDataTab('snapshots'));
    tabGlobalAuditBtn?.addEventListener('click', () => switchDataTab('audit'));
    refreshGlobalAuditBtn?.addEventListener('click', () => loadGlobalBandLog());

    async function loadGlobalBandLog() {
        const container = document.getElementById('globalAuditContainer');
        const loading = document.getElementById('globalAuditLoading');
        if (!container) return;

        if (loading) loading.style.display = 'block';
        container.innerHTML = '';

        try {
            const data = await API.getGlobalBandLog(150);
            if (loading) loading.style.display = 'none';
            const changes = data.changes || [];
            if (changes.length === 0) {
                container.innerHTML = '<div class="empty-state p-3 text-muted">No manual band adjustments recorded in the global audit trail.</div>';
                return;
            }

            container.innerHTML = `
                <table class="global-audit-table">
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Symbol</th>
                            <th>Timeframe</th>
                            <th>Old %</th>
                            <th>New %</th>
                            <th>User</th>
                            <th>Source / Reason</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${changes.map(c => `
                            <tr>
                                <td>${c.when ? c.when.replace('T', ' ').substring(0, 19) : '—'}</td>
                                <td><strong>${c.symbol || '—'}</strong></td>
                                <td><span class="badge badge-neutral">${c.timeframe || '—'}</span></td>
                                <td>${c.old_pct !== null && c.old_pct !== undefined ? c.old_pct : '—'}</td>
                                <td><strong style="color: var(--accent-blue-light);">${c.new_pct !== null && c.new_pct !== undefined ? c.new_pct : '—'}</strong></td>
                                <td>${c.changed_by || 'discretionary'}</td>
                                <td class="text-muted">${c.source || 'discretionary'}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        } catch (err) {
            if (loading) loading.style.display = 'none';
            container.innerHTML = `<div class="empty-state p-3" style="color: var(--accent-red-bright);">Failed to load global audit trail: ${err.message}</div>`;
        }
    }

    async function loadBandBackups() {
        const bodyEl = document.getElementById('bandBackupsListContainer') || document.getElementById('bandBackupsBody');
        const loadingEl = document.getElementById('bandBackupsLoading');
        if (!bodyEl) return;
        if (loadingEl) loadingEl.style.display = 'block';
        bodyEl.innerHTML = '';

        try {
            const data = await API.getBandBackups();
            if (loadingEl) loadingEl.style.display = 'none';
            const backups = data.backups || [];
            if (backups.length === 0) {
                bodyEl.innerHTML = '<div class="empty-state">No dated daily band backups available.</div>';
                return;
            }
            bodyEl.innerHTML = `
                <table class="backups-table">
                    <thead>
                        <tr>
                            <th>Snapshot Date</th>
                            <th>Filename</th>
                            <th>Stocks</th>
                            <th>Size</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${backups.map(b => `
                            <tr>
                                <td><strong>${b.date || '—'}</strong></td>
                                <td><code>${b.file}</code></td>
                                <td>${b.stocks}</td>
                                <td>${b.size_kb ? `${b.size_kb.toFixed(1)} KB` : '—'}</td>
                                <td>
                                    <button class="btn btn-xs btn-outline btn-restore-backup" data-file="${b.file}">Restore</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;

            bodyEl.querySelectorAll('.btn-restore-backup').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const file = e.currentTarget.getAttribute('data-file');
                    const ok = window.confirm(
                        `Are you sure you want to restore snapshot '${file}'?\n\n` +
                        `IMPACT NOTICE:\n` +
                        `• Active band configurations for all symbols will be replaced with this snapshot.\n` +
                        `• An automatic safety backup will be created immediately before restore.\n` +
                        `• Materialized charts and analytical panels will refresh automatically.\n\n` +
                        `Click OK to proceed with restoration.`
                    );
                    if (!ok) return;

                    try {
                        btn.disabled = true;
                        btn.textContent = '...';
                        const res = await API.restoreBandBackup(file);
                        showToast(`Restored snapshot '${file}' successfully (${res.stocks || 'all'} stocks)!`, 'success');
                        await loadBandBackups();
                        if (activeSymbol) {
                            await loadChartData(activeSymbol);
                            await loadStockPanel(activeSymbol);
                        }
                    } catch (err) {
                        if (err.message && err.message.includes('403')) {
                            showToast('Band restore operation is disabled in Demo Mode (HTTP 403).', 'warning');
                        } else {
                            showToast(`Restore failed: ${err.message}`, 'error');
                        }
                        btn.disabled = false;
                        btn.textContent = 'Restore';
                    }
                });
            });
        } catch (err) {
            if (loadingEl) loadingEl.style.display = 'none';
            bodyEl.innerHTML = `<div class="empty-state" style="color: var(--accent-red-bright);">Failed to load backups: ${err.message}</div>`;
        }
    }

    if (bandBackupsBtn) {
        bandBackupsBtn.addEventListener('click', () => {
            if (bandBackupsModal) bandBackupsModal.style.display = 'flex';
            switchDataTab('snapshots');
            loadBandBackups();
        });
    }

    if (closeBandBackupsBtn) {
        closeBandBackupsBtn.addEventListener('click', () => {
            if (bandBackupsModal) bandBackupsModal.style.display = 'none';
        });
    }

    if (bandBackupsDoneBtn) {
        bandBackupsDoneBtn.addEventListener('click', () => {
            if (bandBackupsModal) bandBackupsModal.style.display = 'none';
        });
    }

    // D. Sprint Race Visualizer & Leaderboard
    const raceModal = document.getElementById('raceModal');
    const closeRaceBtn = document.getElementById('closeRaceBtn');
    const openRaceBtn = document.getElementById('openRaceBtn');
    const runRaceBtn = document.getElementById('runRaceBtn');
    let currentRaceLines = [];

    function renderRaceChart(lines) {
        const canvas = document.getElementById('raceChartCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const container = canvas.parentElement;
        const dpr = window.devicePixelRatio || 1;
        const width = container.clientWidth || 800;
        const height = 400;

        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        ctx.scale(dpr, dpr);

        ctx.clearRect(0, 0, width, height);

        if (!lines || lines.length === 0) {
            ctx.fillStyle = '#8b949e';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No trajectory data returned for selected criteria', width / 2, height / 2);
            return;
        }

        const colors = [
            '#238636', '#58a6ff', '#f0883e', '#d29922', '#a371f7',
            '#3fb950', '#79c0ff', '#ff7b72', '#ec6547', '#e3b341',
            '#bc8cff', '#56d364', '#2f81f7', '#da3633', '#1f6feb'
        ];

        let minVal = 0;
        let maxVal = 10;
        const allTimes = new Set();

        lines.forEach(line => {
            (line.points || []).forEach(pt => {
                allTimes.add(pt.time);
                if (pt.value < minVal) minVal = pt.value;
                if (pt.value > maxVal) maxVal = pt.value;
            });
        });

        const padTop = 30;
        const padBottom = 40;
        const padLeft = 60;
        const padRight = 120;
        const chartW = width - padLeft - padRight;
        const chartH = height - padTop - padBottom;

        const valRange = (maxVal - minVal) || 1;
        const yZero = padTop + chartH * (maxVal / valRange);

        // Draw grid lines & Y-axis labels
        ctx.strokeStyle = '#30363d';
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px monospace';
        ctx.textAlign = 'right';
        ctx.lineWidth = 1;

        const ySteps = 5;
        for (let i = 0; i <= ySteps; i++) {
            const v = minVal + (valRange * (i / ySteps));
            const y = padTop + chartH - (chartH * (i / ySteps));
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(padLeft + chartW, y);
            ctx.stroke();
            ctx.fillText(`${v >= 0 ? '+' : ''}${v.toFixed(0)}%`, padLeft - 8, y + 4);
        }

        // Highlight zero baseline if within range
        if (minVal <= 0 && maxVal >= 0) {
            ctx.strokeStyle = '#6e7681';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(padLeft, yZero);
            ctx.lineTo(padLeft + chartW, yZero);
            ctx.stroke();
        }

        const sortedTimes = Array.from(allTimes).sort();
        const timeIndexMap = new Map();
        sortedTimes.forEach((t, idx) => timeIndexMap.set(t, idx));
        const numTimes = sortedTimes.length;

        // Draw trajectories
        lines.forEach((line, lineIdx) => {
            const color = colors[lineIdx % colors.length];
            const pts = (line.points || []).filter(p => timeIndexMap.has(p.time)).sort((a, b) => a.time.localeCompare(b.time));
            if (pts.length < 2) return;

            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();

            pts.forEach((pt, idx) => {
                const tIdx = timeIndexMap.get(pt.time);
                const x = padLeft + (chartW * (tIdx / Math.max(1, numTimes - 1)));
                const y = padTop + chartH - (chartH * ((pt.value - minVal) / valRange));
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // Label at endpoint
            const lastPt = pts[pts.length - 1];
            const lastTIdx = timeIndexMap.get(lastPt.time);
            const endX = padLeft + (chartW * (lastTIdx / Math.max(1, numTimes - 1)));
            const endY = padTop + chartH - (chartH * ((lastPt.value - minVal) / valRange));

            ctx.fillStyle = color;
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(` ${line.symbol} (${lastPt.value >= 0 ? '+' : ''}${lastPt.value.toFixed(1)}%)`, endX + 4, endY + 4);
        });

        // X-axis date labels
        if (numTimes > 0) {
            ctx.fillStyle = '#8b949e';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            const xStep = Math.max(1, Math.floor(numTimes / 6));
            for (let i = 0; i < numTimes; i += xStep) {
                const t = sortedTimes[i];
                const x = padLeft + (chartW * (i / Math.max(1, numTimes - 1)));
                ctx.fillText(t.substring(0, 7), x, height - 12);
            }
            const lastX = padLeft + chartW;
            ctx.fillText(sortedTimes[numTimes - 1].substring(0, 7), lastX, height - 12);
        }
    }

    async function executeRace() {
        const anchor = document.getElementById('raceAnchorSelect')?.value || '2021-01-01';
        const top = parseInt(document.getElementById('raceTopInput')?.value, 10) || 15;
        const symbolsInput = (document.getElementById('raceSymbolsInput')?.value || '').trim();
        const runBtn = document.getElementById('runRaceBtn');
        const boardEl = document.getElementById('raceLeaderboardContainer');

        let metric = 'SPA_A21';
        if (anchor.includes('2022')) metric = 'SPA_A22';
        else if (anchor.includes('2023')) metric = 'SPA_A23';
        else if (anchor.includes('2024')) metric = 'SPA_A24';
        else if (anchor.includes('2025')) metric = 'SPA_A25';
        else if (anchor.includes('2026')) metric = 'SPA_A26';

        try {
            if (runBtn) {
                runBtn.disabled = true;
                runBtn.textContent = 'Running...';
            }
            if (boardEl) boardEl.innerHTML = '<div class="empty-state">Computing trajectory curves...</div>';

            const res = await API.getRace({
                symbols: symbolsInput || undefined,
                anchor: anchor,
                top: top,
                metric: metric,
            });

            currentRaceLines = res.lines || [];
            renderRaceChart(currentRaceLines);

            // Render Leaderboard Table
            if (boardEl) {
                if (currentRaceLines.length === 0) {
                    boardEl.innerHTML = '<div class="empty-state">No leaderboard entries found for specified criteria.</div>';
                } else {
                    boardEl.innerHTML = `
                        <table class="race-table">
                            <thead>
                                <tr>
                                    <th>Rank</th>
                                    <th>Symbol</th>
                                    <th>Trajectory Cumulative Gain</th>
                                    <th>Data Points</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${currentRaceLines.map((l, idx) => `
                                    <tr>
                                        <td><strong>#${idx + 1}</strong></td>
                                        <td><strong>${l.symbol}</strong></td>
                                        <td class="${l.final >= 0 ? 'val-positive' : 'val-negative'}">
                                            <strong>${l.final >= 0 ? '+' : ''}${l.final.toFixed(1)}%</strong>
                                        </td>
                                        <td>${(l.points || []).length} wks</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    `;
                }
            }
        } catch (err) {
            showToast(`Race failed: ${err.message}`, 'error');
            if (boardEl) boardEl.innerHTML = `<div class="empty-state" style="color: var(--accent-red-bright);">Race error: ${err.message}</div>`;
        } finally {
            if (runBtn) {
                runBtn.disabled = false;
                runBtn.textContent = '🏁 Run Race';
            }
        }
    }

    if (openRaceBtn) {
        openRaceBtn.addEventListener('click', () => {
            if (raceModal) raceModal.style.display = 'flex';
            // Prepopulate symbols input if table has filtered symbols and symbols input is empty
            const symInput = document.getElementById('raceSymbolsInput');
            if (symInput && !symInput.value && table && table.displayRows) {
                const rows = table.displayRows;
                if (rows && rows.length > 0 && rows.length <= 15) {
                    symInput.value = rows.map(r => r.symbol).join(', ');
                }
            }
            executeRace();
        });
    }

    if (closeRaceBtn) {
        closeRaceBtn.addEventListener('click', () => {
            if (raceModal) raceModal.style.display = 'none';
        });
    }

    if (runRaceBtn) {
        runRaceBtn.addEventListener('click', executeRace);
    }

    // Modal Backdrop Dismissal for all new modals
    [bandHistoryModal, bandBackupsModal, raceModal].forEach(m => {
        if (m) {
            m.addEventListener('click', (e) => {
                if (e.target === m) {
                    m.style.display = 'none';
                }
            });
        }
    });

    // -------------------------------------------------------------------------
    // 13. Half-Year (H) Policy Radio Setting Handler
    // -------------------------------------------------------------------------
    async function initHalfYearPolicy() {
        try {
            const settings = await API.getSettings();
            const policy = settings.half_year_policy || 'prototype';
            const radio = document.querySelector(`input[name="halfYearPolicyRadio"][value="${policy}"]`);
            if (radio) radio.checked = true;
        } catch (err) {
            console.warn('Could not load system settings:', err);
        }
    }

    document.querySelectorAll('input[name="halfYearPolicyRadio"]').forEach(radio => {
        radio.addEventListener('change', async (e) => {
            const selectedPolicy = e.target.value;
            const policyLabel = selectedPolicy === 'calendar' ? 'Calendar Half-Year (H1/H2)' : 'Prototype-Compatible (2QE)';
            try {
                showToast(`Applying ${policyLabel}...`, 'info');
                await API.updateSettings({ half_year_policy: selectedPolicy });
                showToast(`Half-year policy set to ${policyLabel}`, 'success');

                // Re-run active screen so table and metrics reflect the new policy
                await runScreen();

                // If stock drawer is open, refresh panel data and charts
                if (activeSymbol) {
                    await openStockDrawer(activeSymbol);
                }
            } catch (err) {
                showToast(`Failed to update half-year policy: ${err.message}`, 'error');
            }
        });
    });

    // -------------------------------------------------------------------------
    // 14. Initialization Boot Sequence
    // -------------------------------------------------------------------------
    populateRankingSelects();
    await loadPresetsList();
    await initHalfYearPolicy();
    const initialStatus = await updateStatus();

    // If dataset has rows, run default screen immediately (unconstrained fast startup)
    if (initialStatus && initialStatus.universe_count > 0) {
        await runScreen({ unconstrained: true });
    } else if (initialStatus && initialStatus.status === 'BUILDING') {
        _startBuildPolling();
    } else {
        // Real dataset is empty and not building: display clear empty/guidance state
        // Never automatically switch the backend to demo mode
        table.emptyMessage = 'Market dataset is empty. Click "Rebuild Live Dataset" to fetch live data or "Demo (5 Stocks)" to load sample data.';
        table.render({
            columns: [
                { key: 'symbol', label: 'Symbol' },
                { key: 'name', label: 'Security Name' },
                { key: 'price', label: 'Price' }
            ],
            rows: []
        });
        if (initialStatus && initialStatus.status === 'FAILED') {
            showToast(`Market dataset rebuild failed: ${initialStatus.error || 'Unknown error'}. Click "Demo (5 Stocks)" or "Rebuild Live Dataset".`, 'error');
        } else {
            showToast('Market dataset is empty. Click "Rebuild Live Dataset" or "Demo (5 Stocks)" to load data.', 'info');
        }
    }

});
