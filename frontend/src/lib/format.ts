/**
 * How numbers read on screen (DESIGN.md section 3): scores with three decimals, as Appendix C prints
 * them; durations as minutes and seconds; positions as ordinals.
 */

export function formatScore(score: number): string {
  return score.toFixed(3);
}

/** 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st. */
export function ordinal(n: number): string {
  const lastTwo = n % 100;
  if (lastTwo >= 11 && lastTwo <= 13) {
    return `${n}th`;
  }
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

/** "14:02:31": a time of day on the 24-hour clock, in the browser's own time zone. */
export function formatTimeOfDay(date: Date): string {
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

/**
 * A timestamp from the API. PostgreSQL's carry their offset; a SQLite test database drops it. The
 * backend writes every time in UTC, so one without an offset is read as UTC, never as local time.
 */
export function parseApiTime(text: string): Date {
  return new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}Z`);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "14:02" today, "16 Oct 14:02" earlier this year, "16 Oct 2025 14:02" before that. Local time,
 * 24-hour clock, the same in every browser. */
export function formatWhen(date: Date, now: Date = new Date()): string {
  const time = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  if (date.toDateString() === now.toDateString()) {
    return time;
  }
  const day = `${String(date.getDate())} ${MONTHS[date.getMonth()] ?? ""}`;
  return date.getFullYear() === now.getFullYear()
    ? `${day} ${time}`
    : `${day} ${String(date.getFullYear())} ${time}`;
}

/** 0.5 as "50%". */
export function formatPercent(ratio: number): string {
  return `${String(Math.round(ratio * 100))}%`;
}

/** "40s", "1m 20s", "2m 00s", "1h 05m": seconds are padded once there are minutes, so a column of
 * durations lines up. */
export function formatDuration(milliseconds: number): string {
  const total = Math.max(0, Math.round(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  }
  return `${seconds}s`;
}
