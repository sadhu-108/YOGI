/**
 * Cockpit Chart Controller — TradingView Lightweight Charts & Fallback Renderer.
 */

class CockpitChart {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.chart = null;
        this.candleSeries = null;
        this.upperBandSeries = null;
        this.lowerBandSeries = null;
        this.init();
    }

    init() {
        if (!this.container) return;
        this.container.innerHTML = '';

        if (window.LightweightCharts) {
            this.chart = window.LightweightCharts.createChart(this.container, {
                width: this.container.clientWidth,
                height: this.container.clientHeight || 280,
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

            this.candleSeries = this.chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderVisible: false,
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350',
            });

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

            window.addEventListener('resize', () => {
                this.resize();
            });
        } else {
            console.warn('LightweightCharts not loaded; running with fallback canvas.');
        }
    }

    clear() {
        if (this.chart) {
            if (this.candleSeries) this.candleSeries.setData([]);
            if (this.upperBandSeries) this.upperBandSeries.setData([]);
            if (this.lowerBandSeries) this.lowerBandSeries.setData([]);
        }
        if (this.container) {
            const canvas = this.container.querySelector('canvas');
            if (canvas) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        }
    }

    resize() {
        if (!this.container) return;
        const w = this.container.clientWidth;
        const h = this.container.clientHeight || 280;
        if (this.chart && w > 0) {
            this.chart.applyOptions({
                width: w,
                height: h,
            });
            this.chart.timeScale().fitContent();
        }
    }

    render(seriesData) {
        if (!seriesData || !seriesData.candles) return;

        if (this.chart) {
            // Sort candles chronologically
            const candles = [...seriesData.candles].sort((a, b) => a.time.localeCompare(b.time));
            this.candleSeries.setData(candles);

            if (seriesData.band_upper_curve && seriesData.band_upper_curve.length > 0) {
                const upper = [...seriesData.band_upper_curve].sort((a, b) => a.time.localeCompare(b.time));
                this.upperBandSeries.setData(upper);
            } else {
                this.upperBandSeries.setData([]);
            }

            if (seriesData.band_lower_curve && seriesData.band_lower_curve.length > 0) {
                const lower = [...seriesData.band_lower_curve].sort((a, b) => a.time.localeCompare(b.time));
                this.lowerBandSeries.setData(lower);
            } else {
                this.lowerBandSeries.setData([]);
            }

            this.chart.timeScale().fitContent();
        } else {
            // Fallback rendering in standard HTML5 Canvas
            this._renderFallback(seriesData);
        }
    }

    _renderFallback(data) {
        this.container.innerHTML = '';
        const canvas = document.createElement('canvas');
        canvas.width = this.container.clientWidth || 600;
        canvas.height = this.container.clientHeight || 280;
        this.container.appendChild(canvas);
        const ctx = canvas.getContext('2d');

        ctx.fillStyle = '#131722';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const candles = data.candles || [];
        if (candles.length === 0) {
            ctx.fillStyle = '#8b949e';
            ctx.font = '12px sans-serif';
            ctx.fillText('No candle data available', 20, 40);
            return;
        }

        const allPrices = [...candles.map(c => c.high), ...candles.map(c => c.low)];
        if (data.band_upper_curve) {
            data.band_upper_curve.forEach(pt => { if (typeof pt.value === 'number') allPrices.push(pt.value); });
        }
        if (data.band_lower_curve) {
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

        ctx.fillStyle = '#8b949e';
        ctx.font = '10px monospace';
        ctx.fillText(`Max: ${maxP.toFixed(2)} | Min: ${minP.toFixed(2)} (${candles.length} bars)`, 10, 15);
    }
}

window.CockpitChart = CockpitChart;
