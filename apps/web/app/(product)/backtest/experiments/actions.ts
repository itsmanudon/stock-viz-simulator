"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { createExperiment } from "@/lib/api/experiments";
import { UnauthenticatedError } from "@/lib/api/server";

export type ExperimentFormState = { error?: string; id?: number };

const Schema = z.object({
  name: z.string().trim().min(1, "Name the experiment").max(120),
  hypothesis: z.string().trim().max(4000).optional(),
});

/** A7.6 (M7.7): a named experiment with its hypothesis, written before the runs. */
export async function createExperimentAction(
  _prev: ExperimentFormState,
  formData: FormData,
): Promise<ExperimentFormState> {
  const parsed = Schema.safeParse({
    name: formData.get("name"),
    hypothesis: formData.get("hypothesis") || undefined,
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  try {
    const row = await createExperiment(parsed.data.name, parsed.data.hypothesis ?? null);
    revalidatePath("/backtest/experiments");
    return { id: row.id };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to keep experiments." };
    return { error: "The experiment could not be saved." };
  }
}
