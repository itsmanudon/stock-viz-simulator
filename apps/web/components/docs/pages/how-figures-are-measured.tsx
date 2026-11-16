import { Callout, DocLink, DocSection, Li, List, P, Term, Terms } from "@/components/docs/docs-ui";

export function HowFiguresAreMeasured() {
  return (
    <>
      <DocSection title="Prices">
        <Terms>
          <Term name="Daily closes">
            Stored every weekday night from a free daily data source (Yahoo Finance), adjusted for
            splits. Each bar is dated by its own market&apos;s calendar day.
          </Term>
          <Term name="Which session is complete">
            A market&apos;s session counts once 45 minutes have passed after its close, using that
            exchange&apos;s calendar of holidays and early closes.
          </Term>
          <Term name="Implausible prices">
            Bars with an impossible shape are rejected, and a jump of more than 60% is held for
            review instead of being used.
          </Term>
          <Term name="Exchange rates">
            Stored daily. A trade converts only at a rate no older than the session before its own;
            with no such rate it is refused rather than priced on a stale one.
          </Term>
        </Terms>
      </DocSection>

      <DocSection title="Account figures">
        <Terms>
          <Term name="Account value">
            Holdings at their latest closes, options at their model value, cash in every currency,
            in your display currency.
          </Term>
          <Term name="Annualised return">Calendar days over 365, and only beyond a year.</Term>
          <Term name="Sharpe ratio">
            From returns between snapshots one session apart, with a 5% yearly risk-free rate; it
            needs at least 20 such returns.
          </Term>
          <Term name="Maximum drawdown">
            The largest fall from a peak, from the opening value through every snapshot to today.
          </Term>
          <Term name="Returns, VaR and stress">
            See <DocLink href="/docs/returns-and-risk">Returns and risk</DocLink>.
          </Term>
        </Terms>
      </DocSection>

      <DocSection title="Options">
        <List>
          <Li>Black-Scholes (European exercise, no dividends), with a 5% yearly risk-free rate.</Li>
          <Li>
            Volatility from the latest stored option chain&apos;s nearest listed contract when one
            is within 45 days of the expiry and 10% of the strike and the chain is at most 5 days
            old; otherwise the 30-day historical volatility.
          </Li>
          <Li>
            Implied volatility in a stored chain is solved from the bid-ask midpoint (or the last
            trade) against that day&apos;s stored close.
          </Li>
          <Li>
            The chance of profit assumes a lognormal price at expiry. See{" "}
            <DocLink href="/docs/option-strategies">Option strategies</DocLink>.
          </Li>
        </List>
      </DocSection>

      <DocSection title="Company figures">
        <List>
          <Li>
            Valuation multiples use the last four quarters when they are reported, else the latest
            year, and say which. The price is converted into the reporting currency at that
            day&apos;s rate when the two differ.
          </Li>
          <Li>
            Figures from SEC filings are point-in-time (dated by filing). Figures from Yahoo Finance
            are dated by when they were fetched and are marked as not point-in-time.
          </Li>
          <Li>A figure that cannot be worked out is shown empty with the reason, never as zero.</Li>
        </List>
      </DocSection>

      <Callout title="The rule throughout">
        A figure states its method, its period and its basis next to it; when the data needed is
        missing, the page says so instead of estimating.
      </Callout>
    </>
  );
}
