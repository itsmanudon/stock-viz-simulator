/**
 * Populate the dev database with a demo account that has something to look at.
 *
 * Trades, orders, alerts, and watchlist entries all go through the real API
 * rather than being INSERTed directly, so cash, reserved amounts, average cost,
 * and realized P&L stay internally consistent with the trading engine. The one
 * exception is portfolio_snapshots: those are a derived daily cache written by
 * a scheduler job, and a demo needs them backdated, which no endpoint offers.
 *
 * Re-runnable: each run first deletes the demo accounts and everything that
 * hangs off them, then rebuilds from scratch. It has to work that way rather
 * than topping up, because the cost-basis adjustment below is relative —
 * applying it twice to the same position would compound the discount and
 * inflate the demo P&L a little more on every run.
 *
 * Only rows belonging to the demo emails are touched; a real account you
 * signed up with by hand is left alone.
 *
 * Usage:  pnpm stack:seed
 */

import bcrypt from "bcryptjs";
import { SignJWT } from "jose";
import pg from "pg";

const API_URL = process.env.SEED_API_URL ?? "http://127.0.0.1:8000";
const DATABASE_URL =
  process.env.SEED_DATABASE_URL ?? "postgres://stockviz:stockviz_dev@127.0.0.1:5434/stockviz";
const INTERNAL_API_TOKEN = process.env.INTERNAL_API_TOKEN ?? "dev-internal-token-change-me";
const PASSWORD = process.env.SEED_PASSWORD ?? "demo1234";

const ACCOUNTS = [
  {
    email: "demo@stockviz.local",
    name: "Demo Trader",
    publicProfile: true,
    buys: [
      ["AAPL", 90],
      ["MSFT", 40],
      ["NVDA", 180],
      ["GOOGL", 60],
      ["JPM", 30],
      ["KO", 120],
    ],
    // Partial sells so the trade history shows realized gains and losses.
    sells: [
      ["KO", 40],
      ["AAPL", 15],
    ],
    orders: [
      { ticker: "TSLA", side: "buy", order_type: "limit", quantity: "25", limit_price: "180.00" },
      {
        ticker: "NVDA",
        side: "sell",
        order_type: "take_profit",
        quantity: "50",
        limit_price: "140.00",
      },
      {
        ticker: "MSFT",
        side: "sell",
        order_type: "stop_loss",
        quantity: "30",
        limit_price: "300.00",
      },
    ],
    alerts: [
      { ticker: "AAPL", direction: "below", target_price: "170.00" },
      { ticker: "NVDA", direction: "above", target_price: "130.00" },
      { ticker: "META", direction: "above", target_price: "560.00" },
    ],
    watchlist: ["TSLA", "META", "AMZN", "NFLX", "V"],
  },
  {
    email: "ava@stockviz.local",
    name: "Ava Lindqvist",
    publicProfile: true,
    buys: [
      ["NVDA", 300],
      ["META", 40],
      ["AMZN", 90],
    ],
    sells: [],
    orders: [],
    alerts: [],
    watchlist: ["AAPL", "MSFT"],
  },
  {
    email: "ren@stockviz.local",
    name: "Ren Okafor",
    publicProfile: true,
    buys: [
      ["KO", 400],
      ["JNJ", 120],
      ["WMT", 150],
    ],
    sells: [["KO", 100]],
    orders: [],
    alerts: [],
    watchlist: ["XOM", "PFE"],
  },
];

const key = new TextEncoder().encode(INTERNAL_API_TOKEN);

async function mintToken(userId) {
  return new SignJWT({ sub: String(userId) })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(key);
}

async function api(userId, path, { method = "GET", body } = {}) {
  const token = await mintToken(userId);
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${method} ${path} -> ${res.status} ${text.slice(0, 200)}`);
  }
  return res.status === 204 ? null : res.json();
}

/** Best-effort: a duplicate watchlist row or an unaffordable order shouldn't abort the run. */
async function tryApi(userId, path, init, label) {
  try {
    await api(userId, path, init);
    return true;
  } catch (err) {
    console.warn(`    skipped ${label}: ${err.message.split("\n")[0]}`);
    return false;
  }
}

/**
 * Delete the demo accounts and everything referencing them.
 *
 * Ordered by foreign key so each statement stands alone — Postgres runs a
 * multi-statement query as one transaction, so a single FK violation would
 * roll back the whole batch and silently leave the data in place.
 */
async function resetDemoAccounts(client, emails) {
  const { rows } = await client.query("SELECT id FROM users WHERE email = ANY($1)", [emails]);
  if (rows.length === 0) return 0;
  const ids = rows.map((r) => r.id);

  const byPortfolio = [
    "DELETE FROM simulated_executions WHERE trade_id IN (SELECT t.id FROM trades t JOIN portfolios pf ON pf.id = t.portfolio_id WHERE pf.user_id = ANY($1))",
    "DELETE FROM trades WHERE portfolio_id IN (SELECT id FROM portfolios WHERE user_id = ANY($1))",
    "DELETE FROM positions WHERE portfolio_id IN (SELECT id FROM portfolios WHERE user_id = ANY($1))",
    "DELETE FROM pending_orders WHERE portfolio_id IN (SELECT id FROM portfolios WHERE user_id = ANY($1))",
    "DELETE FROM options_positions WHERE portfolio_id IN (SELECT id FROM portfolios WHERE user_id = ANY($1))",
    "DELETE FROM portfolio_dividends WHERE portfolio_id IN (SELECT id FROM portfolios WHERE user_id = ANY($1))",
    "DELETE FROM watchlist_items WHERE watchlist_id IN (SELECT id FROM watchlists WHERE user_id = ANY($1))",
    "DELETE FROM watchlists WHERE user_id = ANY($1)",
    "DELETE FROM alerts WHERE user_id = ANY($1)",
    "DELETE FROM comments WHERE user_id = ANY($1)",
    "DELETE FROM portfolio_snapshots WHERE user_id = ANY($1)",
    "DELETE FROM portfolios WHERE user_id = ANY($1)",
    "DELETE FROM users WHERE id = ANY($1)",
  ];

  for (const sql of byPortfolio) {
    await client.query(sql, [ids]);
  }
  return ids.length;
}

async function upsertUser(client, account) {
  const existing = await client.query("SELECT id FROM users WHERE email = $1", [account.email]);
  if (existing.rows.length > 0) {
    await client.query("UPDATE users SET public_profile = $2 WHERE id = $1", [
      existing.rows[0].id,
      account.publicProfile,
    ]);
    return { id: existing.rows[0].id, created: false };
  }
  const hash = await bcrypt.hash(PASSWORD, 10);
  const inserted = await client.query(
    `INSERT INTO users (email, name, password_hash, public_profile, display_currency, created_at)
     VALUES ($1, $2, $3, $4, 'USD', NOW() - INTERVAL '120 days') RETURNING id`,
    [account.email, account.name, hash, account.publicProfile],
  );
  return { id: inserted.rows[0].id, created: true };
}

/**
 * Give the book a real cost basis.
 *
 * Market orders fill at the latest stored close, so a freshly seeded account
 * has avg_cost === market price and therefore exactly zero P&L — every return
 * figure, mover, and NAV delta in the UI renders as 0.00%. Nothing is wrong
 * with the engine; the demo is just standing at t=0.
 *
 * So we re-price each position and hand the cash difference back, which keeps
 * the books balanced:
 *
 *   cash + cost_basis  stays equal to the original 100k
 *   market_value       is still today's close
 *   unrealized P&L     becomes market_value - cost_basis, i.e. real
 *
 * The entry price is derived from today's close times a random factor rather
 * than read from history on purpose. The bundled CSVs are not split-adjusted —
 * NVDA trades near $97 today and near $1,200 before its 10:1 split — so a real
 * historical close can price a position at ten times its market value and
 * drive cash negative. The factor band is centred slightly below 1 so a demo
 * book shows a mix of winners and losers that nets out modestly positive.
 *
 * Buy-side trade rows are re-priced to match so the trade history agrees with
 * the position it produced.
 */
async function backdateCostBasis(client, userId) {
  const { rows: positions } = await client.query(
    `SELECT p.id, p.ticker, p.quantity, p.avg_cost, pf.id AS portfolio_id
       FROM positions p
       JOIN portfolios pf ON pf.id = p.portfolio_id
      WHERE pf.user_id = $1`,
    [userId],
  );

  let cashDelta = 0;
  for (const position of positions) {
    const original = Number(position.avg_cost);
    if (!Number.isFinite(original) || original <= 0) continue;

    // 0.70x - 1.15x of the fill price: up to ~43% up, ~13% down.
    const factor = 0.7 + Math.random() * 0.45;
    const entry = original * factor;
    const qty = Number(position.quantity);
    cashDelta += qty * (original - entry);

    await client.query("UPDATE positions SET avg_cost = $2 WHERE id = $1", [
      position.id,
      entry.toFixed(6),
    ]);
    // The tradeside enum stores member NAMES ('BUY'), not values ('buy').
    await client.query(
      `UPDATE trades SET price = $3
        WHERE portfolio_id = $1 AND ticker = $2 AND side = 'BUY'`,
      [position.portfolio_id, position.ticker, entry.toFixed(6)],
    );
  }

  if (cashDelta !== 0) {
    await client.query(
      "UPDATE portfolios SET cash_balance = cash_balance + $2 WHERE user_id = $1",
      [userId, cashDelta.toFixed(6)],
    );
  }
  return positions.length;
}

/**
 * Backdated NAV history so the dashboard hero and portfolio chart have a curve.
 *
 * Interpolates from the account's opening balance on the oldest day to its real
 * current NAV today, with noise on top. Anchoring both ends matters: the
 * leaderboard and the portfolio page derive "return" from the FIRST snapshot,
 * so a series that merely random-walks backwards invents a starting NAV and
 * reports a return that contradicts the actual cost basis — a book up 4% showed
 * as up 36%. Ending exactly on the true NAV keeps every derived figure honest.
 */
async function seedSnapshots(client, userId, currentNav, openingNav, days = 120) {
  const rows = [];
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = new Date();
    date.setDate(date.getDate() - i);

    const progress = (days - 1 - i) / (days - 1);
    const trend = openingNav + (currentNav - openingNav) * progress;
    // Noise tapers to zero at both ends so the anchors stay exact.
    const wobble = Math.sin(progress * Math.PI) * (Math.random() - 0.5) * 0.05;
    const nav = i === 0 ? currentNav : trend * (1 + wobble);

    rows.push([date.toISOString().slice(0, 10), nav.toFixed(6)]);
  }

  for (const [date, value] of rows) {
    await client.query(
      `INSERT INTO portfolio_snapshots (user_id, date, nav) VALUES ($1, $2, $3)
       ON CONFLICT (user_id, date) DO UPDATE SET nav = EXCLUDED.nav`,
      [userId, date, value],
    );
  }
  return rows.length;
}

async function main() {
  const client = new pg.Client({ connectionString: DATABASE_URL });
  await client.connect();

  try {
    const live = await fetch(`${API_URL}/live`)
      .then((r) => r.ok)
      .catch(() => false);
    if (!live) throw new Error(`API is not reachable at ${API_URL} — start the stack first.`);

    const removed = await resetDemoAccounts(
      client,
      ACCOUNTS.map((a) => a.email),
    );
    if (removed > 0) console.log(`Reset ${removed} existing demo account(s).`);

    for (const account of ACCOUNTS) {
      const { id } = await upsertUser(client, account);
      console.log(`\n${account.name} <${account.email}>  (id ${id})`);

      for (const [ticker, qty] of account.buys) {
        await tryApi(
          id,
          "/v1/trades",
          {
            method: "POST",
            body: { ticker, side: "buy", quantity: String(qty) },
          },
          `buy ${qty} ${ticker}`,
        );
      }
      for (const [ticker, qty] of account.sells) {
        await tryApi(
          id,
          "/v1/trades",
          {
            method: "POST",
            body: { ticker, side: "sell", quantity: String(qty) },
          },
          `sell ${qty} ${ticker}`,
        );
      }
      for (const order of account.orders) {
        await tryApi(id, "/v1/orders", { method: "POST", body: order }, `order ${order.ticker}`);
      }
      for (const alert of account.alerts) {
        await tryApi(id, "/v1/alerts", { method: "POST", body: alert }, `alert ${alert.ticker}`);
      }
      for (const ticker of account.watchlist) {
        await tryApi(id, `/v1/watchlist/${ticker}`, { method: "POST" }, `watch ${ticker}`);
      }

      await backdateCostBasis(client, id);

      const portfolio = await api(id, "/v1/portfolio");
      const nav = Number(portfolio.total_value);
      // Every account opens with the same simulated 100k.
      const written = await seedSnapshots(client, id, nav, 100_000);
      const pnl = Number(portfolio.unrealized_pl);
      console.log(
        `  positions ${portfolio.positions.length} · NAV $${nav.toLocaleString("en-US", {
          maximumFractionDigits: 2,
        })} · unrealized ${pnl >= 0 ? "+" : ""}$${pnl.toLocaleString("en-US", {
          maximumFractionDigits: 2,
        })} · ${written} daily snapshots`,
      );
    }

    console.log(`\nDone. Sign in with any of the emails above, password: ${PASSWORD}`);
  } finally {
    await client.end();
  }
}

main().catch((err) => {
  console.error(`\nSeed failed: ${err.message}`);
  process.exit(1);
});
