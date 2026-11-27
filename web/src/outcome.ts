/** What the person did with a card in this session. */
export type Outcome = { account: string } | "skipped";

/** Identifies a card. A card's first row is in no other card. */
export function cardKey(card: { rows: { import_id: string }[] }): string {
  return card.rows[0].import_id;
}
