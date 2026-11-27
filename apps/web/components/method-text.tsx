import { methodParts } from "@/lib/method-text";

/** An API method note, with a Markdown-style list shown as a real list. */
export function MethodText({ note, className }: { note: string; className?: string }) {
  const { lead, items } = methodParts(note);
  return (
    <div className={className ?? "text-2xs leading-5 text-text-tertiary"}>
      {lead ? <p>{lead}</p> : null}
      {items.length ? (
        <ul className="mt-1.5 space-y-1">
          {items.map((item) => (
            <li key={`${item.label}-${item.text.slice(0, 24)}`} className="flex gap-2">
              <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-text-tertiary" />
              <span>
                {item.label ? (
                  <span className="font-medium text-text-secondary">
                    {item.label}
                    {item.joined ? " " : ": "}
                  </span>
                ) : null}
                {item.text}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
