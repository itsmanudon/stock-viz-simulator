import { Callout, DocSection, H3, Li, List, P, Term, Terms } from "@/components/docs/docs-ui";

export function Alerts() {
  return (
    <>
      <DocSection title="Kinds of alert">
        <Terms>
          <Term name="Price level">A close above or below a price you set.</Term>
          <Term name="Daily move">
            A session&apos;s close moving more than a percentage either way.
          </Term>
          <Term name="Technical">
            An indicator above or below a value, or above or below another figure (for example the
            close crossing its 200-day average).
          </Term>
          <Term name="News">
            A new headline about the stock with the sentiment or event type you chose.
          </Term>
          <Term name="Portfolio">
            Your account falling a percentage from its peak, one holding growing past a share of the
            account, or the account moving more than a percentage in a day.
          </Term>
        </Terms>
        <P>
          The form shows the latest close and its date, how far the target is, and the rule in words
          before you save it.
        </P>
      </DocSection>

      <DocSection title="When an alert fires">
        <List>
          <Li>
            Alerts are judged once per trading session, after the night&apos;s prices arrive, not
            during the day.
          </Li>
          <Li>
            A rule fires when its condition <strong>becomes</strong> true: a close that crosses your
            level, not every close beyond it. A new rule first notes where things stand.
          </Li>
          <Li>
            <strong>Once</strong> rules stop after firing; <strong>every cross</strong> rules fire
            again on later crossings, after a cooling-off of the sessions you choose.
          </Li>
          <Li>A daily-move rule fires on each session that moves enough.</Li>
          <Li>A news rule fires once for each matching headline that arrives after you set it.</Li>
        </List>
        <H3>Managing alerts</H3>
        <P>
          Pause and resume, re-arm a fired rule, dismiss or delete it. Each rule keeps a history of
          when it fired, the close it saw and the threshold.
        </P>
        <Callout title="Not real-time monitoring">
          An alert can only fire after a session&apos;s close is stored. It will not catch a move
          during the day.
        </Callout>
      </DocSection>

      <DocSection title="Notifications">
        <P>
          The bell in the top bar shows how many notifications are unread and the newest five; it
          checks once a minute while the page is open. The Notifications page lists them all by
          kind, with mark read and mark all read. They are in the app only, not email.
        </P>
        <Terms>
          <Term name="Alerts">Each alert that fired.</Term>
          <Term name="Orders">Pending orders filled, cancelled (with the reason) or expired.</Term>
          <Term name="Dividends">Dividends credited to you.</Term>
          <Term name="Corporate actions">
            A split that adjusted your holdings, orders or options.
          </Term>
          <Term name="Options">Contracts and strategies settled at expiry, with the amounts.</Term>
        </Terms>
      </DocSection>
    </>
  );
}
