import { Callout, DocSection, Li, List, P, Term, Terms } from "@/components/docs/docs-ui";

export function NewsReactions() {
  return (
    <>
      <DocSection title="Where the news comes from">
        <P>
          News comes from the Aegis news service. StockViz stores which documents are about which
          companies, their sentiment and event type, and a link to the source; it does not store the
          articles&apos; text. A headline is dated by its publisher, or by when it was collected
          when the source gives no date.
        </P>
      </DocSection>

      <DocSection title="News reactions (event studies)">
        <P>
          News reactions asks how stocks moved around news of one kind: pick the symbols, a
          sentiment and an event type. For each matching headline:
        </P>
        <List>
          <Li>
            The event day is the first trading session that closed after the news was available.
          </Li>
          <Li>
            The abnormal return each day is the stock&apos;s return less its market index&apos;s
            (the S&amp;P 500 for US stocks, the NIFTY 50 for Indian ones).
          </Li>
          <Li>These add up across a window into the cumulative abnormal return.</Li>
        </List>
        <Terms>
          <Term name="Windows">
            The event day and the next, five days after, five days before, and twenty days after.
          </Term>
          <Term name="Averages">
            The mean, its standard error and a t-statistic across events, shown only with at least
            10 events.
          </Term>
          <Term name="Excluded">
            Events without the full window of prices are counted but not used; overlapping windows
            are counted.
          </Term>
        </Terms>
        <Callout title="Association, not cause">
          A pattern here says stocks tended to move after news like this. It does not say the news
          moved them.
        </Callout>
      </DocSection>
    </>
  );
}
