import {
  Callout,
  DocLink,
  DocSection,
  Li,
  List,
  P,
  Shot,
  Term,
  Terms,
} from "@/components/docs/docs-ui";

export function Portfolio() {
  return (
    <>
      <DocSection title="The headline figures">
        <Terms>
          <Term name="Account value">
            Cash in every currency plus holdings and open options at the latest closes, converted
            into your display currency.
          </Term>
          <Term name="Available cash">
            Cash less what pending buys, cash-secured puts and option strategies hold back.
          </Term>
          <Term name="Unrealized P&L">
            Gains and losses on what you still hold: stocks and open options together.
          </Term>
          <Term name="Realized P&L">
            Everything closed so far: stock sales and options closed, assigned or expired.
          </Term>
        </Terms>
        <Callout title="When a price is missing">
          If a holding has no stored close, an option cannot be priced, or a currency has no
          exchange rate, the portfolio says so at the top instead of quietly counting it as zero.
          The nightly snapshot skips that night rather than record a false loss.
        </Callout>
        <Shot
          src="/docs/portfolio.png"
          alt="The portfolio page: account value, figures and the holdings"
          caption="A new account's portfolio: its value (the chart appears after two nights of history), the headline figures, then the tabs."
        />
      </DocSection>

      <DocSection title="The tabs">
        <Terms>
          <Term name="Positions">
            Each holding with its average cost, value, gain and how much is held back by orders or
            covered calls.
          </Term>
          <Term name="Options">
            The options book&apos;s Greeks, contracts by expiry, open strategies and every contract.
            See <DocLink href="/docs/options">Options</DocLink>.
          </Term>
          <Term name="Orders">Pending orders, cancellable from here.</Term>
          <Term name="Income">Dividends credited, and those expected from what you hold.</Term>
          <Term name="Journal">A calendar of realized profit and loss, day by day.</Term>
          <Term name="News">Headlines about your holdings.</Term>
          <Term name="Analytics">
            Returns, exposure, risk, stress tests, rebalancing and goals. See{" "}
            <DocLink href="/docs/returns-and-risk">Returns and risk</DocLink>.
          </Term>
        </Terms>
      </DocSection>

      <DocSection title="Daily history">
        <P>
          Each night StockViz records your account&apos;s value, dated by the session its prices
          come from. That history draws the value chart and the returns. Returns need at least two
          days of it.
        </P>
      </DocSection>
    </>
  );
}
