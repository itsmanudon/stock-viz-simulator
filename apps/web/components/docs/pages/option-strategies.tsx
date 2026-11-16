import { Callout, DocSection, H3, Li, List, P, Shot, Term, Terms } from "@/components/docs/docs-ui";

export function OptionStrategies() {
  return (
    <>
      <DocSection title="Templates">
        <P>
          A strategy is several option legs opened together from a template. Pick one in the
          strategy builder on the Trade page; strikes start around today&apos;s close and can be
          changed.
        </P>
        <Terms>
          <Term name="Covered call">{"Write a call on shares you hold."}</Term>
          <Term name="Cash-secured put">{"Write a put with its strike value held in cash."}</Term>
          <Term name="Protective put">{"Buy a put on shares you hold."}</Term>
          <Term name="Bull call spread">
            {"Buy a call, write a higher one: gains as the stock rises, capped."}
          </Term>
          <Term name="Bear put spread">
            {"Buy a put, write a lower one: gains as the stock falls, capped."}
          </Term>
          <Term name="Bull put spread">
            {"Write a put, buy a lower one: a credit kept above the higher strike."}
          </Term>
          <Term name="Bear call spread">
            {"Write a call, buy a higher one: a credit kept below the lower strike."}
          </Term>
          <Term name="Iron condor">
            {"A bull put and a bear call spread: a credit kept between the inner strikes."}
          </Term>
          <Term name="Straddle">
            {"Buy a call and a put at one strike: gains on a large move either way."}
          </Term>
          <Term name="Strangle">
            {"Buy a put and a call at two strikes: cheaper, needs a larger move."}
          </Term>
          <Term name="Calendar spread">
            {"Write a near expiry, buy a far one, same strike: gains if the stock stays near it."}
          </Term>
        </Terms>
      </DocSection>

      <DocSection title="Reading the builder">
        <Shot
          src="/docs/strategy-builder.png"
          alt="The strategy builder with a bull call spread, its legs, figures and payoff chart"
          caption="A bull call spread in the builder: the legs, what it costs, the most it can lose and gain, the breakeven, and the payoff."
        />
        <Terms>
          <Term name="Net premium">{"Paid for a debit strategy, received for a credit one."}</Term>
          <Term name="Cash held back">
            {
              "What the legs could cost at expiry, beyond the premiums. A credit spread holds back its width; an iron condor its wider side."
            }
          </Term>
          <Term name="Most it can lose / gain">
            {"At expiry, worked exactly from the legs. Unlimited gains say so."}
          </Term>
          <Term name="Breakevens">
            {"Stock prices at expiry where the strategy neither gains nor loses."}
          </Term>
          <Term name="Chance of profit">
            {
              "A model figure: the share of outcomes above zero if the price at expiry follows a lognormal distribution with the volatility used. It inherits every assumption of the model."
            }
          </Term>
          <Term name="Payoff chart">
            {
              "Profit or loss across prices: solid at the first expiry, dashed today. Today's close and the breakevens are marked."
            }
          </Term>
        </Terms>
        <P>
          The volatility smile below the builder shows the implied volatility of the latest stored
          chain by strike, one line per expiry, or says when none is stored.
        </P>
      </DocSection>

      <DocSection title="Opening and closing">
        <List>
          <Li>
            {
              "Review the strategy, then place it. Every leg opens at the quoted prices, or none does."
            }
          </Li>
          <Li>
            {
              "No naked options: each written leg is covered by shares, by cash, or by a bought leg of the same strategy. Anything with an unlimited loss is refused."
            }
          </Li>
          <Li>
            {
              "If you set a single-order risk limit, it is checked against the most the strategy can lose."
            }
          </Li>
          <Li>
            {
              "Close a strategy from Portfolio, Options: every open leg at its model value, as one payment."
            }
          </Li>
          <Li>
            {
              "A bought leg that covers a written one cannot be closed on its own; buy the written leg back first."
            }
          </Li>
        </List>
      </DocSection>

      <DocSection title="At expiry">
        <P>
          A strategy settles as one, in cash, from the expiry session&apos;s close: each leg is
          worth its intrinsic value, bought legs receive it, written legs pay it, and the net moves
          once. It never needs more than the cash it held back, and no shares change hands.
        </P>
        <H3>Calendars</H3>
        <P>
          The near leg settles first. Out of the money, it expires and the far leg stays open as an
          ordinary bought option. In the money, the far leg is sold at its model value to pay what
          the near leg owes, closing both.
        </P>
        <Callout title="A worked example">
          A bull call spread on 100/110 calls, bought for 6.00 and written for 2.00, costs 400. At a
          115 close it pays 1,000 (the most it can gain, 600 after the cost); at 105 it pays 500
          (100 after the cost); at 95 nothing, losing the 400.
        </Callout>
      </DocSection>
    </>
  );
}
