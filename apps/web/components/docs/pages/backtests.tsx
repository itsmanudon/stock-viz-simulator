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

export function Backtests() {
  return (
    <>
      <DocSection title="Running a backtest">
        <P>
          A backtest replays a rule over stored history for one symbol. Pick the symbol, the dates,
          the starting cash and a strategy:
        </P>
        <Terms>
          <Term name="Moving-average crossover">
            Buy when the short average crosses above the long one, sell when it crosses back.
          </Term>
          <Term name="RSI threshold">
            Buy when the 14-day RSI falls below a level, sell when it rises above another.
          </Term>
        </Terms>
        <Shot
          src="/docs/backtest.png"
          alt="A backtest equity curve, with the buy-and-hold return"
          caption="A default run's equity curve, with buying and holding's return over the same window beside it."
        />
      </DocSection>

      <DocSection title="How fills and costs work">
        <Terms>
          <Term name="Fill rule">
            By default a signal on one day fills at the next day&apos;s open (it could not have
            traded at a close it had just seen). You can choose the next close instead.
          </Term>
          <Term name="All in, all out">
            Each buy uses the whole account; each sell closes the whole position.
          </Term>
          <Term name="Spread and slippage">
            Optional costs, in basis points, that move each fill against you.
          </Term>
          <Term name="Fees">
            Automatic by default: Indian symbols pay their exchange&apos;s equity delivery charges
            (securities transaction tax, exchange charges, stamp duty, GST, the DP charge), other
            markets none. You can choose none, the US schedule (SEC and FINRA fees on sales) or a
            delivery schedule. Each fill pays the rates in force on its date; the results list every
            component with its source under Costs. See{" "}
            <DocLink href="/docs/costs">Costs and fees</DocLink>.
          </Term>
          <Term name="Liquidity cap">
            A buy fills at most 10% (you can change it) of the 20-day average traded value; the rest
            is not filled and the trade says &quot;partial&quot;. Price bands are not checked yet.
          </Term>
          <Term name="Total return">
            When chosen, dividends are paid on shares held into each ex-date, for the strategy and
            the buy-and-hold line alike.
          </Term>
          <Term name="Warm-up">
            Indicators read enough history before your start date to be ready on day one, but
            nothing trades before it.
          </Term>
        </Terms>
        <P>
          Results are in the symbol&apos;s currency, and the page states the price basis and every
          choice above.
        </P>
      </DocSection>

      <DocSection title="Saving and checking runs">
        <List>
          <Li>
            Signed in, <strong>Save run</strong> keeps the request, the code version and a
            fingerprint of every price it read.
          </Li>
          <Li>
            <strong>Rerun</strong> says whether the result is identical, different (same data,
            changed code; the differing figures are listed) or that the data changed.
          </Li>
          <Li>
            <strong>Walk-forward</strong> picks the best setting on three years, scores it on the
            next year, and steps forward a year at a time; the stitched out-of-sample curve is the
            result. <strong>Sweep settings</strong> ranks every setting in a grid (up to 50) and
            says how many were tried.
          </Li>
        </List>
        <Callout title="Read a sweep with care">
          The best of fifty settings will look better than any one setting would have done in
          advance. Walk-forward exists to check that.
        </Callout>
        <H3>What a backtest is not</H3>
        <P>
          It does not model the order book, partial fills or intraday prices. It works on daily
          bars.
        </P>
      </DocSection>
    </>
  );
}
