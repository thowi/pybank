import { Badge, Group, Mark, Paper, Stack, Table, Text, Title } from "@mantine/core";
import type { Card } from "../api";
import { formatAmount } from "../format";
import { messages } from "../messages";
import type { Outcome } from "../outcome";
import { AccountName } from "./AccountName";
import { Choices } from "./Choices";

// More rows than this only make a sure card long. The choices matter more.
const SHOWN_ROWS = 8;

/** Marks the words of `text` that are missing from `common`. */
function Marked({ common, text }: { common: Set<string>; text: string }) {
  // Splits around the spaces and keeps them, so the text reads as before.
  return text
    .split(/(\s+)/)
    .map((part, i) =>
      common.has(part) || part === "·" || !part.trim() ? part : <Mark key={i}>{part}</Mark>,
    );
}

interface Props {
  busy: boolean;
  card: Card;
  onPick: (account: string) => void;
  outcome: Outcome | undefined;
}

export function CurrentCard({ busy, card, onPick, outcome }: Props) {
  const texts = card.rows.map((row) => [row.payee, row.narration].filter(Boolean).join(" · "));
  const [first, ...rest] = texts.map((text) => new Set(text.split(/\s+/)));
  const common = new Set([...first].filter((word) => rest.every((words) => words.has(word))));
  const amountsDiffer = new Set(card.rows.map((row) => Number(row.amount))).size > 1;
  const choicesDiffer = new Set(card.rows.map((row) => row.choices[0]?.account)).size > 1;
  // An unsure card shows every row, so each can be checked.
  const shown = card.sure ? card.rows.slice(0, SHOWN_ROWS) : card.rows;
  const hidden = card.rows.length - shown.length;
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
            {choicesDiffer && (
              <Badge color="yellow" variant="light">
                {messages.choicesDiffer}
              </Badge>
            )}
            <Badge variant="default">{messages.rows(card.rows.length)}</Badge>
          </Group>
        </Group>
        <Table verticalSpacing={6}>
          <Table.Tbody>
            {shown.map((row, i) => (
              <Table.Tr key={row.import_id}>
                <Table.Td c="dimmed" style={{ whiteSpace: "nowrap" }}>
                  {row.date}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    <Marked common={common} text={texts[i]} />
                  </Text>
                  <Text size="xs">
                    <AccountName account={row.account} />
                  </Text>
                  {choicesDiffer && row.choices[0] && (
                    <Text size="xs" c="dimmed">
                      {messages.rowChoice(Math.round(row.choices[0].probability * 100))}{" "}
                      <AccountName account={row.choices[0].account} />
                    </Text>
                  )}
                </Table.Td>
                <Table.Td
                  ta="right"
                  fw={600}
                  c={row.amount.startsWith("-") ? undefined : "brand"}
                  style={{ whiteSpace: "nowrap" }}
                >
                  {amountsDiffer ? (
                    <Mark>{formatAmount(row.amount, row.currency)}</Mark>
                  ) : (
                    formatAmount(row.amount, row.currency)
                  )}
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
