"use client";

/**
 * Settings → Notifications (A2.3): where the nightly notifications go
 * besides the bell. A signed webhook (URL and a write-only secret), email
 * (to the account address unless another is given) and Telegram (a chat
 * id). Each has "Send test", which goes through the server's real sender. A
 * channel the server has no config for says so, not an error. Unticking a
 * category keeps it in the bell but off that channel.
 */

import { useActionState } from "react";

import {
  type ChannelActionState,
  saveChannelAction,
  testChannelAction,
} from "@/app/(product)/(authed)/settings/notification-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { NotificationChannel } from "@/lib/api/notifications";

const LABELS: Record<NotificationChannel["channel"], string> = {
  webhook: "Webhook",
  email: "Email",
  telegram: "Telegram",
};

const CATEGORY_LABELS: Record<string, string> = {
  alert: "Alerts",
  screen: "Screens",
  order: "Orders",
  dividend: "Dividends",
  corporate_action: "Splits",
  option: "Options",
  system: "System",
};

function Message({ state }: { state: ChannelActionState }) {
  if (state.error)
    return (
      <p role="alert" className="text-xs text-negative">
        {state.error}
      </p>
    );
  if (state.ok) return <output className="block text-xs text-positive">{state.ok}</output>;
  return null;
}

function ChannelForm({
  channel,
  categories,
  accountEmail,
}: {
  channel: NotificationChannel;
  categories: string[];
  accountEmail?: string | null;
}) {
  const [saved, save, saving] = useActionState<ChannelActionState, FormData>(saveChannelAction, {});
  const [tested, test, testing] = useActionState<ChannelActionState, FormData>(
    testChannelAction,
    {},
  );
  const name = channel.channel;
  const label = LABELS[name];
  const heading = `channel-${name}`;

  if (!channel.available) {
    return (
      <section aria-labelledby={heading} className="space-y-1 py-3">
        <h3 id={heading} className="text-sm font-medium">
          {label}
        </h3>
        <p className="text-xs text-text-tertiary" data-testid={`channel-${name}-unavailable`}>
          Not available on this server.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby={heading} className="space-y-2.5 py-3">
      <h3 id={heading} className="text-sm font-medium">
        {label}
      </h3>
      <form action={save} className="space-y-2.5">
        <input type="hidden" name="channel" value={name} />
        <input type="hidden" name="categories" value={categories.join(",")} />
        {name === "webhook" ? (
          <>
            <div className="grid gap-1">
              <label htmlFor="webhook-url" className="text-xs text-text-tertiary">
                URL (https)
              </label>
              <Input
                id="webhook-url"
                name="url"
                type="url"
                defaultValue={channel.url ?? ""}
                placeholder="https://example.com/stockviz"
                maxLength={500}
              />
            </div>
            <div className="grid gap-1">
              <label htmlFor="webhook-secret" className="text-xs text-text-tertiary">
                Signing secret {channel.secret_set ? "(set; leave blank to keep it)" : ""}
              </label>
              <Input
                id="webhook-secret"
                name="secret"
                type="password"
                autoComplete="new-password"
                placeholder={channel.secret_set ? "set" : "at least 16 characters"}
                maxLength={256}
              />
              <p className="text-2xs text-text-tertiary">
                Each POST carries <code>X-StockViz-Signature: sha256=…</code>, an HMAC-SHA256 of the
                body under this secret.
              </p>
            </div>
          </>
        ) : null}
        {name === "email" ? (
          <div className="grid gap-1">
            <label htmlFor="email-address" className="text-xs text-text-tertiary">
              Address
            </label>
            <Input
              id="email-address"
              name="address"
              type="email"
              defaultValue={channel.address ?? ""}
              placeholder={accountEmail ?? "your account email"}
              maxLength={320}
            />
          </div>
        ) : null}
        {name === "telegram" ? (
          <div className="grid gap-1">
            <label htmlFor="telegram-chat" className="text-xs text-text-tertiary">
              Chat id
            </label>
            <Input
              id="telegram-chat"
              name="chat_id"
              defaultValue={channel.chat_id ?? ""}
              placeholder="123456789"
              maxLength={64}
              className="font-mono"
            />
            <p className="text-2xs text-text-tertiary">
              Start a chat with this server&apos;s bot, then paste your numeric chat id (a bot such
              as @userinfobot tells you yours).
            </p>
          </div>
        ) : null}
        <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          <legend className="mb-1 text-text-tertiary">Send</legend>
          {categories.map((c) => (
            <label key={c} className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                name={`send:${c}`}
                defaultChecked={!channel.muted_categories?.includes(c)}
              />
              {CATEGORY_LABELS[c] ?? c}
            </label>
          ))}
        </fieldset>
        <label className="inline-flex items-center gap-1.5 text-sm">
          <input type="checkbox" name="enabled" defaultChecked={channel.enabled} />
          Send my notifications here
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" size="sm" variant="outline" disabled={saving}>
            {saving ? "Saving…" : `Save ${label.toLowerCase()}`}
          </Button>
        </div>
        <Message state={saved} />
      </form>
      <form action={test} className="space-y-1">
        <input type="hidden" name="channel" value={name} />
        <Button
          type="submit"
          size="sm"
          variant="ghost"
          disabled={testing || !channel.configured}
          title={channel.configured ? undefined : "Save the channel first"}
        >
          {testing ? "Sending…" : "Send test"}
        </Button>
        <Message state={tested} />
      </form>
    </section>
  );
}

export function NotificationChannelsPanel({
  channels,
  categories,
  accountEmail,
}: {
  channels: NotificationChannel[];
  categories: string[];
  accountEmail?: string | null;
}) {
  return (
    <div className="divide-y divide-border-muted">
      <p className="pb-3 text-xs leading-relaxed text-text-tertiary">
        Notifications always appear in the app. They can also go to these channels after each
        nightly run; a failed send is retried a few times.
      </p>
      {channels.map((c) => (
        <ChannelForm
          key={c.channel}
          channel={c}
          categories={categories}
          accountEmail={accountEmail}
        />
      ))}
    </div>
  );
}
