/**
 * Display-only decimal helpers for paper-trade estimates.
 *
 * Accounting and reservations stay on the API. These functions multiply
 * decimal *strings* with integer arithmetic so the ticket does not invent
 * binary floating-point notionals.
 */

const DECIMAL_PATTERN = /^-?\d+(?:\.\d+)?$/;

type Scaled = { digits: bigint; scale: number; negative: boolean };

function parseDecimal(raw: string): Scaled | null {
  const value = raw.trim();
  if (!DECIMAL_PATTERN.test(value)) return null;
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  const digits = BigInt(`${whole}${fraction}` || "0");
  if (digits === 0n) return { digits: 0n, scale: fraction.length, negative: false };
  return { digits, scale: fraction.length, negative };
}

function padScale(value: Scaled, scale: number): bigint {
  const delta = scale - value.scale;
  return delta <= 0 ? value.digits : value.digits * 10n ** BigInt(delta);
}

export function multiplyDecimalStrings(
  left: string,
  right: string,
  fractionDigits = 2,
): string | null {
  const a = parseDecimal(left);
  const b = parseDecimal(right);
  if (!a || !b) return null;
  if (fractionDigits < 0 || fractionDigits > 12) return null;

  const productScale = a.scale + b.scale;
  const negative = a.negative !== b.negative && a.digits !== 0n && b.digits !== 0n;
  let digits = a.digits * b.digits;

  if (productScale < fractionDigits) {
    digits *= 10n ** BigInt(fractionDigits - productScale);
  } else if (productScale > fractionDigits) {
    const divisor = 10n ** BigInt(productScale - fractionDigits);
    const remainder = digits % divisor;
    digits = digits / divisor;
    if (remainder * 2n >= divisor) digits += 1n;
  }

  const sign = negative && digits !== 0n ? "-" : "";
  const padded = digits.toString().padStart(fractionDigits + 1, "0");
  if (fractionDigits === 0) return `${sign}${padded}`;
  const whole = padded.slice(0, -fractionDigits);
  const fraction = padded.slice(-fractionDigits);
  return `${sign}${whole}.${fraction}`;
}

export function compareDecimalStrings(left: string, right: string): number | null {
  const a = parseDecimal(left);
  const b = parseDecimal(right);
  if (!a || !b) return null;
  const scale = Math.max(a.scale, b.scale);
  const av = (a.negative ? -1n : 1n) * padScale(a, scale);
  const bv = (b.negative ? -1n : 1n) * padScale(b, scale);
  if (av === bv) return 0;
  return av > bv ? 1 : -1;
}
