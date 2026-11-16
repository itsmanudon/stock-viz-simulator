import { DocLink, DocSection, H3, P, Term, Terms } from "@/components/docs/docs-ui";

export function GlossaryFaq() {
  return (
    <>
      <DocSection title="Glossary">
        <Terms>
          <Term name="Close">
            The last price of a trading session, as stored. Everything here prices from it.
          </Term>
          <Term name="Session">One trading day on one exchange.</Term>
          <Term name="Ex-date">
            The first day a share trades without its next dividend; you need to hold before it to be
            paid.
          </Term>
          <Term name="Basis point">One hundredth of a percent (0.01%).</Term>
          <Term name="Strike">
            The price at which an option lets its holder buy (call) or sell (put).
          </Term>
          <Term name="Premium">The price of an option contract.</Term>
          <Term name="Intrinsic value">
            What an option would be worth if it expired now: how far it is in the money.
          </Term>
          <Term name="Implied volatility">
            The volatility that makes the model price match a market price.
          </Term>
          <Term name="Covered">A written option backed by the shares or cash it could need.</Term>
          <Term name="VaR / CVaR">
            A loss exceeded only on the worst days in history, and the average of those days.
          </Term>
          <Term name="TWR / XIRR">
            Growth with outside cash flows taken out, and the yearly rate matching your own cash
            flows.
          </Term>
          <Term name="Drawdown">A fall from a previous peak.</Term>
        </Terms>
      </DocSection>

      <DocSection title="Questions">
        <H3>My limit order filled at a different price than my limit.</H3>
        <P>
          Pending orders fill at the session&apos;s close, once the close has crossed your limit. A
          close below your buy limit fills at that lower close. See{" "}
          <DocLink href="/docs/orders">Orders</DocLink>.
        </P>
        <H3>Why is my order still pending?</H3>
        <P>
          It is checked once a day after the night&apos;s prices. It can only fill on a session that
          closed after you placed it, and it waits if that night&apos;s close is not stored.
        </P>
        <H3>Why was my market order refused as stale?</H3>
        <P>
          That stock&apos;s newest close is older than other stocks&apos; in the same currency, so
          its price refresh failed. It will trade again once its close is stored.
        </P>
        <H3>Why can&apos;t I write a call?</H3>
        <P>
          A call is only written covered: you need 100 shares per contract that are not already held
          back by a sell order or another call. Writing is for US-dollar accounts.
        </P>
        <H3>Why can&apos;t I close one leg of my spread?</H3>
        <P>
          The leg you bought covers the leg you wrote. Buy the written leg back first, or close the
          whole strategy.
        </P>
        <H3>Why don&apos;t option prices match my broker?</H3>
        <P>
          StockViz prices options with a model on the latest stored close, not from live quotes. See{" "}
          <DocLink href="/docs/options">Options</DocLink>.
        </P>
        <H3>Where is the live price?</H3>
        <P>
          There is none. The moving badge on a stock page is a simulation from the close. Every
          order uses stored closes.
        </P>
        <H3>Why does my account show no change yet?</H3>
        <P>The change needs at least two nights of recorded history.</P>
      </DocSection>
    </>
  );
}
