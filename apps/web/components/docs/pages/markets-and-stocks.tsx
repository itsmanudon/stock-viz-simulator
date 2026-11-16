import {
  Callout,
  DocLink,
  DocSection,
  H3,
  Li,
  List,
  P,
  Term,
  Terms,
} from "@/components/docs/docs-ui";

export function MarketsAndStocks() {
  return (
    <>
      <DocSection title="Markets">
        <P>
          Markets lists every symbol with its latest stored close, the day&apos;s move and the date
          of that close. Symbols end on different days (markets close on different holidays), so
          each row carries its own date. A symbol whose refresh stalled shows no day&apos;s move
          rather than an old one.
        </P>
      </DocSection>

      <DocSection title="A stock's page">
        <Terms>
          <Term name="Chart">
            Daily candles with about twenty indicators to add (moving averages, Bollinger and
            Keltner bands, Supertrend, RSI, MACD, stochastics and more). Indicators are worked out
            with enough history before the visible window, so they do not change when you change the
            timeframe. RSI and MACD get their own panes.
          </Term>
          <Term name="Statistics">
            The 52-week range, volume and other figures for the latest close.
          </Term>
          <Term name="Financials">
            Key valuation multiples as of today, each with a reason when it cannot be worked out (a
            loss, no shares outstanding), the price-to-earnings history over five years, and the
            annual and quarterly statements. It says when figures are not point-in-time and when a
            company reports in a different currency from the one it trades in.
          </Term>
          <Term name="News">
            Headlines about the company from the Aegis news service, dated by the publisher (or by
            when they were collected), with how stocks reacted to similar news. See{" "}
            <DocLink href="/docs/news-reactions">News reactions</DocLink>.
          </Term>
          <Term name="Trade">The order ticket, two-step like the one on the Trade page.</Term>
        </Terms>
        <Callout title="The moving quote is simulated">
          The price badge that moves on a stock page is a random walk from the latest close, for the
          feel of a live ticker. It is not exchange data and orders never use it.
        </Callout>
        <H3>Watchlist</H3>
        <List>
          <Li>
            Add symbols by searching; each row shows the latest close, its date and a 30-day
            sparkline.
          </Li>
          <Li>News for everything on the list appears below it.</Li>
        </List>
      </DocSection>
    </>
  );
}
