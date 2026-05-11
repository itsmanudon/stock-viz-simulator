/**
 * User-row CRUD against the shared Postgres ``users`` table.
 *
 * The schema is owned by the FastAPI side (Alembic migrations); we just SQL
 * against it directly. Keep these functions DB-only — no auth logic, no
 * password hashing, no NextAuth coupling.
 */

import { pool } from "./db";

export type UserRow = {
  id: number;
  email: string;
  name: string | null;
  image: string | null;
  password_hash: string | null;
};

export async function findUserByEmail(email: string): Promise<UserRow | null> {
  const result = await pool.query<UserRow>(
    "SELECT id, email, name, image, password_hash FROM users WHERE email = $1 LIMIT 1",
    [email.toLowerCase()],
  );
  return result.rows[0] ?? null;
}

export async function createUser(args: {
  email: string;
  name: string | null;
  passwordHash: string;
}): Promise<UserRow> {
  const result = await pool.query<UserRow>(
    `INSERT INTO users (email, name, password_hash, created_at)
     VALUES ($1, $2, $3, NOW())
     RETURNING id, email, name, image, password_hash`,
    [args.email.toLowerCase(), args.name, args.passwordHash],
  );
  return result.rows[0];
}
