import type { components } from "./schema";

export type Card = components["schemas"]["Card"];
export type Choice = components["schemas"]["Choice"];
export type ReviewData = components["schemas"]["Review"];
export type Row = components["schemas"]["Row"];

async function checked(response: Response): Promise<Response> {
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response;
}

export async function fetchReview(): Promise<ReviewData> {
  return (await checked(await fetch("/api/review"))).json();
}

/** Saves an account per import-id. */
export async function saveAnswers(answers: Record<string, string>): Promise<void> {
  await checked(
    await fetch("/api/answers", {
      body: JSON.stringify({ answers }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    }),
  );
}
