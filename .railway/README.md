# Railway configuration

This project defines its Railway infrastructure in code.

```txt
.railway/railway.ts
```

Use this file to describe the Railway project you want: services, databases, buckets, custom domains, replicas, groups, and environment variables.

## Common commands

Create the configuration files:

```bash
railway config init
```

Import an existing Railway project into code:

```bash
railway config pull
```

Preview what Railway would change:

```bash
railway config plan
```

Apply the planned changes:

```bash
railway config apply
```

## Shared project (named partials)

The Railway project `stockviz` also runs Aegis News. Each repository owns its
slice as a named partial:

| Partial | File | Resources |
| --- | --- | --- |
| `stockviz` | this repository, `.railway/railway.ts` | Postgres, api, web, cron |
| `aegis` | `itsmanudon/aegis-news`, `.railway/railway.ts` | aegis-api, aegis-daily, aegis-raw |

Keep `export const partial = "stockviz"` in `railway.ts`. Without it the file
is planned as the whole project, and a plan deletes the Aegis services.
`railway config partials list` shows who owns what.

## Notes

- `railway config plan` is safe and does not change Railway.
- `railway config apply` previews changes and asks before applying unless you pass `--yes`.
- Destructive changes in non-interactive or agent sessions require `railway config apply --confirm-destructive` after reviewing the plan.
- Services already managed by `railway.json` must be migrated before `.railway/railway.ts` can manage them.
- Use `replicas` for scaling; advanced placement can still specify region names.
- Use `group("Name", [resources])` to keep large projects organized on the Railway canvas.
- Secrets imported from Railway are rendered as `preserve()` so existing values are retained without writing secret values to source. Use `railway config pull --omit-preserved-variables` for a smaller import.
