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

export function Options() {
  return (
    <>
      <DocSection title="What you can trade">
        <List>
          <Li>{"Calls and puts on US stocks (not on indices, and not yet on Indian stocks)."}</Li>
          <Li>
            {"One contract covers 100 shares. Options are European: they settle at expiry only."}
          </Li>
          <Li>
            <strong>Buy to open</strong> a call or put, or <strong>write covered</strong>: a covered
            call on shares you hold, or a cash-secured put backed by cash. Writing is available on
            US-dollar accounts.
          </Li>
          <Li>
            Several legs at once (spreads, iron condors and more) come from the{" "}
            <DocLink href="/docs/option-strategies">strategy builder</DocLink>.
          </Li>
        </List>
      </DocSection>

      <DocSection title="How a contract is priced">
        <P>
          There is no live options market here, so every price comes from the Black-Scholes model
          using the stock&apos;s latest stored close, the strike, the time to expiry, a 5% yearly
          risk-free rate and a volatility. The volatility is:
        </P>
        <List>
          <Li>
            {
              "the implied volatility of the nearest listed contract in the latest option chain StockViz stored (the chains are saved every night from a free source), when one is close enough in expiry and strike;"
            }
          </Li>
          <Li>
            {
              "otherwise the stock's 30-day historical volatility. That needs at least 20 daily closes; with fewer, the contract is not priced at all."
            }
          </Li>
        </List>
        <P>
          The quote always says which one it used. No contract opens for less than 1 cent a share;
          the quote says when that minimum applies.
        </P>
        <Shot
          src="/docs/option-ticket.png"
          alt="The option ticket with a call quoted, its Greeks below"
          caption="The option ticket: spot and its date, volatility and its source, the rate, the premium, and the Greeks."
        />
        <H3>The Greeks</H3>
        <Terms>
          <Term name="Delta">
            {"How many shares one contract moves like. 0.5 means about 50 shares."}
          </Term>
          <Term name="Gamma">{"How much delta changes for a $1 move in the stock."}</Term>
          <Term name="Theta">{"Value lost each calendar day, all else equal."}</Term>
          <Term name="Vega">{"Change in value for 1 percentage point of volatility."}</Term>
          <Term name="Rho">{"Change in value for 1 percentage point of the interest rate."}</Term>
        </Terms>
        <P>
          On the portfolio, Greeks are the position&apos;s: a written contract&apos;s are the
          contract&apos;s with the sign flipped.
        </P>
        <H3>Checking a premium you saw elsewhere</H3>
        <P>
          Under the quote, &quot;Saw a different premium?&quot; solves the volatility a price
          implies, beside the one StockViz uses. It changes nothing: the buy is still charged at the
          quote.
        </P>
      </DocSection>

      <DocSection title="Writing covered options">
        <Terms>
          <Term name="Covered call">
            {
              "You need 100 shares per contract that are not already held back. They are held back until the call is bought back or expires: you cannot sell them meanwhile."
            }
          </Term>
          <Term name="Cash-secured put">
            {
              "Its full strike value is held back in cash. The premium you receive is in your cash and can be spent; the strike value cannot."
            }
          </Term>
        </Terms>
        <P>
          The premium is credited when you write. The quote shows what is held back, the most the
          position can lose and gain, and its breakeven at expiry.
        </P>
      </DocSection>

      <DocSection title="Closing before expiry">
        <P>
          From Portfolio, Options: a bought contract is sold back, a written one bought back, at its
          current model value. It is two steps: the first click states the amount. A contract past
          its expiry date waits for the nightly settlement instead.
        </P>
      </DocSection>

      <DocSection title="At expiry">
        <P>
          The night after the expiry session&apos;s close is stored, each contract settles from that
          close. Until the close is stored, it waits.
        </P>
        <Terms>
          <Term name="Bought call, in the money">
            {
              "Exercised: the shares are bought at the strike. Without the cash, the profit is paid in cash instead."
            }
          </Term>
          <Term name="Bought put, in the money">
            {
              "Exercised: shares you hold are sold at the strike. Without them, the profit is paid in cash."
            }
          </Term>
          <Term name="Bought, out of the money">
            {"Expires worthless; the premium was the cost."}
          </Term>
          <Term name="Covered call, in the money">
            {"Assigned: your held-back shares are sold at the strike."}
          </Term>
          <Term name="Cash-secured put, in the money">
            {"Assigned: you buy the shares at the strike with the held-back cash."}
          </Term>
          <Term name="Written, out of the money">
            {"Expires; you keep the premium and the cover is released."}
          </Term>
        </Terms>
        <Shot
          src="/docs/options-book.png"
          alt="Options Greeks on the portfolio: dollar delta, theta, vega and rho, by underlying"
          caption="Portfolio, Options: the book's Greeks in money. Below it, contracts by expiry with what today's close would do."
        />
        <Callout title="What you see">
          Each settlement sends a notification with the amount. Portfolio, Options lists your
          contracts by expiry with what today&apos;s close would do on that day, and the book&apos;s
          Greeks in money.
        </Callout>
      </DocSection>
    </>
  );
}
