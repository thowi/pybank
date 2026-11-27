import { Badge, Group, Pagination, Paper, Stack, Text, UnstyledButton } from "@mantine/core";
import { useState } from "react";
import type { Card } from "../api";
import { messages } from "../messages";
import { cardKey, type Outcome } from "../outcome";
import { AccountName } from "./AccountName";

const PAGE_SIZE = 6;

interface Props {
  // The cards after the current one, with their position in the whole queue.
  cards: { card: Card; index: number }[];
  onOpen: (index: number) => void;
  outcomes: Record<string, Outcome>;
}

export function Upcoming({ cards, onOpen, outcomes }: Props) {
  const [page, setPage] = useState(1);
  const pages = Math.ceil(cards.length / PAGE_SIZE);
  if (!cards.length) return null;
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600} c="dimmed" tt="uppercase">
        {messages.upNext}
      </Text>
      {cards.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map(({ card, index }) => {
        const top = card.choices[0];
        const outcome = outcomes[cardKey(card)];
        return (
          <UnstyledButton key={cardKey(card)} onClick={() => onOpen(index)}>
            <Paper withBorder p="sm" radius="md" opacity={outcome ? 0.6 : 1}>
              <Group justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap">
                  <Text fw={600} tt="capitalize" lineClamp={1}>
                    {card.payee}
                  </Text>
                  <Badge variant="default" size="sm">
                    {messages.rows(card.rows.length)}
                  </Badge>
                </Group>
                <Text size="sm" lineClamp={1}>
                  <AccountName account={top.account} />{" "}
                  <Text component="span" c="dimmed" inherit>
                    {Math.round(top.probability * 100)}%
                  </Text>
                </Text>
              </Group>
            </Paper>
          </UnstyledButton>
        );
      })}
      {pages > 1 && <Pagination total={pages} value={page} onChange={setPage} size="sm" />}
    </Stack>
  );
}
