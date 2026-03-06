'use client';

interface ToneProps {
  tone?: 'gold' | 'cyan' | 'rose' | 'green';
}

interface ProgressRingProps extends ToneProps {
  value: number;
  label: string;
  caption?: string;
}

interface MiniBarsProps extends ToneProps {
  values: number[];
  labels?: string[];
}

interface DistributionMeterItem {
  label: string;
  value: number;
  tone?: 'gold' | 'cyan' | 'rose' | 'green';
}

interface DistributionMeterProps {
  items: DistributionMeterItem[];
}

interface PulseDotProps extends ToneProps {
  label: string;
  status: string;
}

function clampPercentage(value: number): number {
  if (Number.isNaN(value)) {
    return 0;
  }

  return Math.max(0, Math.min(100, Math.round(value)));
}

export function ProgressRing({ value, label, caption, tone = 'gold' }: ProgressRingProps) {
  const normalizedValue = clampPercentage(value);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (normalizedValue / 100) * circumference;

  return (
    <div className="viz-card">
      <div className={`progress-ring progress-ring--${tone}`}>
        <svg viewBox="0 0 140 140" aria-hidden="true">
          <circle className="progress-ring__track" cx="70" cy="70" r={radius} />
          <circle
            className="progress-ring__value"
            cx="70"
            cy="70"
            r={radius}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="progress-ring__center">
          <strong>{normalizedValue}%</strong>
          <span>{label}</span>
        </div>
      </div>
      {caption ? <p className="viz-caption">{caption}</p> : null}
    </div>
  );
}

export function MiniBars({ values, labels = [], tone = 'cyan' }: MiniBarsProps) {
  const normalizedValues = values.length > 0 ? values.map((value) => clampPercentage(value)) : [18, 42, 64, 58, 76];

  return (
    <div className={`mini-bars mini-bars--${tone}`} role="img" aria-label="Mini bar chart">
      {normalizedValues.map((value, index) => (
        <div key={`${value}-${index}`} className="mini-bars__item">
          <span className="mini-bars__bar" style={{ height: `${Math.max(value, 10)}%` }} />
          <span className="mini-bars__label">{labels[index] || String(index + 1)}</span>
        </div>
      ))}
    </div>
  );
}

export function DistributionMeter({ items }: DistributionMeterProps) {
  const total = items.reduce((sum, item) => sum + item.value, 0);

  return (
    <div className="distribution-meter">
      <div className="distribution-meter__track" aria-hidden="true">
        {items.map((item) => {
          const width = total === 0 ? 0 : (item.value / total) * 100;
          return (
            <span
              key={item.label}
              className={`distribution-meter__segment distribution-meter__segment--${item.tone || 'gold'}`}
              style={{ width: `${width}%` }}
            />
          );
        })}
      </div>
      <div className="distribution-meter__legend">
        {items.map((item) => (
          <div key={item.label} className="distribution-meter__legend-item">
            <span className={`distribution-meter__swatch distribution-meter__swatch--${item.tone || 'gold'}`} />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PulseDot({ label, status, tone = 'green' }: PulseDotProps) {
  return (
    <div className="pulse-dot">
      <span className={`pulse-dot__signal pulse-dot__signal--${tone}`} aria-hidden="true" />
      <div>
        <span className="tiny-label">{label}</span>
        <strong>{status}</strong>
      </div>
    </div>
  );
}
