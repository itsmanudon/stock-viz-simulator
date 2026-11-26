import { Callout, DocLink, DocSection, H3, Li, List, P } from "@/components/docs/docs-ui";

/**
 * The Checklist (A2.4), which replaced the 7-vote Signals. Formulas here
 * match `apps/api/src/stockviz/services/checklist/dimensions.py`; the page
 * itself always shows the stored canonical text of the version that judged.
 */
export function Checklist() {
  return (
    <>
      <DocSection title="What the checklist is">
        <P>
          After each night&apos;s prices, every tracked symbol is checked against six dimensions on
          its latest stored session. Each dimension is a short list of conditions written in the
          rule language, with a published source, and the page shows the exact formula that judged
          it. The summary is a count, such as &quot;4 of 6 met&quot;.
        </P>
        <List>
          <Li>
            A dimension is <strong>met</strong> when every one of its conditions is met.
          </Li>
          <Li>
            It is <strong>unknown</strong> when an input is missing (no index close, no
            fundamentals, no delivery data, too little history) and no condition failed. Unknown is
            never counted as met or as not met, and the page names what was missing.
          </Li>
          <Li>
            Otherwise it is <strong>not met</strong>, and the page lists the conditions that failed.
          </Li>
        </List>
        <P>
          A symbol without a bar on its venue&apos;s latest session is unknown on every dimension,
          never judged on an older close. See <DocLink href="/checklist">the Checklist</DocLink>.
        </P>
      </DocSection>
      <DocSection title="The six dimensions">
        <H3>Trend</H3>
        <P>
          The close is above its 200-day average (<code>close &gt; sma(close, 200)</code>), and the
          50-day average is above the 200-day (<code>sma(close, 50) &gt; sma(close, 200)</code>).
        </P>
        <H3>Momentum / relative strength</H3>
        <P>
          The 6-month return beat the venue&apos;s index (<code>rs(126) &gt; 0</code>, against ^GSPC
          or ^NSEI), and the 14-day RSI is between 50 and 70.
        </P>
        <H3>Volume / delivery</H3>
        <P>
          Volume is above its 50-day average. On NSE and BSE listings, more than half of the traded
          shares were taken for delivery (<code>delivery_pct &gt; 50</code>); US exchanges publish
          no delivery figure, so US listings are judged on volume alone. Until NSE delivery files
          are loaded, the delivery condition is unknown.
        </P>
        <H3>Market regime</H3>
        <P>
          The venue&apos;s index closed above its own 200-day average (
          <code>index_close &gt; sma(index_close, 200)</code>).
        </P>
        <H3>Quality</H3>
        <P>
          Return on equity above 15% and debt to equity below 1, as known on the date. Fundamentals
          are point in time only from when StockViz began collecting them.
        </P>
        <H3>Risk / reward</H3>
        <P>
          The close is within 25% of its 52-week high, and the 14-day average true range is under 4%
          of the close.
        </P>
      </DocSection>
      <DocSection title="Evidence grades">
        <P>
          Once a week each dimension&apos;s formula is graded on the stored history: every time it
          turned true after being false, the return over the next 20 sessions, after a round trip of
          the venue&apos;s fees, is compared with what holding the whole universe returned over the
          same 20 sessions. Events closer than 20 sessions on one symbol count once.
        </P>
        <List>
          <Li>
            <strong>A</strong>: t-statistic at least 3 and mean excess return at least 1%.
          </Li>
          <Li>
            <strong>B</strong>: t at least 2. <strong>C</strong>: t at least 1. <strong>D</strong>:
            otherwise.
          </Li>
          <Li>Under 30 events the formula is not graded.</Li>
        </List>
        <P>
          Each grade shows its sample: the number of events and symbols, the window and the horizon.
          Grades are measured on today&apos;s pinned symbol list, so companies that were delisted
          are missing: the sample is survivorship-biased and a grade can look better than it would
          have at the time. Every grade says so.
        </P>
        <Callout title="Not advice">
          The checklist counts published conditions and reports how they behaved in the past. It is
          not a prediction and not a recommendation to buy, sell or hold anything.
        </Callout>
      </DocSection>
    </>
  );
}
