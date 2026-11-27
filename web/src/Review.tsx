import { Button, Paper, Stack, Text, Title } from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { Spotlight, type SpotlightActionData } from "@mantine/spotlight";
import { useMutation } from "@tanstack/react-query";
import { extendedMatch, Fzf } from "fzf";
import { useState } from "react";
import { type Card, type ReviewData, saveAnswers } from "./api";
import { CurrentCard } from "./components/CurrentCard";
import { ProgressHeader } from "./components/ProgressHeader";
import { Upcoming } from "./components/Upcoming";
import { messages } from "./messages";
import { cardKey, type Outcome } from "./outcome";

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
  const [cards, setCards] = useState(review.cards);
  const [pos, setPos] = useState(0);
  // The positions left, for going back.
  const [history, setHistory] = useState<number[]>([]);
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const save = useMutation({
    mutationFn: saveAnswers,
    onError: (error) =>
      notifications.show({ color: "red", message: String(error), title: messages.saveFailed }),
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
  const pick = (i: number) => card?.choices[i] && answer(card.choices[i].account);
  const split = () => {
    if (!card || card.rows.length < 2) return;
    const singles = card.rows.map((_, i) => rowCard(card, i));
    setCards((c) => [...c.slice(0, pos), ...singles, ...c.slice(pos + 1)]);
  };
  const back = () => {
    if (!history.length) return;
    setPos(history[history.length - 1]);
    setHistory((h) => h.slice(0, -1));
  };

  useHotkeys([
    ["1", () => pick(0)],
    ["2", () => pick(1)],
    ["3", () => pick(2)],
    ["s", () => !save.isPending && settle("skipped")],
    ["n", split],
    ["u", back],
  ]);

  const total = cards.reduce((sum, c) => sum + c.rows.length, 0);
  const answered = rowCount(cards, outcomes, "answered");
  return (
    <Stack gap="xl">
      <ProgressHeader
        answered={answered}
        skipped={rowCount(cards, outcomes, "skipped")}
        total={total}
        year={review.year}
      />
      {card ? (
        <CurrentCard
          busy={save.isPending}
          card={card}
          onPick={answer}
          outcome={outcomes[cardKey(card)]}
        />
      ) : (
        <Paper withBorder p="xl" radius="lg">
          <Title order={2}>{cards.length ? messages.doneTitle : messages.emptyTitle}</Title>
          <Text c="dimmed" mt="xs">
            {cards.length ? messages.doneText(answered) : messages.emptyText}
          </Text>
          {history.length > 0 && (
            <Button variant="light" mt="md" onClick={back}>
              {messages.keys.undo}
            </Button>
          )}
        </Paper>
      )}
      <Upcoming
        key={pos}
        cards={cards.map((c, index) => ({ card: c, index })).slice(pos + 1)}
        onOpen={goTo}
        outcomes={outcomes}
      />
      <Spotlight
        actions={review.categories.map((account) => ({
          id: account,
          label: account,
          onClick: () => answer(account),
        }))}
        disabled={!card}
        // The actions hold no groups. Extended match: Each word matches alone.
        filter={(query, actions) =>
          new Fzf(actions as SpotlightActionData[], {
            match: extendedMatch,
            selector: (action) => action.label ?? "",
          })
            .find(query)
            .map((result) => result.item)
        }
        highlightQuery
        limit={30}
        nothingFound={messages.nothingFound}
        scrollable
        searchProps={{ placeholder: messages.searchPlaceholder }}
        shortcut="/"
      />
    </Stack>
  );
}
