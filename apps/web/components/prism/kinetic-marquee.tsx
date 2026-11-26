/**
 * Oversized kinetic type band: the four verbs of the product scrolling past
 * in two opposite rows, one solid and one hollow. Decorative; the same words
 * are the headings of the sections around it. Reuses `.marquee` (which
 * stops under reduced motion and lets the row scroll by hand).
 */

const WORDS = ["Screen", "Backtest", "Simulate", "Replay", "Keep score"];

function Row({ hollow, reverse }: { hollow?: boolean; reverse?: boolean }) {
  const items = [...WORDS, ...WORDS].map((word, i) => ({
    word,
    key: `${word}-${i < WORDS.length ? "a" : "b"}`,
  }));
  return (
    <div className="marquee" aria-hidden>
      <div
        className="marquee-track"
        style={
          {
            "--marquee-duration": "48s",
            animationDirection: reverse ? "reverse" : undefined,
          } as React.CSSProperties
        }
      >
        {[0, 1].map((half) => (
          <div key={half} className="flex min-w-[100vw] shrink-0 items-center">
            {items.map(({ word, key }) => (
              <span
                key={`${half}-${key}`}
                className={
                  hollow
                    ? "marquee-display text-outline px-6 [--outline-color:var(--foreground)] opacity-60"
                    : "marquee-display px-6 text-foreground/90"
                }
              >
                {word}
                <span className="font-editorial text-prism px-6">✦</span>
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function KineticMarquee() {
  return (
    <section aria-label="What StockViz does" className="overflow-hidden py-14 sm:py-20">
      <p className="sr-only">Screen, backtest, simulate, replay, and keep score.</p>
      <Row />
      <div className="mt-2">
        <Row hollow reverse />
      </div>
    </section>
  );
}
