import { ClosingCta } from "@/components/marketing/closing-cta";
import { Hero } from "@/components/marketing/hero";
import { LandingMotion } from "@/components/marketing/landing-motion";
import {
  FillSteps,
  LandingFaq,
  MovingToday,
  SessionTiles,
  StatementBand,
  StorySection,
} from "@/components/marketing/landing-sections";
import { ProofSection } from "@/components/marketing/proofs/proof-section";
import { WorkspacePalette } from "@/components/marketing/workspace-palette";
import { KineticMarquee } from "@/components/prism/kinetic-marquee";
import { TerrainSection } from "@/components/prism/terrain-section";

/**
 * Marketing home.
 *
 * Copy here is deliberately literal about what the product is: end-of-day
 * data, simulated fills, a rule-based checklist. Overselling it as live trading
 * or AI advice would misrepresent the engine (see the repo's agent guides).
 *
 * Section order follows the approved Aurora board (v5): hero with the pinned
 * card, movers, how a session works, "watch it work" (one animated row per
 * feature, motion batch 1), the scroll story, every fill shows its
 * work, the statement band, rankings, the workspace tiles, FAQ, closing call
 * to action. The old ticker strip, product tour and numbers band fold into
 * those sections. The workspace tiles became a working copy of the ⌘K
 * palette (`WorkspacePalette`), which still links every surface.
 */

export default function HomePage() {
  return (
    <div>
      <Hero />

      <TerrainSection />

      <LandingMotion>
        <MovingToday />
        <SessionTiles />
        <ProofSection />
        <StorySection />
        <FillSteps />
        <StatementBand />
        <KineticMarquee />

        <section aria-labelledby="surfaces-heading" className="border-y border-border-muted">
          <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
            <h2
              id="surfaces-heading"
              className="text-2xl font-medium tracking-[-0.02em] text-balance sm:text-3xl"
            >
              Everything in the workspace
            </h2>
            <p className="mt-3 max-w-2xl text-lg text-text-secondary text-pretty">
              Six surfaces, one jump-to box. Type to find one.
            </p>
            <WorkspacePalette />
          </div>
        </section>

        <LandingFaq />
      </LandingMotion>

      <ClosingCta />
    </div>
  );
}
