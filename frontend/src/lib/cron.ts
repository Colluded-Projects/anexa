// Client-side checks for 5-field crontab expressions. The server is the
// authority; this only catches obvious mistakes and explains the schedule.

interface FieldDef {
  name: string;
  min: number;
  max: number;
  names?: string[];
}

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const FIELDS: FieldDef[] = [
  { name: "minute", min: 0, max: 59 },
  { name: "hour", min: 0, max: 23 },
  { name: "day of month", min: 1, max: 31 },
  { name: "month", min: 1, max: 12, names: MONTHS },
  { name: "day of week", min: 0, max: 7, names: DAYS },
];

function parseValue(raw: string, def: FieldDef): number | null {
  if (/^\d+$/.test(raw)) {
    const value = Number(raw);
    return value >= def.min && value <= def.max ? value : null;
  }
  if (def.names) {
    const index = def.names.indexOf(raw.toUpperCase());
    if (index >= 0) return index + (def.name === "month" ? 1 : 0);
  }
  return null;
}

function checkPart(part: string, def: FieldDef): string | null {
  const [range, step, extra] = part.split("/");
  if (extra !== undefined || range === undefined || range === "") {
    return `"${part}" is not valid for ${def.name}`;
  }
  if (step !== undefined && (!/^\d+$/.test(step) || Number(step) < 1)) {
    return `step "${step}" in ${def.name} must be a positive number`;
  }
  if (range === "*") return null;
  const bounds = range.split("-");
  if (bounds.length > 2) return `"${part}" is not valid for ${def.name}`;
  const values = bounds.map((bound) => parseValue(bound, def));
  if (values.some((value) => value === null)) {
    return `${def.name} must be ${def.min}-${def.max}, got "${part}"`;
  }
  if (values.length === 2 && (values[0] as number) > (values[1] as number)) {
    return `range "${range}" in ${def.name} runs backwards`;
  }
  return null;
}

/** Returns a message describing the first problem, or null when the expression looks valid. */
export function validateCron(expression: string): string | null {
  const fields = expression.trim().split(/\s+/).filter(Boolean);
  if (fields.length !== 5) {
    return `Expected 5 fields (minute hour day-of-month month day-of-week), got ${fields.length}.`;
  }
  for (const [index, field] of fields.entries()) {
    const def = FIELDS[index] as FieldDef;
    for (const part of field.split(",")) {
      const problem = checkPart(part, def);
      if (problem) return `${problem[0]?.toUpperCase()}${problem.slice(1)}.`;
    }
  }
  return null;
}

const pad = (value: number) => String(value).padStart(2, "0");
const isNumber = (field: string) => /^\d+$/.test(field);

function joinList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function nameOf(raw: string, def: FieldDef, labels: string[]): string {
  const value = parseValue(raw, def);
  if (value === null) return raw;
  if (def.name === "month") return labels[value - 1] ?? raw;
  return labels[value % 7] ?? raw;
}

function describeNamed(field: string, def: FieldDef, labels: string[]): string {
  return joinList(
    field.split(",").map((part) => {
      const [range = "", step] = part.split("/");
      const [from = "", to] = range.split("-");
      const text =
        to === undefined
          ? nameOf(from, def, labels)
          : `${nameOf(from, def, labels)} through ${nameOf(to, def, labels)}`;
      return step ? `every ${step} from ${text}` : text;
    }),
  );
}

function describeTime(minute: string, hour: string): string {
  if (isNumber(minute) && isNumber(hour)) return `at ${pad(Number(hour))}:${pad(Number(minute))}`;
  if (minute === "*" && hour === "*") return "every minute";
  if (minute.startsWith("*/") && hour === "*") {
    const step = minute.slice(2);
    return step === "1" ? "every minute" : `every ${step} minutes`;
  }
  if (isNumber(minute) && hour === "*") {
    return minute === "0" ? "every hour" : `every hour at minute ${Number(minute)}`;
  }
  if (isNumber(minute) && hour.startsWith("*/")) {
    const step = hour.slice(2);
    const base = step === "1" ? "every hour" : `every ${step} hours`;
    return minute === "0" ? base : `${base} at minute ${Number(minute)}`;
  }
  if (isNumber(minute) && /^[\d,]+$/.test(hour)) {
    return `at ${joinList(hour.split(",").map((h) => `${pad(Number(h))}:${pad(Number(minute))}`))}`;
  }
  if (minute === "*" && isNumber(hour)) return `every minute during hour ${pad(Number(hour))}`;
  return `at minute ${minute} of hour ${hour}`;
}

/** Plain-English summary of a valid expression; empty string when it is invalid. */
export function describeCron(expression: string): string {
  if (validateCron(expression)) return "";
  const [minute = "*", hour = "*", dom = "*", month = "*", dow = "*"] = expression
    .trim()
    .split(/\s+/);

  const time = describeTime(minute, hour);
  const days: string[] = [];
  if (dow !== "*") days.push(`on ${describeNamed(dow, FIELDS[4] as FieldDef, DAY_NAMES)}`);
  if (dom !== "*") {
    days.push(
      dom.startsWith("*/")
        ? `every ${dom.slice(2)} days`
        : `on day ${joinList(dom.split(","))} of the month`,
    );
  }
  if (month !== "*") days.push(`in ${describeNamed(month, FIELDS[3] as FieldDef, MONTH_NAMES)}`);

  const frequent = time.startsWith("every");
  const text = days.length
    ? `${time} ${days.join(", ")}`
    : frequent
      ? time
      : `every day ${time}`;
  return `${text[0]?.toUpperCase()}${text.slice(1)}`;
}

export const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: "Every 15 minutes", cron: "*/15 * * * *" },
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily at 09:00", cron: "0 9 * * *" },
  { label: "Weekdays at 09:00", cron: "0 9 * * 1-5" },
  { label: "Mondays at 09:00", cron: "0 9 * * 1" },
];
