export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="container mx-auto flex h-16 items-center justify-between px-6 text-sm text-muted-foreground">
        <span>© {new Date().getFullYear()} StockViz</span>
        <span>v2.0.0-alpha</span>
      </div>
    </footer>
  );
}
