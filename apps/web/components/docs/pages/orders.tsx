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

export function Orders() {
  return (
    <>
      <DocSection title="Placing an order">
        <P>
          Orders are placed from the Trade page or from a stock&apos;s page. Every order is two
          steps: you open a review, check it, then place it. Nothing happens until you press the
          review&apos;s button.
        </P>
        <Terms>
          <Term name="Quantity">{"Shares to buy or sell."}</Term>
          <Term name="Reference price">
            {"For a market order, the latest stored close and its date: the price it fills at."}
          </Term>
          <Term name="Your limit or trigger">{"For a pending order, the price you set."}</Term>
          <Term name="Estimated value">{"Quantity times the price, in the stock's currency."}</Term>
          <Term name="Fees">{"None in the simulator."}</Term>
          <Term name="Buying power after">
            {
              "For a buy, what is left to spend once it fills (or the cash a pending buy holds back)."
            }
          </Term>
          <Term name="Risk limits">
            {"If you set limits in Settings, the review shows each one after this order."}
          </Term>
        </Terms>
        <Shot
          src="/docs/order-review.png"
          alt="The trade ticket with a market buy under review"
          caption="A market buy under review: the reference close and its date, the value, and buying power after."
        />
      </DocSection>

      <DocSection title="Order types">
        <Terms>
          <Term name="Market">
            {
              "Fills straight away at the latest stored close. It is refused if this stock's newest close is older than other stocks' in the same currency (its price refresh failed), so it never fills at a stale price."
            }
          </Term>
          <Term name="Limit">
            {
              "A buy fills when a close is at or below your limit; a sell when a close is at or above it."
            }
          </Term>
          <Term name="Stop-loss">
            {"Sell only. Fills when a close is at or below your trigger."}
          </Term>
          <Term name="Take-profit">
            {"Sell only. Fills when a close is at or above your trigger."}
          </Term>
        </Terms>
        <H3>How pending orders fill</H3>
        <List>
          <Li>
            {
              "They are checked once a day, after the night's prices arrive, against that day's close."
            }
          </Li>
          <Li>
            They fill <strong>at the close</strong>, not at your limit or trigger price.
          </Li>
          <Li>{"Only a session that closed after you placed the order can fill it."}</Li>
          <Li>
            {
              "A pending buy holds back its cash, and a pending sell its shares, until it fills, is cancelled or expires."
            }
          </Li>
          <Li>
            {
              "If it triggers but cannot fill (say the cash is no longer there), it is cancelled with the reason."
            }
          </Li>
          <Li>{"An order not filled within 30 days expires and releases what it held back."}</Li>
        </List>
      </DocSection>

      <DocSection title="No double orders">
        <P>
          Each review carries its own key. Pressing the button twice, or a slow connection resending
          it, places the order once.
        </P>
      </DocSection>

      <DocSection title="Risk limits">
        <P>
          In Settings you can cap how much of the account one order, one holding, one sector or one
          foreign currency may take, and an estimated one-day loss (95% VaR). They are off until you
          set them. A market buy over a limit is refused; a pending buy that would break one when it
          fills is cancelled with the reason. Sells are never stopped by a limit.
        </P>
        <Callout title="Where to see the result">
          Filled orders appear under Trade history and the Portfolio; pending and past orders under
          Orders, with a tab for each status. Filled pending orders also send a notification.
          Options have their own rules: see <DocLink href="/docs/options">Options</DocLink>.
        </Callout>
      </DocSection>
    </>
  );
}
