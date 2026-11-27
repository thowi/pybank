import { Badge, Group, Paper, Stack, Table, Text, Title } from "@mantine/core";
import type { Card } from "../api";
import { formatAmount } from "../format";
import { messages } from "../messages";
import type { Outcome } from "../outcome";
import { AccountName } from "./AccountName";
import { Choices } from "./Choices";

// More rows than this only make the card long. The choices matter more.
const SHOWN_ROWS = 8;

interface Props {
  busy: boolean;
  card: Card;
  onPick: (account: string) => void;
  outcome: Outcome | undefined;
}

export function CurrentCard({ busy, card, onPick, outcome }: Props) {
  const hidden = card.rows.length - SHOWN_ROWS;
  return (
    <Paper withBorder shadow="md" p="lg" radius="lg">
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={2} tt="capitalize">
            {card.payee}
          </Title>
          <Group gap="xs">
            {outcome && (
              <Badge color={outcome === "skipped" ? "gray" : "brand"} variant="light">
                {outcome === "skipped" ? messages.skipped : messages.answered(outcome.account)}
              </Badge>
            )}
            {card.sure && <Badge variant="dot">{messages.sure}</Badge>}
            <Badge variant="default">{messages.rows(card.rows.length)}</Badge>
          </Group>
        </Group>
        <Table verticalSpacing={6}>
          <Table.Tbody>
            {card.rows.slice(0, SHOWN_ROWS).map((row) => (
              <Table.Tr key={row.import_id}>
                <Table.Td c="dimmed" style={{ whiteSpace: "nowrap" }}>
                  {row.date}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{[row.payee, row.narration].filter(Boolean).join(" · ")}</Text>
                  <Text size="xs">
                    <AccountName account={row.account} />
                  </Text>
                </Table.Td>
                <Table.Td
                  ta="right"
                  fw={600}
                  c={row.amount.startsWith("-") ? undefined : "brand"}
                  style={{ whiteSpace: "nowrap" }}
                >
                  {formatAmount(row.amount, row.currency)}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {hidden > 0 && (
          <Text size="sm" c="dimmed">
            {messages.more(hidden)}
          </Text>
        )}
        <Choices choices={card.choices} disabled={busy} onPick={onPick} />
      </Stack>
    </Paper>
  );
}
