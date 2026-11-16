import { Callout, DocSection, Li, List, P, Shot, Term, Terms } from "@/components/docs/docs-ui";

export function Replay() {
  return (
    <>
      <DocSection title="What Replay is">
        <P>
          Replay puts you inside a past stretch of one stock&apos;s history without showing you what
          comes next. You see the chart up to the current bar, trade at its close, then step to the
          next bar. It is a separate practice account: nothing here touches your paper portfolio.
        </P>
        <Callout title="Blind by design">
          A replay session never loads anything from after its current bar: no later prices, no
          news, no live quote. The banner at the top says so.
        </Callout>
      </DocSection>

      <DocSection title="Using a session">
        <List ordered>
          <Li>Start a session: pick a US stock and a stored date range.</Li>
          <Li>Write your thesis and what would prove it wrong (the journal), if you want to.</Li>
          <Li>Buy or sell at the current bar&apos;s close; then advance one bar.</Li>
          <Li>On the last bar you can still trade; advancing from it finishes the replay.</Li>
        </List>
        <P>The journal&apos;s thesis locks at your first fill; your reflection stays editable.</P>
        <Shot
          src="/docs/replay.png"
          alt="A replay session after one buy, the chart ending at the current bar"
          caption="A replay session in January 2020 after one buy: the chart stops at the current bar."
        />
      </DocSection>

      <DocSection title="Forensics">
        <Terms>
          <Term name="Episodes">Each stretch from opening a position to closing it.</Term>
          <Term name="Worst and best excursion">
            How far the price went against you and in your favour while you held, from each
            day&apos;s low and high, measured from your average cost.
          </Term>
          <Term name="Against buy and hold">
            Your result against simply holding the stock over the same bars.
          </Term>
        </Terms>
      </DocSection>
    </>
  );
}
