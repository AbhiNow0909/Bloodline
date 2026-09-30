import type { ReactNode } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from 'recharts'

import { formatDate, REPORT_TIME_ZONE } from '../lib/format'
import { FlagLabel } from '../reports/FlagLabel'
import type { ChartModel, ChartPoint } from './chartData'

const DAY_MS = 24 * 60 * 60 * 1000
const MONTH_YEAR = new Intl.DateTimeFormat('en-IN', {
  month: 'short',
  year: 'numeric',
  timeZone: REPORT_TIME_ZONE,
})
const DAY_MONTH = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  timeZone: REPORT_TIME_ZONE,
})
const NUMBER = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 })

const AXIS_TICK = { fill: 'var(--color-muted)', fontSize: 14 }
const BAND_FILL = 'var(--color-edta-soft)'

interface DotProps {
  cx?: number
  cy?: number
  index?: number
  payload?: ChartPoint
}

/** A result on the line: a circle, or a triangle pointing up (High) or down (Low), so the
 * flag never depends on colour alone. */
function FlagDot({ cx, cy, index, payload, active = false }: DotProps & { active?: boolean }) {
  const key = `dot-${String(index ?? 0)}`
  if (cx === undefined || cy === undefined || !payload) return <g key={key} />
  const size = active ? 9 : 7
  if (payload.flag === 'high' || payload.flag === 'low') {
    const up = payload.flag === 'high'
    const d = up
      ? `M${String(cx)} ${String(cy - size)} L${String(cx + size)} ${String(cy + size * 0.8)} L${String(cx - size)} ${String(cy + size * 0.8)} Z`
      : `M${String(cx)} ${String(cy + size)} L${String(cx + size)} ${String(cy - size * 0.8)} L${String(cx - size)} ${String(cy - size * 0.8)} Z`
    return <path key={key} d={d} fill="var(--color-alert)" stroke="#fff" strokeWidth={1.5} />
  }
  return (
    <circle
      key={key}
      cx={cx}
      cy={cy}
      r={active ? 6 : 4.5}
      fill="#fff"
      stroke="var(--color-edta)"
      strokeWidth={2.5}
    />
  )
}

function ChartTooltip({ active, payload }: TooltipContentProps<TooltipValueType, string | number>) {
  const point = payload[0]?.payload as ChartPoint | undefined
  if (!active || !point) return null
  const { reading } = point
  const converted =
    reading.unit_canonical !== null && reading.unit !== reading.unit_canonical
      ? ` (${reading.value_canonical ?? ''} ${reading.unit_canonical})`
      : ''
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-sm">
      <p className="font-semibold">{formatDate(reading.collected_at)}</p>
      <p>
        {reading.value_text} {reading.unit}
        {converted}
      </p>
      <FlagLabel flag={reading.flag} />
    </div>
  )
}

function LegendItem({ children, mark }: { children: string; mark: ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <svg viewBox="0 0 20 20" className="size-5" aria-hidden="true" focusable="false">
        {mark}
      </svg>
      {children}
    </li>
  )
}

/** The chart itself. Screen readers get `summary`; every value is also in the table below it. */
export default function TrendChart({ model, summary }: { model: ChartModel; summary: string }) {
  const spanDays = (model.xDomain[1] - model.xDomain[0]) / DAY_MS
  const dateTick = spanDays >= 180 ? MONTH_YEAR : DAY_MONTH
  const hasBand = model.sharedBand !== null || model.points.some((p) => p.band !== null)

  return (
    <div className="flex flex-col gap-3">
      <div
        role="img"
        aria-label={summary}
        className="rounded-lg border border-line bg-surface p-2 pt-4"
      >
        <ComposedChart
          responsive
          accessibilityLayer={false}
          style={{ width: '100%', height: 300 }}
          data={model.points}
          margin={{ top: 8, right: 16, bottom: 4, left: 4 }}
        >
          <CartesianGrid vertical={false} stroke="var(--color-line)" />
          {model.sharedBand ? (
            <ReferenceArea
              x1={model.xDomain[0]}
              x2={model.xDomain[1]}
              y1={model.sharedBand[0]}
              y2={model.sharedBand[1]}
              fill={BAND_FILL}
              fillOpacity={1}
              stroke="none"
            />
          ) : (
            <Area
              dataKey="band"
              type="linear"
              stroke="none"
              fill={BAND_FILL}
              fillOpacity={1}
              activeDot={false}
              isAnimationActive={false}
            />
          )}
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={model.xDomain}
            ticks={model.xTicks}
            tickFormatter={(t: number) => dateTick.format(t)}
            tick={AXIS_TICK}
            stroke="var(--color-line)"
          />
          <YAxis
            domain={model.yDomain}
            ticks={model.yTicks}
            allowDataOverflow
            width={56}
            tickFormatter={(value: number) => NUMBER.format(value)}
            tick={AXIS_TICK}
            stroke="var(--color-line)"
          />
          <Tooltip
            content={ChartTooltip}
            cursor={{ stroke: 'var(--color-muted)', strokeDasharray: '4 4' }}
            isAnimationActive={false}
          />
          <Line
            dataKey="value"
            type="linear"
            stroke="var(--color-edta)"
            strokeWidth={2.5}
            dot={(props: DotProps) => <FlagDot {...props} />}
            activeDot={(props: DotProps) => <FlagDot {...props} active />}
            isAnimationActive={false}
          />
        </ComposedChart>
      </div>
      <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
        {hasBand && (
          <LegendItem mark={<rect x="1" y="4" width="18" height="12" rx="2" fill={BAND_FILL} />}>
            The lab's reference range
          </LegendItem>
        )}
        <LegendItem
          mark={
            <circle
              cx="10"
              cy="10"
              r="5"
              fill="#fff"
              stroke="var(--color-edta)"
              strokeWidth="2.5"
            />
          }
        >
          In range or not compared
        </LegendItem>
        <LegendItem mark={<path d="M10 3 L17 15 L3 15 Z" fill="var(--color-alert)" />}>
          High
        </LegendItem>
        <LegendItem mark={<path d="M10 17 L17 5 L3 5 Z" fill="var(--color-alert)" />}>
          Low
        </LegendItem>
      </ul>
    </div>
  )
}
