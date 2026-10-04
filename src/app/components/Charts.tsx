import { HeatmapChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { graphic, init, use, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickSeries, createChart, HistogramSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { CorrelationMatrix, PerformancePoint, Position, PriceBar, SimulationPoint } from '../types'

use([HeatmapChart, LineChart, PieChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

function useEChart(option: EChartsCoreOption) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = init(ref.current)
    chart.setOption(option)
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [option])
  return ref
}

const baseAxis = {
  axisLine: { lineStyle: { color: '#26364b' } },
  axisLabel: { color: '#7890aa', fontFamily: 'Space Grotesk' },
  splitLine: { lineStyle: { color: 'rgba(77, 104, 132, .16)' } },
}

export function PerformanceChart({ points, valueMode = false }: { points: PerformancePoint[]; valueMode?: boolean }) {
  const { t } = useTranslation('charts')
  const legendItems = valueMode ? [t('portfolioValue')] : [t('myReturn'), t('benchmark')]
  const option: EChartsCoreOption = {
    animationDuration: 700,
    tooltip: { trigger: 'axis', backgroundColor: '#101b2a', borderColor: '#2b4059', textStyle: { color: '#e8f1fb' } },
    legend: {
      top: 4,
      right: 8,
      itemWidth: 18,
      itemHeight: 8,
      itemGap: 18,
      textStyle: { color: '#91a4ba' },
      data: legendItems,
    },
    grid: { left: 8, right: 12, top: 48, bottom: 24, containLabel: true },
    xAxis: { ...baseAxis, type: 'category', boundaryGap: false, data: points.map((point) => point.date.slice(5)) },
    yAxis: { ...baseAxis, type: 'value', axisLabel: { ...baseAxis.axisLabel, formatter: valueMode ? '${value}' : '{value}%' } },
    media: [{
      query: { maxWidth: 560 },
      option: {
        legend: { left: 8, right: 'auto', itemGap: 12 },
        grid: { left: 4, right: 8, top: 50, bottom: 24, containLabel: true },
      },
    }],
    series: valueMode ? [{
      name: t('portfolioValue'), type: 'line', smooth: 0.32, showSymbol: false,
      data: points.map((point) => point.portfolio_value),
      lineStyle: { width: 3, color: '#3dd6a6' },
      areaStyle: { color: new graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(61,214,166,.32)' }, { offset: 1, color: 'rgba(61,214,166,0)' }]) },
    }] : [
      { name: t('myReturn'), type: 'line', smooth: 0.3, showSymbol: false, data: points.map((point) => point.portfolio_return_pct), lineStyle: { width: 3, color: '#3dd6a6' }, areaStyle: { color: 'rgba(61,214,166,.08)' } },
      { name: t('benchmark'), type: 'line', smooth: 0.3, showSymbol: false, data: points.map((point) => point.benchmark_return_pct), lineStyle: { width: 2, color: '#ffbf69', type: 'dashed' } },
    ],
  }
  const ref = useEChart(option)
  return <div ref={ref} className="chart-canvas" />
}

export function AllocationChart({ positions, cash }: { positions: Position[]; cash: number }) {
  const { t } = useTranslation('charts')
  const items = [
    ...positions.map((position) => ({
      name: position.symbol.startsWith('NISA-') ? position.symbol.slice(5) : position.symbol,
      value: position.market_value,
    })),
    ...(cash > 0 ? [{ name: t('cash'), value: cash }] : []),
  ]
  const crowded = items.length > 6
  const option: EChartsCoreOption = {
    tooltip: { trigger: 'item', backgroundColor: '#101b2a', borderColor: '#2b4059', textStyle: { color: '#e8f1fb' } },
    legend: { show: !crowded, bottom: 0, textStyle: { color: '#91a4ba' } },
    color: ['#3dd6a6', '#58a6ff', '#ffbf69', '#ff6b7a', '#7b8da2'],
    series: [{
      type: 'pie', radius: ['50%', '72%'], center: ['50%', crowded ? '50%' : '43%'], avoidLabelOverlap: true,
      minShowLabelAngle: crowded ? 10 : 0,
      label: { color: '#b8c7d8', formatter: '{b} {d}%' },
      data: items,
    }],
  }
  const ref = useEChart(option)
  return <div ref={ref} className="chart-canvas" />
}

export function SimulationPnlChart({ points }: { points: SimulationPoint[] }) {
  const { t } = useTranslation('charts')
  const option: EChartsCoreOption = {
    animationDuration: 650,
    tooltip: { trigger: 'axis', backgroundColor: '#101b2a', borderColor: '#2b4059', textStyle: { color: '#e8f1fb' } },
    legend: { right: 0, textStyle: { color: '#91a4ba' }, data: [t('pnl'), t('positionValue')] },
    grid: { left: 8, right: 12, top: 42, bottom: 10, containLabel: true },
    xAxis: { ...baseAxis, type: 'category', boundaryGap: false, data: points.map((point) => point.trade_date.slice(5)) },
    yAxis: [
      { ...baseAxis, type: 'value', axisLabel: { ...baseAxis.axisLabel, formatter: '{value}%' } },
      { ...baseAxis, type: 'value', axisLabel: { ...baseAxis.axisLabel, formatter: '${value}' } },
    ],
    series: [
      {
        name: t('pnl'),
        type: 'line',
        smooth: 0.3,
        showSymbol: false,
        data: points.map((point) => point.pnl_pct),
        lineStyle: { width: 3, color: '#3dd6a6' },
        areaStyle: { color: 'rgba(61,214,166,.08)' },
        markLine: { symbol: 'none', lineStyle: { color: '#38546f', type: 'dashed' }, data: [{ yAxis: 0 }] },
      },
      {
        name: t('positionValue'),
        type: 'line',
        yAxisIndex: 1,
        smooth: 0.28,
        showSymbol: false,
        data: points.map((point) => point.value),
        lineStyle: { width: 2, color: '#58a6ff' },
      },
    ],
  }
  const ref = useEChart(option)
  return <div ref={ref} className="chart-canvas chart-canvas-compact" />
}

export function CorrelationHeatmap({ matrix }: { matrix: CorrelationMatrix }) {
  const { t } = useTranslation('charts')
  const option: EChartsCoreOption = {
    animationDuration: 500,
    tooltip: {
      backgroundColor: '#101b2a',
      borderColor: '#2b4059',
      textStyle: { color: '#e8f1fb' },
      formatter: (params: { value: [number, number, number] }) => {
        const [col, row, value] = params.value
        return `${matrix.symbols[row]} × ${matrix.symbols[col]}<br/><strong>${value.toFixed(2)}</strong>`
      },
    },
    grid: { left: 8, right: 8, top: 8, bottom: 58, containLabel: true },
    xAxis: {
      type: 'category', data: matrix.symbols, splitArea: { show: true },
      axisLine: { lineStyle: { color: '#26364b' } }, axisLabel: { color: '#7890aa', fontFamily: 'Space Grotesk' },
    },
    yAxis: {
      type: 'category', data: matrix.symbols, splitArea: { show: true },
      axisLine: { lineStyle: { color: '#26364b' } }, axisLabel: { color: '#7890aa', fontFamily: 'Space Grotesk' },
    },
    visualMap: {
      min: -1, max: 1, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 96,
      textStyle: { color: '#7890aa', fontFamily: 'Space Grotesk' },
      inRange: { color: ['#ff6b7a', '#ffbf69', '#3dd6a6'] },
    },
    series: [{
      type: 'heatmap',
      data: matrix.symbols.flatMap((_, row) => matrix.symbols.map((__, col) => [col, row, matrix.values[row][col]])),
      label: {
        show: true, color: '#e8f1fb', fontSize: 10,
        formatter: (params: { value: [number, number, number] }) => params.value[2].toFixed(2),
      },
      itemStyle: { borderColor: '#101b2a', borderWidth: 2 },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(61,214,166,.4)' } },
    }],
  }
  const ref = useEChart(option)
  return <div ref={ref} className="chart-canvas" />
}

export function PriceChart({ bars }: { bars: PriceBar[] }) {
  const { t } = useTranslation('charts')
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!container.current || !bars.length) return
    const chart = createChart(container.current, {
      layout: { background: { color: 'transparent' }, textColor: '#7890aa', fontFamily: 'Space Grotesk' },
      grid: { vertLines: { color: 'rgba(77,104,132,.12)' }, horzLines: { color: 'rgba(77,104,132,.12)' } },
      rightPriceScale: { borderColor: '#26364b' },
      timeScale: { borderColor: '#26364b' },
      height: 420,
    })
    const candles = chart.addSeries(CandlestickSeries, { upColor: '#3dd6a6', downColor: '#ff6b7a', borderVisible: false, wickUpColor: '#3dd6a6', wickDownColor: '#ff6b7a' })
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '', color: '#35506d' }, 1)
    const sorted = [...bars].sort((left, right) => left.trade_date.localeCompare(right.trade_date))
    candles.setData(sorted.map((bar) => ({
      time: bar.trade_date as Time,
      open: bar.open ?? bar.close,
      high: bar.high ?? bar.close,
      low: bar.low ?? bar.close,
      close: bar.close,
    })))
    volume.setData(sorted.map((bar) => ({ time: bar.trade_date as Time, value: bar.volume ?? 0, color: (bar.close >= (bar.open ?? bar.close)) ? 'rgba(61,214,166,.35)' : 'rgba(255,107,122,.35)' })))
    chart.timeScale().fitContent()
    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.current?.clientWidth ?? 0 }))
    observer.observe(container.current)
    return () => { observer.disconnect(); chart.remove() }
  }, [bars])
  if (!bars.length) return <div className="empty-chart"><strong>{t('noBars')}</strong><span>{t('noBarsHint')}</span><a href="#/monitor">{t('openMonitor')}</a></div>
  return <div ref={container} className="price-chart" />
}
