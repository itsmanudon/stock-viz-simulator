# StockViz design docs

Design hand-off for the web app's look and its next changes. Design only:
nothing in this folder is app code, and nothing here has been built yet.

| Folder | What it is | Read it when |
| --- | --- | --- |
| [`audit/`](./audit/README.md) | Round 2 UI audit (27 Nov 2026): scores, 27 findings with evidence (C21 to C27 from the deeper pass on Trade, Orders, Portfolio and Alerts), research | You want to know why a change is needed |
| [`redesign/`](./redesign/README.md) | **The build list**: every change in build order, with today's screen, the proposed design, what stays, files and "done when" checks | You are building |

## Decisions that hold

- **Palette: Liquid Chrome**, as it ships on `dev` and `main`. Brand champagne
  is for identity, focus and selection only; gain and loss colours only
  through `--positive` and `--negative`. No other palette is proposed.
- **Landing page:** keep it as it is, except the "Everything in the
  workspace" section (L1). Its new copy (heading, intro line, pill label)
  was approved by the owner on 27 Nov 2026; use it word for word.
- **Inside the app:** Title Case via `titleCase()`, never capitals; status as
  a shape and a word; one-shot motion that settles; `localStorage` only as a
  convenience.
- **Sidebar:** fold workspaces to a count, keep Today and the current
  workspace open, one icon per item, Market Pulse at the foot (M1). No pinned
  pages.

If the audit and the build list ever disagree, the build list wins: it is the
spec. The same content is on two private artifacts owned by the repo owner,
"StockViz PRISM Audit" and "StockViz New Changes".

A reference first pass of M1 and C14 to C17 exists on the closed, unmerged
PR #114. It is there to read, not to merge.
