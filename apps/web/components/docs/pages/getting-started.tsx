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

export function GettingStarted() {
  return (
    <>
      <DocSection title="What StockViz is">
        <P>
          StockViz is a paper-trading and research workspace. You trade with money that is not real,
          against prices that are stored, not streamed. It covers US and Indian stocks, with options
          on US stocks, and keeps every figure honest about where it comes from.
        </P>
        <Callout title="End of day and simulated">
          Every price is a stored daily close. The prices are refreshed every weekday night at 22:00
          UTC, after the US market closes. Orders fill at the latest stored close, not at a live
          quote. The price ticker on a stock page is a simulation drawn from that close, not
          exchange data. The top bar of the app shows the date of the newest stored close.
        </Callout>
      </DocSection>

      <DocSection title="Your paper account">
        <List>
          <Li>
            Sign up with an email and password, or with Google where it is enabled. Your account
            starts with <strong>$100,000</strong> of paper cash in US dollars.
          </Li>
          <Li>
            While the account is fresh (no trades, orders or options yet), Settings can restart it
            in Indian rupees with <strong>₹1 crore</strong>, or back in dollars. After the first
            trade the account currency is fixed.
          </Li>
          <Li>
            Buying a stock in another currency spends any cash you already hold in that currency
            first, then converts the rest at the latest stored exchange rate. Selling keeps the
            proceeds in the stock&apos;s own currency.
          </Li>
          <Li>
            Dividends are credited to you automatically for shares held before the ex-date, and
            stock splits adjust your holdings, orders and options once, overnight.
          </Li>
        </List>
        <Shot
          src="/docs/dashboard.png"
          alt="The signed-in home page: account value, movers, orders, watchlist and alerts"
          caption="Home, after signing in: the account's value and change, then orders, watchlist, alerts, movers and allocation."
        />
      </DocSection>

      <DocSection title="Where things are">
        <Terms>
          <Term name="Home">{"Your account at a glance."}</Term>
          <Term name="Markets">
            {"Every symbol with its latest close, the day's move and its date."}
          </Term>
          <Term name="Research">
            Screener, compare, signals, backtests, news reactions and replay. See the Research pages
            (coming next).
          </Term>
          <Term name="Trade">
            The order ticket, the option ticket and the strategy builder. See{" "}
            <DocLink href="/docs/orders">Orders</DocLink> and{" "}
            <DocLink href="/docs/options">Options</DocLink>.
          </Term>
          <Term name="Portfolio">
            {"Positions, options, orders, income, journal, news and analytics."}
          </Term>
          <Term name="Alerts">
            {"Price, technical, news and portfolio rules, judged after each night."}
          </Term>
          <Term name="Settings">
            {
              "Display currency, account currency, risk limits, your public name on the leaderboard."
            }
          </Term>
          <Term name="Status">
            {"When each nightly job last ran, and the newest close for each market."}
          </Term>
        </Terms>
      </DocSection>

      <DocSection title="Things that are not here">
        <List>
          <Li>{"No real money, and no connection to a broker."}</Li>
          <Li>{"No intraday or live prices: everything works off daily closes."}</Li>
          <Li>{"No crypto, and no naked (uncovered) options."}</Li>
        </List>
      </DocSection>
    </>
  );
}
