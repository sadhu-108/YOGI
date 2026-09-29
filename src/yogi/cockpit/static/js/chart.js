/**
 * Cockpit Chart Controller — TradingView Lightweight Charts & Fallback Renderer.
 * Supports Price Chart Overlays (EMA, Bands, Bollinger, Donchian, ATR, VWAP, Volume)
 * and Synchronized Analytical Sub-Panels (RSI, MACD, DMI, OBV, MFI, YOGI Momentum Curves).
 */

function _prepareCurvePoints(curve) {
    if (!curve || !Array.isArray(curve)) return [];
    const valid = [];
    const seenTimes = new Set();
    const sorted = [...curve].sort((a, b) => (a.time || '').localeCompare(b.time || ''));
    for (const pt of sorted) {
        if (pt && pt.time && typeof pt.value === 'number' && !isNaN(pt.value) && isFinite(pt.value)) {
            if (!seenTimes.has(pt.time)) {
                seenTimes.add(pt.time);
                valid.push({ time: pt.time, value: pt.value });
            }
        }
    }
    return valid;
}

class CockpitChart {
    constructor(containerId = 'chartContainer', subContainerId = 'subChartCanvas') {
        this.container = document.getElementById(containerId);
        this.subContainer = document.getElementById(subContainerId);
        this.subChartWrapper = document.getElementById('subChartContainer');

        this.chart = null;
        this.subChart = null;
        this.currentData = null;

        // Overlay state (default visible: EMA 3, EMA 5, YOGI Bands, Volume)
        this.overlays = {
            ema3: true,
            ema5: true,
            sma20: false,
            avg_price: false,
            bands: true,
            bollinger: false,
            donchian: false,
            atr_bands: false,
            vwap: false,
            volume: true,
        };

        // Active analytical panel ('none' by default)
        this.activePanel = 'none';

        // Main chart series
        this.candleSeries = null;
        this.upperBandSeries = null;
        this.lowerBandSeries = null;
        this.ema3Series = null;
        this.ema5Series = null;
        this.sma20Series = null;
        this.bollingerUpper = null;
        this.bollingerLower = null;
        this.bollingerBasis = null;
        this.donchianUpper = null;
        this.donchianLower = null;
        this.donchianMiddle = null;
        this.atrUpper = null;
        this.atrLower = null;
        this.vwapSeries = null;
        this.volumeSeries = null;
        this.avgPriceLine = null;

        // Sub chart series references
        this.subSeriesList = [];
        this.subPriceLines = [];

        // Point-to-Point Measurement Tool (Batch U4)
        this.isMeasuring = false;
        this.measureP1 = null; // { price: number, time: string }
        this.measureP2 = null; // { price: number, time: string }
        this.measureP1Line = null;
        this.measureP2Line = null;
        this.onMeasureChange = null; // callback (state) => void

        this.init();
    }

    init() {
        if (!this.container) return;
        this.container.innerHTML = '';

        if (window.LightweightCharts) {
            // 1. Initialize Main Price Chart
            this.chart = window.LightweightCharts.createChart(this.container, {
                width: this.container.clientWidth || 600,
                height: this.container.clientHeight || 260,
                layout: {
                    background: { color: '#131722' },
                    textColor: '#d1d4dc',
                },
                grid: {
                    vertLines: { color: '#1e222d' },
                    horzLines: { color: '#1e222d' },
                },
                crosshair: {
                    mode: window.LightweightCharts.CrosshairMode.Normal,
                },
                rightPriceScale: {
                    borderColor: '#2b2b43',
                },
                timeScale: {
                    borderColor: '#2b2b43',
                    timeVisible: false,
                    secondsVisible: false,
                },
            });

            // Point-to-Point Measurement Click Subscription
            this.chart.subscribeClick((param) => {
                if (!this.isMeasuring) return;
                if (!param || !param.point) return;

                let price = null;
                if (this.candleSeries && typeof this.candleSeries.coordinateToPrice === 'function') {
                    price = this.candleSeries.coordinateToPrice(param.point.y);
                }
                if (price === null && param.seriesData && this.candleSeries && typeof param.seriesData.get === 'function') {
                    const candle = param.seriesData.get(this.candleSeries);
                    if (candle && typeof candle.close === 'number') price = candle.close;
                }
                if (price === null && this.currentData && this.currentData.candles && param.time) {
                    const c = this.currentData.candles.find(bar => bar.time === param.time);
                    if (c && typeof c.close === 'number') price = c.close;
                }

                if (price !== null && !isNaN(price)) {
                    this.recordMeasurePoint(price, param.time);
                }
            });

            // Candlesticks (Primary series)
            this.candleSeries = this.chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderVisible: false,
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350',
            });

            // Volume histogram overlay (placed at chart bottom)
            this.volumeSeries = this.chart.addHistogramSeries({
                color: '#26a69a',
                priceFormat: { type: 'volume' },
                priceScaleId: '', // overlay
            });
            this.volumeSeries.priceScale().applyOptions({
                scaleMargins: {
                    top: 0.8,
                    bottom: 0,
                },
            });

            // YOGI Bands (Upper / Lower dashed)
            this.upperBandSeries = this.chart.addLineSeries({
                color: '#58a6ff',
                lineWidth: 1.5,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'Upper Band',
            });
            this.lowerBandSeries = this.chart.addLineSeries({
                color: '#f85149',
                lineWidth: 1.5,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'Lower Band',
            });

            // Trend Overlays: EMA 3, EMA 5, SMA 20 (Basis)
            this.ema3Series = this.chart.addLineSeries({
                color: '#e3b341',
                lineWidth: 1.2,
                title: 'EMA 3',
            });
            this.ema5Series = this.chart.addLineSeries({
                color: '#f0883e',
                lineWidth: 1.2,
                title: 'EMA 5',
            });
            this.sma20Series = this.chart.addLineSeries({
                color: '#8b949e',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dotted,
                title: 'SMA 20',
            });

            // Channels & Volatility Overlays: Bollinger, Donchian, ATR Bands, VWAP
            this.bollingerUpper = this.chart.addLineSeries({
                color: '#39c5bb',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'BB Upper',
            });
            this.bollingerLower = this.chart.addLineSeries({
                color: '#39c5bb',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'BB Lower',
            });
            this.bollingerBasis = this.chart.addLineSeries({
                color: '#39c5bb',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dotted,
                title: 'BB Mid',
            });

            this.donchianUpper = this.chart.addLineSeries({
                color: '#a371f7',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'DC Upper',
            });
            this.donchianLower = this.chart.addLineSeries({
                color: '#a371f7',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'DC Lower',
            });
            this.donchianMiddle = this.chart.addLineSeries({
                color: '#a371f7',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dotted,
                title: 'DC Mid',
            });

            this.atrUpper = this.chart.addLineSeries({
                color: '#d29922',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'ATR Upper',
            });
            this.atrLower = this.chart.addLineSeries({
                color: '#d29922',
                lineWidth: 1,
                lineStyle: window.LightweightCharts.LineStyle.Dashed,
                title: 'ATR Lower',
            });

            this.vwapSeries = this.chart.addLineSeries({
                color: '#2ea043',
                lineWidth: 1.5,
                title: 'VWAP',
            });

            // 2. Initialize Analytical Sub-Panel Chart
            if (this.subContainer) {
                this.subChart = window.LightweightCharts.createChart(this.subContainer, {
                    width: this.subContainer.clientWidth || (this.container.clientWidth || 600),
                    height: this.subContainer.clientHeight || 130,
                    layout: {
                        background: { color: '#131722' },
                        textColor: '#d1d4dc',
                    },
                    grid: {
                        vertLines: { color: '#1e222d' },
                        horzLines: { color: '#1e222d' },
                    },
                    crosshair: {
                        mode: window.LightweightCharts.CrosshairMode.Normal,
                    },
                    rightPriceScale: {
                        borderColor: '#2b2b43',
                    },
                    timeScale: {
                        borderColor: '#2b2b43',
                        timeVisible: false,
                        secondsVisible: false,
                    },
                });

                // Synchronize time scales between main price chart and analytical sub-panel
                let isSyncingMain = false;
                let isSyncingSub = false;

                this.chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                    if (isSyncingSub || !this.subChart) return;
                    isSyncingMain = true;
                    try {
                        this.subChart.timeScale().setVisibleLogicalRange(range);
                    } catch (_) {}
                    isSyncingMain = false;
                });

                this.subChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                    if (isSyncingMain || !this.chart) return;
                    isSyncingSub = true;
                    try {
                        this.chart.timeScale().setVisibleLogicalRange(range);
                    } catch (_) {}
                    isSyncingSub = false;
                });
            }

            window.addEventListener('resize', () => {
                this.resize();
            });
        } else {
            console.warn('LightweightCharts not loaded; running with fallback canvas.');
        }
    }

    clear() {
        this.currentData = null;
        if (this.chart) {
            if (this.candleSeries) this.candleSeries.setData([]);
            if (this.upperBandSeries) this.upperBandSeries.setData([]);
            if (this.lowerBandSeries) this.lowerBandSeries.setData([]);
            if (this.ema3Series) this.ema3Series.setData([]);
            if (this.ema5Series) this.ema5Series.setData([]);
            if (this.sma20Series) this.sma20Series.setData([]);
            if (this.bollingerUpper) this.bollingerUpper.setData([]);
            if (this.bollingerLower) this.bollingerLower.setData([]);
            if (this.bollingerBasis) this.bollingerBasis.setData([]);
            if (this.donchianUpper) this.donchianUpper.setData([]);
            if (this.donchianLower) this.donchianLower.setData([]);
            if (this.donchianMiddle) this.donchianMiddle.setData([]);
            if (this.atrUpper) this.atrUpper.setData([]);
            if (this.atrLower) this.atrLower.setData([]);
            if (this.vwapSeries) this.vwapSeries.setData([]);
            if (this.volumeSeries) this.volumeSeries.setData([]);

            if (this.avgPriceLine && this.candleSeries) {
                try { this.candleSeries.removePriceLine(this.avgPriceLine); } catch (_) {}
                this.avgPriceLine = null;
            }
        }

        this._clearSubChart();
        this._clearMeasureLines();
        if (this.isMeasuring) {
            this.measureP1 = null;
            this.measureP2 = null;
        }

        if (this.container) {
            const canvas = this.container.querySelector('canvas');
            if (canvas) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        }
    }

    // -------------------------------------------------------------------------
    // Point-to-Point Measurement Tool Methods (Batch U4)
    // -------------------------------------------------------------------------
    toggleMeasure(forceState) {
        this.isMeasuring = typeof forceState === 'boolean' ? forceState : !this.isMeasuring;
        if (!this.isMeasuring) {
            this.cancelMeasure();
        } else {
            this.resetMeasure();
            if (this.onMeasureChange) {
                this.onMeasureChange({ active: true, step: 1, p1: null, p2: null, deltaPct: null, deltaAbs: null });
            }
        }
        return this.isMeasuring;
    }

    recordMeasurePoint(price, time = null) {
        if (!this.isMeasuring) return;
        const p = typeof price === 'number' ? price : parseFloat(price);
        if (isNaN(p)) return;

        if (!this.measureP1 || (this.measureP1 && this.measureP2)) {
            // Step 1: First point (or reset if both already existed)
            this._clearMeasureLines();
            this.measureP1 = { price: p, time: time || '' };
            this.measureP2 = null;

            if (this.candleSeries && typeof this.candleSeries.createPriceLine === 'function') {
                try {
                    this.measureP1Line = this.candleSeries.createPriceLine({
                        price: p,
                        color: '#58a6ff',
                        lineWidth: 1.5,
                        lineStyle: window.LightweightCharts ? window.LightweightCharts.LineStyle.Dashed : 2,
                        axisLabelVisible: true,
                        title: `P1: ₹${p.toFixed(2)}`,
                    });
                } catch (_) {}
            }

            if (this.onMeasureChange) {
                this.onMeasureChange({
                    active: true,
                    step: 2,
                    p1: this.measureP1,
                    p2: null,
                    deltaPct: null,
                    deltaAbs: null,
                });
            }
        } else if (this.measureP1 && !this.measureP2) {
            // Step 2: Second point -> complete measurement
            this.measureP2 = { price: p, time: time || '' };
            const p1 = this.measureP1.price;
            const p2 = this.measureP2.price;
            const deltaAbs = p2 - p1;
            const deltaPct = p1 !== 0 ? (deltaAbs / Math.abs(p1)) * 100.0 : 0.0;
            const color = deltaPct >= 0 ? '#26a69a' : '#ef5350';

            if (this.candleSeries && typeof this.candleSeries.createPriceLine === 'function') {
                try {
                    this.measureP2Line = this.candleSeries.createPriceLine({
                        price: p2,
                        color: color,
                        lineWidth: 1.5,
                        lineStyle: window.LightweightCharts ? window.LightweightCharts.LineStyle.Solid : 0,
                        axisLabelVisible: true,
                        title: `P2: ₹${p2.toFixed(2)} (${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(2)}%)`,
                    });
                } catch (_) {}
            }

            if (this.onMeasureChange) {
                this.onMeasureChange({
                    active: true,
                    step: 3,
                    p1: this.measureP1,
                    p2: this.measureP2,
                    deltaPct: deltaPct,
                    deltaAbs: deltaAbs,
                });
            }
        }
    }

    resetMeasure() {
        this._clearMeasureLines();
        this.measureP1 = null;
        this.measureP2 = null;
        if (this.onMeasureChange && this.isMeasuring) {
            this.onMeasureChange({
                active: true,
                step: 1,
                p1: null,
                p2: null,
                deltaPct: null,
                deltaAbs: null,
            });
        }
    }

    cancelMeasure() {
        this.isMeasuring = false;
        this._clearMeasureLines();
        this.measureP1 = null;
        this.measureP2 = null;
        if (this.onMeasureChange) {
            this.onMeasureChange({
                active: false,
                step: 0,
                p1: null,
                p2: null,
                deltaPct: null,
                deltaAbs: null,
            });
        }
    }

    _clearMeasureLines() {
        if (this.candleSeries && typeof this.candleSeries.removePriceLine === 'function') {
            if (this.measureP1Line) {
                try { this.candleSeries.removePriceLine(this.measureP1Line); } catch (_) {}
                this.measureP1Line = null;
            }
            if (this.measureP2Line) {
                try { this.candleSeries.removePriceLine(this.measureP2Line); } catch (_) {}
                this.measureP2Line = null;
            }
        }
    }

    _clearSubChart() {
        if (this.subChart) {
            for (const s of this.subSeriesList) {
                try { this.subChart.removeSeries(s); } catch (_) {}
            }
            this.subSeriesList = [];
            this.subPriceLines = [];
        }
        if (this.subContainer) {
            const canvas = this.subContainer.querySelector('canvas');
            if (canvas) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        }
    }

    resize() {
        const w = (this.container && this.container.clientWidth) ? this.container.clientWidth : 600;
        const h = (this.container && this.container.clientHeight) ? this.container.clientHeight : 260;

        if (this.chart && w > 0) {
            this.chart.applyOptions({ width: w, height: h });
            try { this.chart.timeScale().fitContent(); } catch (_) {}
        }

        if (this.subChart && w > 0 && this.subContainer) {
            const subH = this.subContainer.clientHeight || 130;
            this.subChart.applyOptions({ width: w, height: subH });
            try { this.subChart.timeScale().fitContent(); } catch (_) {}
        }
    }

    setOverlay(key, isEnabled) {
        this.overlays[key] = !!isEnabled;
        if (this.currentData) {
            this.applyOverlays();
        }
    }

    setActivePanel(panelKey) {
        this.activePanel = panelKey || 'none';
        if (this.currentData) {
            this.renderSubPanel();
        } else {
            if (this.activePanel === 'none' && this.subChartWrapper) {
                this.subChartWrapper.style.display = 'none';
            } else if (this.subChartWrapper) {
                this.subChartWrapper.style.display = 'flex';
            }
        }
    }

    render(seriesData) {
        if (!seriesData || !seriesData.candles) return;
        this.currentData = seriesData;

        if (this.chart) {
            // Sort candles chronologically
            const candles = [...seriesData.candles].sort((a, b) => (a.time || '').localeCompare(b.time || ''));
            this.candleSeries.setData(candles);

            this.applyOverlays();
            this.renderSubPanel();

            try {
                this.chart.timeScale().fitContent();
            } catch (_) {}
        } else {
            this._renderFallback(seriesData);
        }
    }

    applyOverlays() {
        if (!this.chart || !this.currentData) return;
        const d = this.currentData;

        // 1. YOGI Bands
        if (this.overlays.bands) {
            this.upperBandSeries.setData(_prepareCurvePoints(d.band_upper_curve));
            this.lowerBandSeries.setData(_prepareCurvePoints(d.band_lower_curve));
        } else {
            this.upperBandSeries.setData([]);
            this.lowerBandSeries.setData([]);
        }

        // 2. EMA 3 & EMA 5
        this.ema3Series.setData(this.overlays.ema3 ? _prepareCurvePoints(d.ema3_curve) : []);
        this.ema5Series.setData(this.overlays.ema5 ? _prepareCurvePoints(d.ema5_curve) : []);

        // 3. SMA 20 (Basis)
        this.sma20Series.setData(this.overlays.sma20 ? _prepareCurvePoints(d.basis_curve) : []);

        // 4. Bollinger Bands (20, 2)
        if (this.overlays.bollinger && d.bollinger) {
            this.bollingerUpper.setData(_prepareCurvePoints(d.bollinger.upper));
            this.bollingerLower.setData(_prepareCurvePoints(d.bollinger.lower));
            this.bollingerBasis.setData(_prepareCurvePoints(d.bollinger.basis));
        } else {
            this.bollingerUpper.setData([]);
            this.bollingerLower.setData([]);
            this.bollingerBasis.setData([]);
        }

        // 5. Donchian Channels (20)
        if (this.overlays.donchian && d.donchian) {
            this.donchianUpper.setData(_prepareCurvePoints(d.donchian.upper));
            this.donchianLower.setData(_prepareCurvePoints(d.donchian.lower));
            this.donchianMiddle.setData(_prepareCurvePoints(d.donchian.middle));
        } else {
            this.donchianUpper.setData([]);
            this.donchianLower.setData([]);
            this.donchianMiddle.setData([]);
        }

        // 6. ATR Volatility Bands (14, 2)
        if (this.overlays.atr_bands && d.atr_bands) {
            this.atrUpper.setData(_prepareCurvePoints(d.atr_bands.upper));
            this.atrLower.setData(_prepareCurvePoints(d.atr_bands.lower));
        } else {
            this.atrUpper.setData([]);
            this.atrLower.setData([]);
        }

        // 7. Cumulative VWAP
        this.vwapSeries.setData(this.overlays.vwap ? _prepareCurvePoints(d.vwap_curve) : []);

        // 8. Average Price line
        if (this.avgPriceLine) {
            try { this.candleSeries.removePriceLine(this.avgPriceLine); } catch (_) {}
            this.avgPriceLine = null;
        }
        if (this.overlays.avg_price && d.avg_price !== null && d.avg_price !== undefined) {
            try {
                this.avgPriceLine = this.candleSeries.createPriceLine({
                    price: d.avg_price,
                    color: '#e3b341',
                    lineWidth: 1.5,
                    lineStyle: window.LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `Avg ₹${d.avg_price}`,
                });
            } catch (_) {}
        }

        // 9. Volume Histogram
        if (this.overlays.volume && d.candles && d.candles.length > 0) {
            const volPts = [];
            const seenTimes = new Set();
            const sortedCandles = [...d.candles].sort((a, b) => (a.time || '').localeCompare(b.time || ''));
            for (const c of sortedCandles) {
                if (c && c.time && typeof c.volume === 'number' && !isNaN(c.volume) && !seenTimes.has(c.time)) {
                    seenTimes.add(c.time);
                    volPts.push({
                        time: c.time,
                        value: c.volume,
                        color: (c.close >= c.open) ? 'rgba(38, 166, 154, 0.45)' : 'rgba(239, 83, 80, 0.45)',
                    });
                }
            }
            this.volumeSeries.setData(volPts);
        } else {
            this.volumeSeries.setData([]);
        }
    }

    renderSubPanel() {
        const subWrapper = this.subChartWrapper || document.getElementById('subChartContainer');
        const subTitleEl = document.getElementById('subChartTitle');
        const subLegendEl = document.getElementById('subChartLegend');

        if (this.activePanel === 'none') {
            if (subWrapper) subWrapper.style.display = 'none';
            this._clearSubChart();
            this.resize();
            return;
        }

        if (subWrapper) subWrapper.style.display = 'flex';
        this._clearSubChart();
        if (!this.subChart || !this.currentData) return;

        const d = this.currentData;
        let titleText = 'Analytical Panel';
        let legendText = '';

        switch (this.activePanel) {
            case 'rsi': {
                titleText = 'RSI (14)';
                const rsiPts = _prepareCurvePoints(d.rsi ? d.rsi.points : d.rsi_curve);
                const lastVal = d.rsi && d.rsi.last_rsi !== null ? d.rsi.last_rsi : (rsiPts.length ? rsiPts[rsiPts.length - 1].value : null);
                legendText = lastVal !== null ? `RSI: ${lastVal.toFixed(2)}` : '';

                const rsiSeries = this.subChart.addLineSeries({
                    color: '#a371f7',
                    lineWidth: 1.5,
                    title: 'RSI',
                });
                rsiSeries.setData(rsiPts);
                this.subSeriesList.push(rsiSeries);

                // 70 overbought (red), 30 oversold (green), 50 centerline (grey)
                try {
                    rsiSeries.createPriceLine({ price: 70, color: 'rgba(239, 83, 80, 0.7)', lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'OB 70' });
                    rsiSeries.createPriceLine({ price: 30, color: 'rgba(38, 166, 154, 0.7)', lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'OS 30' });
                    rsiSeries.createPriceLine({ price: 50, color: 'rgba(139, 148, 158, 0.4)', lineStyle: window.LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
                } catch (_) {}
                break;
            }

            case 'macd': {
                titleText = 'MACD (12, 26, 9)';
                const macdData = d.macd || {};
                const mPts = _prepareCurvePoints(macdData.macd);
                const sPts = _prepareCurvePoints(macdData.signal);
                const hPts = _prepareCurvePoints(macdData.histogram);

                const lastM = macdData.last_macd !== null ? macdData.last_macd : (mPts.length ? mPts[mPts.length - 1].value : null);
                const lastS = macdData.last_signal !== null ? macdData.last_signal : (sPts.length ? sPts[sPts.length - 1].value : null);
                legendText = (lastM !== null && lastS !== null) ? `MACD: ${lastM.toFixed(2)} · Signal: ${lastS.toFixed(2)}` : '';

                // Histogram series
                const histSeries = this.subChart.addHistogramSeries({
                    color: '#26a69a',
                    title: 'Histogram',
                });
                const coloredHist = hPts.map(pt => ({
                    time: pt.time,
                    value: pt.value,
                    color: pt.value >= 0 ? '#26a69a' : '#ef5350',
                }));
                histSeries.setData(coloredHist);
                this.subSeriesList.push(histSeries);

                // MACD & Signal line series
                const macdSeries = this.subChart.addLineSeries({ color: '#58a6ff', lineWidth: 1.5, title: 'MACD' });
                macdSeries.setData(mPts);
                this.subSeriesList.push(macdSeries);

                const sigSeries = this.subChart.addLineSeries({ color: '#f0883e', lineWidth: 1.5, title: 'Signal' });
                sigSeries.setData(sPts);
                this.subSeriesList.push(sigSeries);

                try {
                    macdSeries.createPriceLine({ price: 0, color: 'rgba(139, 148, 158, 0.5)', lineStyle: window.LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
                } catch (_) {}
                break;
            }

            case 'dmi': {
                titleText = "Wilder's DMI / ADX";
                const dmiData = d.dmi_series || {};
                const plusPts = _prepareCurvePoints(dmiData.plus);
                const minusPts = _prepareCurvePoints(dmiData.minus);
                const adxPts = _prepareCurvePoints(dmiData.adx);

                const summ = d.dmi_summary || {};
                if (summ.adx !== null && summ.adx !== undefined) {
                    legendText = `ADX: ${summ.adx.toFixed(1)} · +DI: ${(summ.plus_di || 0).toFixed(1)} · -DI: ${(summ.minus_di || 0).toFixed(1)} (${(summ.state || '').toUpperCase()})`;
                }

                const plusSeries = this.subChart.addLineSeries({ color: '#26a69a', lineWidth: 1.5, title: '+DI' });
                plusSeries.setData(plusPts);
                this.subSeriesList.push(plusSeries);

                const minusSeries = this.subChart.addLineSeries({ color: '#ef5350', lineWidth: 1.5, title: '-DI' });
                minusSeries.setData(minusPts);
                this.subSeriesList.push(minusSeries);

                const adxSeries = this.subChart.addLineSeries({ color: '#e3b341', lineWidth: 1.5, title: 'ADX' });
                adxSeries.setData(adxPts);
                this.subSeriesList.push(adxSeries);

                try {
                    adxSeries.createPriceLine({ price: 25, color: 'rgba(227, 179, 65, 0.6)', lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'Trend 25' });
                } catch (_) {}
                break;
            }

            case 'obv': {
                titleText = 'On-Balance Volume (OBV)';
                const obvPts = _prepareCurvePoints(d.obv ? d.obv.points : d.obv_curve);
                const lastVal = d.obv && d.obv.last_obv !== null ? d.obv.last_obv : (obvPts.length ? obvPts[obvPts.length - 1].value : null);
                legendText = lastVal !== null ? `OBV: ${(lastVal / 1e6).toFixed(2)}M` : '';

                const obvSeries = this.subChart.addLineSeries({ color: '#58a6ff', lineWidth: 1.5, title: 'OBV' });
                obvSeries.setData(obvPts);
                this.subSeriesList.push(obvSeries);
                break;
            }

            case 'mfi': {
                titleText = 'Money Flow Index (MFI 14)';
                const mfiPts = _prepareCurvePoints(d.mfi ? d.mfi.points : d.mfi_curve);
                const lastVal = d.mfi && d.mfi.last_mfi !== null ? d.mfi.last_mfi : (mfiPts.length ? mfiPts[mfiPts.length - 1].value : null);
                legendText = lastVal !== null ? `MFI: ${lastVal.toFixed(2)}` : '';

                const mfiSeries = this.subChart.addLineSeries({ color: '#39c5bb', lineWidth: 1.5, title: 'MFI' });
                mfiSeries.setData(mfiPts);
                this.subSeriesList.push(mfiSeries);

                try {
                    mfiSeries.createPriceLine({ price: 80, color: 'rgba(239, 83, 80, 0.7)', lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'OB 80' });
                    mfiSeries.createPriceLine({ price: 20, color: 'rgba(38, 166, 154, 0.7)', lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'OS 20' });
                } catch (_) {}
                break;
            }

            case 'sprint': {
                titleText = 'YOGI Sprint Speed (4w)';
                const spPts = _prepareCurvePoints(d.y_sprint ? d.y_sprint.points : d.y_sprint_curve);
                const lastVal = d.y_sprint && d.y_sprint.last_speed !== null ? d.y_sprint.last_speed : (spPts.length ? spPts[spPts.length - 1].value : null);
                legendText = lastVal !== null ? `Speed: ${lastVal >= 0 ? '+' : ''}${lastVal.toFixed(2)} %/wk` : '';

                const spSeries = this.subChart.addLineSeries({ color: '#26a69a', lineWidth: 1.5, title: 'Sprint Speed' });
                spSeries.setData(spPts);
                this.subSeriesList.push(spSeries);

                try {
                    spSeries.createPriceLine({ price: 0, color: 'rgba(139, 148, 158, 0.5)', lineStyle: window.LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
                } catch (_) {}
                break;
            }

            case 'accel': {
                titleText = 'YOGI Acceleration (4w vs 52w)';
                const acPts = _prepareCurvePoints(d.y_accel ? d.y_accel.points : d.y_accel_curve);
                const lastVal = d.y_accel && d.y_accel.last_accel !== null ? d.y_accel.last_accel : (acPts.length ? acPts[acPts.length - 1].value : null);
                legendText = lastVal !== null ? `Accel: ${lastVal >= 0 ? '+' : ''}${lastVal.toFixed(2)} pts/wk` : '';

                const acSeries = this.subChart.addLineSeries({ color: '#f0883e', lineWidth: 1.5, title: 'Acceleration' });
                acSeries.setData(acPts);
                this.subSeriesList.push(acSeries);

                try {
                    acSeries.createPriceLine({ price: 0, color: 'rgba(139, 148, 158, 0.5)', lineStyle: window.LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
                } catch (_) {}
                break;
            }

            case 'band_dist': {
                titleText = 'YOGI Band Distance';
                const bdPts = _prepareCurvePoints(d.y_band ? d.y_band.points : d.y_band_curve);
                const lastVal = d.y_band && d.y_band.last_distance !== null ? d.y_band.last_distance : (bdPts.length ? bdPts[bdPts.length - 1].value : null);
                legendText = lastVal !== null ? `Distance: ${lastVal >= 0 ? '+' : ''}${lastVal.toFixed(2)}%` : '';

                const bdSeries = this.subChart.addLineSeries({ color: '#a371f7', lineWidth: 1.5, title: 'Band Distance' });
                bdSeries.setData(bdPts);
                this.subSeriesList.push(bdSeries);

                try {
                    bdSeries.createPriceLine({ price: 0, color: 'rgba(139, 148, 158, 0.5)', lineStyle: window.LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
                } catch (_) {}
                break;
            }

            case 'yogi_roc': {
                titleText = 'YOGI ROC (21d)';
                const rocPts = _prepareCurvePoints(d.y_roc ? d.y_roc.points : d.y_roc_curve);
                const lastVal = d.y_roc && d.y_roc.last_roc !== null ? d.y_roc.last_roc : (rocPts.length ? rocPts[rocPts.length - 1].value : null);
                legendText = lastVal !== null ? `ROC: ${lastVal >= 0 ? '+' : ''}${lastVal.toFixed(2)}%` : '';

                const rocSeries = this.subChart.addLineSeries({ color: '#58a6ff', lineWidth: 1.5, title: 'YOGI ROC' });
                rocSeries.setData(rocPts);
                this.subSeriesList.push(rocSeries);

                try {
                    rocSeries.createPriceLine({ price: 0, color: 'rgba(139, 148, 158, 0.5)', lineStyle: window.LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
                } catch (_) {}
                break;
            }

            default:
                break;
        }

        if (subTitleEl) subTitleEl.textContent = titleText;
        if (subLegendEl) subLegendEl.textContent = legendText;

        this.resize();
        try {
            this.subChart.timeScale().fitContent();
        } catch (_) {}
    }

    _renderFallback(data) {
        this.container.innerHTML = '';
        const canvas = document.createElement('canvas');
        canvas.width = this.container.clientWidth || 600;
        canvas.height = this.container.clientHeight || 260;
        this.container.appendChild(canvas);
        const ctx = canvas.getContext('2d');

        ctx.fillStyle = '#131722';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        canvas.addEventListener('click', (e) => {
            if (!this.isMeasuring) return;
            const rect = canvas.getBoundingClientRect();
            const y = e.clientY - rect.top;
            const x = e.clientX - rect.left;
            const availableH = canvas.height - 40;
            const ratio = (canvas.height - 20 - y) / (availableH || 1);
            const price = minP + ratio * priceRange;
            const barIdx = Math.max(0, Math.min(candles.length - 1, Math.floor((x - 20) / (stepX || 1))));
            const time = candles[barIdx] ? candles[barIdx].time : null;
            this.recordMeasurePoint(price, time);
        });

        const candles = data.candles || [];
        if (candles.length === 0) {
            ctx.fillStyle = '#8b949e';
            ctx.font = '12px sans-serif';
            ctx.fillText('No candle data available', 20, 40);
            return;
        }

        const allPrices = [...candles.map(c => c.high), ...candles.map(c => c.low)];
        if (this.overlays.bands && data.band_upper_curve) {
            data.band_upper_curve.forEach(pt => { if (typeof pt.value === 'number') allPrices.push(pt.value); });
        }
        if (this.overlays.bands && data.band_lower_curve) {
            data.band_lower_curve.forEach(pt => { if (typeof pt.value === 'number') allPrices.push(pt.value); });
        }

        const minP = Math.min(...allPrices) * 0.98;
        const maxP = Math.max(...allPrices) * 1.02;
        const priceRange = maxP - minP || 1;

        const getY = (val) => canvas.height - 20 - ((val - minP) / priceRange) * (canvas.height - 40);
        const stepX = (canvas.width - 40) / candles.length;

        // Draw candles
        candles.forEach((c, i) => {
            const x = 20 + i * stepX + stepX / 2;
            const openY = getY(c.open);
            const closeY = getY(c.close);
            const highY = getY(c.high);
            const lowY = getY(c.low);
            const isUp = c.close >= c.open;

            ctx.strokeStyle = isUp ? '#26a69a' : '#ef5350';
            ctx.fillStyle = isUp ? '#26a69a' : '#ef5350';

            // Wick
            ctx.beginPath();
            ctx.moveTo(x, highY);
            ctx.lineTo(x, lowY);
            ctx.stroke();

            // Body
            const bodyY = Math.min(openY, closeY);
            const bodyH = Math.max(Math.abs(closeY - openY), 1);
            const w = Math.max(stepX * 0.7, 2);
            ctx.fillRect(x - w / 2, bodyY, w, bodyH);
        });

        // Draw Band Envelope Curves (Upper = Blue dashed, Lower = Red dashed)
        if (this.overlays.bands) {
            const timeToX = new Map(candles.map((c, i) => [c.time, 20 + i * stepX + stepX / 2]));
            const drawCurve = (curvePoints, color) => {
                if (!curvePoints || curvePoints.length === 0) return;
                ctx.save();
                ctx.strokeStyle = color;
                ctx.lineWidth = 1.5;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                let first = true;
                curvePoints.forEach(pt => {
                    const x = timeToX.get(pt.time);
                    if (x !== undefined && pt.value !== null && pt.value !== undefined) {
                        const y = getY(pt.value);
                        if (first) {
                            ctx.moveTo(x, y);
                            first = false;
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                });
                ctx.stroke();
                ctx.restore();
            };

            drawCurve(data.band_upper_curve, '#58a6ff');
            drawCurve(data.band_lower_curve, '#f85149');
        }

        ctx.fillStyle = '#8b949e';
        ctx.font = '10px monospace';
        ctx.fillText(`Max: ${maxP.toFixed(2)} | Min: ${minP.toFixed(2)} (${candles.length} bars)`, 10, 15);
    }
}

window.CockpitChart = CockpitChart;
