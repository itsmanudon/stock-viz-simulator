import { DocSection, H3, Li, List, P, Shot, Term, Terms } from "@/components/docs/docs-ui";

export function ScreenerCompare() {
  return (
    <>
      <DocSection title="Screener">
        <P>
          The screener filters every symbol on figures worked out after each night&apos;s prices.
          Filters and sort live in the address bar, so a screen can be bookmarked or shared; each
          applied filter shows as a chip you can remove.
        </P>
        <Terms>
          <Term name="Market, currency and sector">
            Country of listing, exchange, trading currency and sector.
          </Term>
          <Term name="Technicals">
            RSI, momentum over a window, the 52-week range, price against its 50- and 200-day
            averages, volatility and average volume.
          </Term>
          <Term name="Fundamentals">
            Highest price-to-earnings, lowest dividend yield, smallest market value (in US dollars),
            lowest return on equity, highest debt to equity.
          </Term>
        </Terms>
        <List>
          <Li>
            Results come 50 to a page; any change to a filter or the sort goes back to page one.
          </Li>
          <Li>Signed in, you can save a screen by name and open it again later.</Li>
          <Li>Tick up to six rows and press Compare selected to open them on one chart.</Li>
        </List>
        <Shot
          src="/docs/screener.png"
          alt="The screener with filters applied and a page of results"
          caption="The screener: filters as removable chips, results with their latest close and its date."
        />
      </DocSection>

      <DocSection title="Compare">
        <P>
          Compare draws several symbols on one chart, each rebased to 100 at the start of the
          window, over one month to five years. The series are cut to the days every symbol traded,
          so a holiday in one market never shows as a flat day in another.
        </P>
        <H3>What the figures mean</H3>
        <List>
          <Li>
            The return, volatility and maximum drawdown are for the closes in the window, not a risk
            model.
          </Li>
          <Li>
            Fundamentals sit side by side below, each company&apos;s market value in its own
            reporting currency.
          </Li>
        </List>
        <Shot
          src="/docs/compare.png"
          alt="Compare with three symbols rebased to 100 over one year"
          caption="Three symbols over a year, each rebased to 100 at the start, on the days all three traded."
        />
      </DocSection>
    </>
  );
}
