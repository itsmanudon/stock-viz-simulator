/**
 * PRISM: every workspace navigation re-mounts this template, so the page
 * rises in with a short blur (`.page-enter` in globals.css). With reduced
 * motion the class does nothing and the page simply appears.
 */
export default function ProductTemplate({ children }: { children: React.ReactNode }) {
  return <div className="page-enter">{children}</div>;
}
