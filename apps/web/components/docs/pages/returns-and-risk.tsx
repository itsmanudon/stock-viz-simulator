import {
  Callout,
  DocLink,
  DocSection,
  H3,
  Li,
  List,
  P,
  Shot,
  Term,
  Terms,
} from "@/components/docs/docs-ui";

export function ReturnsAndRisk() {
  return (
    <>
      <DocSection title="Returns">
        <Terms>
          <Term name="Time-weighted return">
            The account&apos;s growth over 1 month, 3 months, the year so far, 1 year and since it
            opened, chained day by day. Annualised only beyond a year.
          </Term>
          <Term name="Money-weighted return (XIRR)">
            For the account and each holding: the yearly rate that matches its own buys, sells,
            dividends and today&apos;s value. Not shown under 30 days, where a yearly rate would be
            noise.
          </Term>
        </Terms>
      </DocSection>

      <DocSection title="Exposure and currency effects">
        <List>
          <Li>
            Weights of the account by sector, country and currency. Cash counts under its currency;
            options are listed beside the weights at their delta (the stock they move like), not
            added into them.
          </Li>
          <Li>
            For each holding, the gain since you bought splits into the <strong>price</strong> move,
            the <strong>currency</strong> move and a small <strong>cross</strong> term, which add up
            exactly; dividends are counted as income.
          </Li>
        </List>
      </DocSection>

      <DocSection title="Value at risk">
        <P>
          StockViz replays today&apos;s holdings over the last 500 trading days: each day&apos;s
          return for each holding, in your account&apos;s currency, including its currency&apos;s
          move. Options are repriced in full at each day&apos;s moved price.
        </P>
        <Terms>
          <Term name="VaR">
            The loss exceeded on only 5% (or 1%) of those days, over one day or ten (real
            overlapping ten-day stretches, not a scaled one-day figure).
          </Term>
          <Term name="CVaR">The average loss on those worst days.</Term>
          <Term name="Proxies">
            A holding without enough history of its own uses its market index for the missing days,
            and the panel lists which.
          </Term>
        </Terms>
        <P>It needs at least 250 trading days; with fewer it says so instead of guessing.</P>
        <Shot
          src="/docs/risk-panel.png"
          alt="The risk panel: value at risk and expected shortfall with their method"
          caption="The risk panel states its rule, its window, how many days it used and what was proxied."
        />
        <H3>One year ahead</H3>
        <P>
          10,000 possible years are drawn by resampling past daily returns in short blocks (so calm
          and stormy runs stay together). The panel shows the spread of outcomes and, if you enter a
          goal, the share of those years that reach it, in words like &quot;about 1 in 4&quot;. It
          is a resampling of the past, not a forecast.
        </P>
      </DocSection>

      <DocSection title="Stress tests">
        <Terms>
          <Term name="Past crises">
            Today&apos;s holdings put through the 2008 crisis, the 2020 COVID crash, the 2022 rate
            shock and the 2013 taper tantrum, each with that period&apos;s currency moves. A holding
            without prices then moves with its index, scaled by its beta, and is marked.
          </Term>
          <Term name="Fixed shocks">
            US stocks or Indian stocks down 10% or 20%, the rupee 10% weaker, and all of these
            together.
          </Term>
        </Terms>
        <P>Each shows the change in value, the value after, and the holdings that drive it.</P>
      </DocSection>

      <DocSection title="Rebalancing and limits">
        <List>
          <Li>
            Rebalancing is a preview: set target weights and it lists the whole-share orders that
            would reach them, each opening the normal ticket. Nothing is placed for you.
          </Li>
          <Li>
            Risk limits are set in Settings and checked when you trade: see{" "}
            <DocLink href="/docs/orders">Orders</DocLink>.
          </Li>
        </List>
        <Callout title="Every figure says how it is measured">
          Each return and risk figure carries its method, period and basis beside it on the page.
        </Callout>
      </DocSection>
    </>
  );
}
