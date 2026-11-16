import { Callout, DocSection, Li, List, P, Shot } from "@/components/docs/docs-ui";

export function Signals() {
  return (
    <>
      <DocSection title="What a signal is">
        <P>
          Signals score each symbol on seven checks after each night&apos;s prices: six on price and
          volume, and one on the sentiment of the week&apos;s news. Each check is a vote; the page
          shows every vote with its reason.
        </P>
        <List>
          <Li>
            A score of 4 or more is <strong>bullish</strong>; anything lower is neutral. There is no
            bearish model.
          </Li>
          <Li>
            When no news about a symbol was scored that week, the sentiment vote is left out and the
            score is out of 6, not 7. It is never counted against the stock.
          </Li>
          <Li>
            Each row is dated by the close behind it, and marked stale when that close is more than
            five days behind the newest one.
          </Li>
        </List>
        <Callout title="Not advice">
          Signals are a fixed set of rules applied the same way to every stock. They are not a
          prediction and not a recommendation to trade.
        </Callout>
        <Shot
          src="/docs/signals.png"
          alt="The signals list with each symbol's score and its votes"
          caption="Signals: each symbol's score out of its available votes, dated by the close behind it."
        />
      </DocSection>
    </>
  );
}
