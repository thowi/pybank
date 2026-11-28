import { Button, Paper, Stack, Text, Title } from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { Spotlight, type SpotlightActionData } from "@mantine/spotlight";
import { useMutation } from "@tanstack/react-query";
import { extendedMatch, Fzf } from "fzf";
import { useState } from "react";
import { addCategory, type Card, type ReviewData, saveAnswers, saveNote } from "./api";
import { CurrentCard } from "./components/CurrentCard";
import { NoteDialog } from "./components/NoteDialog";
import { ProgressHeader } from "./components/ProgressHeader";
import { SureList } from "./components/SureList";
import { Upcoming } from "./components/Upcoming";
import { messages } from "./messages";
import { cardKey, type Outcome } from "./outcome";

// A name beancount takes for a category. The server checks it again.
const CATEGORY_NAME = /^(Expenses|Income)(:[\p{Lu}\p{Nd}][\p{L}\p{Nd}-]*)+$/u;
const CARD_KEYS: [string, string][] = [
  ["↵ 1 2 3", messages.keys.pick],
  ["s", messages.keys.skip],
  ["n", messages.keys.note],
  ["o", messages.keys.split],
  ["/", messages.keys.search],
  ["u", messages.keys.undo],
];
const LIMIT = 30;
const NEW_ID = "new-category";

/** Completes `query` to the deepest account level that all its matches share. */
function complete(query: string, accounts: string[]): string {
  // Each typed level starts a level, in any case: "e:te" finds "Expenses:Telecom".
  const typed = query.toLowerCase().split(":");
  const split = accounts.map((account) => account.split(":"));
  // Matches from the root first, else from the shallowest level: "tel" finds
  // "Expenses:Telecom".
  const matchesAt = (depth: number) =>
    split.filter(
      (levels) =>
        levels.length >= depth + typed.length &&
        typed.every((t, i) => levels[depth + i].toLowerCase().startsWith(t)),
    );
  const maxDepth = Math.max(0, ...split.map((levels) => levels.length));
  let depth = 0;
  while (depth < maxDepth && !matchesAt(depth).length) depth++;
  const matches = matchesAt(depth);
  if (!matches.length) return query;
  const end = depth + typed.length;
  const heads = matches.map((levels) => levels.slice(0, end).join(":"));
  if (heads.every((head) => head === heads[0])) {
    return matches.some((levels) => levels.length > end) ? `${heads[0]}:` : heads[0];
  }
  let prefix = heads[0];
  for (const head of heads) while (!head.startsWith(prefix)) prefix = prefix.slice(0, -1);
  // A prefix that ends before the last typed level would drop what was typed.
  if (prefix.split(":").length < end) return query;
  return prefix.length > query.length ? prefix : query;
}

/** A card of one row, with that row's own choices. */
function rowCard(card: Card, i: number): Card {
  const row = card.rows[i];
  return { choices: row.choices, payee: card.payee, rows: [row], sure: false };
}

function rowCount(cards: Card[], outcomes: Record<string, Outcome>, kind: "answered" | "skipped") {
  return cards
    .filter((card) => {
      const outcome = outcomes[cardKey(card)];
      return outcome && (outcome === "skipped") === (kind === "skipped");
    })
    .reduce((sum, card) => sum + card.rows.length, 0);
}

export function Review({ review }: { review: ReviewData }) {
  // The sure cards show as one list first, the other cards follow one by one.
  const [sure, setSure] = useState(() => review.cards.filter((c) => c.sure));
  const [cards, setCards] = useState(() => review.cards.filter((c) => !c.sure));
  // The rows accepted from the sure list.
  const [accepted, setAccepted] = useState(0);
  const [categories, setCategories] = useState(review.categories);
  const [query, setQuery] = useState("");
  const [pos, setPos] = useState(0);
  // The positions left, for going back.
  const [history, setHistory] = useState<number[]>([]);
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [noting, setNoting] = useState(false);
  const save = useMutation({
    mutationFn: saveAnswers,
    onError: (error) =>
      notifications.show({ color: "red", message: String(error), title: messages.saveFailed }),
  });
  const add = useMutation({
    mutationFn: addCategory,
    onError: (error) =>
      notifications.show({ color: "red", message: String(error), title: messages.addFailed }),
  });
  const note = useMutation({
    mutationFn: ({ importIds, text }: { importIds: string[]; text: string }) =>
      saveNote(importIds, text),
    onError: (error) =>
      notifications.show({ color: "red", message: String(error), title: messages.saveNoteFailed }),
  });
  const card: Card | undefined = cards[pos];

  const goTo = (next: number) => {
    setHistory((h) => [...h, pos]);
    setPos(next);
  };
  const settle = (outcome: Outcome) => {
    if (!card) return;
    setOutcomes((o) => ({ ...o, [cardKey(card)]: outcome }));
    goTo(pos + 1);
  };
  const answer = (account: string) => {
    if (!card || save.isPending) return;
    const answers = Object.fromEntries(card.rows.map((row) => [row.import_id, account]));
    save.mutate(answers, { onSuccess: () => settle({ account }) });
  };
  const create = (account: string) => {
    if (!card || add.isPending) return;
    add.mutate(account, {
      onSuccess: () => {
        setCategories((c) => [...c, account].sort());
        answer(account);
      },
    });
  };
  const skipWithNote = (text: string) => {
    if (!card) return;
    const importIds = card.rows.map((row) => row.import_id);
    note.mutate(
      { importIds, text },
      {
        onSuccess: () => {
          setNoting(false);
          settle("skipped");
        },
      },
    );
  };
  const pick = (i: number) => card?.choices[i] && answer(card.choices[i].account);
  const split = () => {
    if (!card || card.rows.length < 2) return;
    const singles = card.rows.map((_, i) => rowCard(card, i));
    setCards((c) => [...c.slice(0, pos), ...singles, ...c.slice(pos + 1)]);
  };
  const accept = (ticked: Set<string>) => {
    if (save.isPending) return;
    const rows = sure.flatMap((c) => c.rows).filter((row) => ticked.has(row.import_id));
    const singles = sure.flatMap((c) =>
      c.rows.flatMap((row, i) => (ticked.has(row.import_id) ? [] : [rowCard(c, i)])),
    );
    const next = () => {
      setAccepted(rows.length);
      setCards((c) => [...singles, ...c]);
      setSure([]);
    };
    if (!rows.length) return next();
    const answers = Object.fromEntries(rows.map((row) => [row.import_id, row.choices[0].account]));
    save.mutate(answers, { onSuccess: next });
  };
  const back = () => {
    if (!history.length) return;
    setPos(history[history.length - 1]);
    setHistory((h) => h.slice(0, -1));
  };

  // Off while the note dialog is open, so its keys never reach the card.
  useHotkeys(noting || sure.length ? [] : [
    ["1", () => pick(0)],
    ["Enter", () => pick(0)],
    ["2", () => pick(1)],
    ["3", () => pick(2)],
    ["s", () => !save.isPending && !note.isPending && settle("skipped")],
    ["n", () => card && setNoting(true)],
    ["o", split],
    ["u", back],
  ]);

  const actions: SpotlightActionData[] = categories.map((account) => ({
    id: account,
    label: account,
    onClick: () => answer(account),
  }));
  const name = query.trim();
  if (CATEGORY_NAME.test(name) && !categories.includes(name)) {
    actions.push({ id: NEW_ID, label: messages.create(name), onClick: () => create(name) });
  }

  const total = [...sure, ...cards].reduce((sum, c) => sum + c.rows.length, accepted);
  const answered = rowCount(cards, outcomes, "answered") + accepted;
  const reviewed = cards.length > 0 || accepted > 0;
  return (
    <Stack gap="xl">
      <ProgressHeader
        answered={answered}
        keys={sure.length ? [] : CARD_KEYS}
        skipped={rowCount(cards, outcomes, "skipped")}
        total={total}
        year={review.year}
      />
      {sure.length ? (
        <SureList busy={save.isPending} cards={sure} onAccept={accept} />
      ) : card ? (
        <CurrentCard
          busy={save.isPending}
          card={card}
          onPick={answer}
          outcome={outcomes[cardKey(card)]}
        />
      ) : (
        <Paper withBorder p="xl" radius="lg">
          <Title order={2}>{reviewed ? messages.doneTitle : messages.emptyTitle}</Title>
          <Text c="dimmed" mt="xs">
            {reviewed ? messages.doneText(answered) : messages.emptyText}
          </Text>
          {history.length > 0 && (
            <Button variant="light" mt="md" onClick={back}>
              {messages.keys.undo}
            </Button>
          )}
        </Paper>
      )}
      <NoteDialog
        busy={note.isPending}
        onClose={() => setNoting(false)}
        onSave={skipWithNote}
        opened={noting}
      />
      {!sure.length && (
        <Upcoming
          key={pos}
          cards={cards.map((c, index) => ({ card: c, index })).slice(pos + 1)}
          onOpen={goTo}
          outcomes={outcomes}
        />
      )}
      <Spotlight
        actions={actions}
        disabled={!card || sure.length > 0}
        // The actions hold no groups. Extended match: Each word matches alone.
        // A new category comes last, so Enter on a partial name picks a match.
        filter={(q, all) => {
          const items = all as SpotlightActionData[];
          const matches = new Fzf(
            items.filter((action) => action.id !== NEW_ID),
            { match: extendedMatch, selector: (action) => action.label ?? "" },
          )
            .find(q)
            .map((result) => result.item);
          return [...matches.slice(0, LIMIT - 1), ...items.filter((a) => a.id === NEW_ID)];
        }}
        highlightQuery
        limit={LIMIT}
        nothingFound={messages.nothingFound}
        onQueryChange={setQuery}
        query={query}
        scrollable
        searchProps={{
          onKeyDown: (event) => {
            if (event.key !== "Tab" || event.shiftKey) return;
            event.preventDefault();
            // Through the input's own event, so Spotlight selects the top match again.
            const input = event.currentTarget;
            const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
            setValue?.call(input, complete(query, categories));
            input.dispatchEvent(new Event("input", { bubbles: true }));
          },
          placeholder: messages.searchPlaceholder,
        }}
        shortcut="/"
      />
    </Stack>
  );
}
