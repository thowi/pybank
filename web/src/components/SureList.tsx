import { Badge, Button, Checkbox, Group, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import type { Card } from "../api";
import { formatAmount } from "../format";
import { messages } from "../messages";
import { AccountName } from "./AccountName";
import { KeyHints } from "./KeyHints";

const KEYS: [string, string][] = [
  ["j k ↑ ↓", messages.keys.move],
  ["␣", messages.keys.tick],
  ["↵", messages.keys.accept],
];
// The focus moves by these keys, between the rows. Tab reaches the button.
const STEPS: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, j: 1, k: -1 };

interface Props {
  busy: boolean;
  // The sure cards. Each row gets its own line.
  cards: Card[];
  onAccept: (ticked: Set<string>) => void;
}

export function SureList({ busy, cards, onAccept }: Props) {
  // By top account, so one category forms a block and an outlier stands out.
  const rows = cards
    .flatMap((card) => card.rows)
    .sort(
      (a, b) =>
        a.choices[0].account.localeCompare(b.choices[0].account) ||
        a.payee.localeCompare(b.payee) ||
        a.date.localeCompare(b.date),
    );
  const [unticked, setUnticked] = useState<Set<string>>(new Set());
  const [focused, setFocused] = useState(-1);
  // The row checkboxes, then the accept button, in focus order.
  const items = useRef<(HTMLElement | null)[]>([]);
  const ticked = new Set(rows.map((row) => row.import_id).filter((id) => !unticked.has(id)));

  useEffect(() => items.current[0]?.focus(), []);

  const toggle = (id: string) =>
    setUnticked((u) => {
      const next = new Set(u);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const move = (step: number) => {
    const all = items.current;
    const at = all.indexOf(document.activeElement as HTMLElement);
    // Stops at the last row, so space on the button never accepts by mistake.
    const next = all[Math.min(Math.max(at + step, 0), rows.length - 1)];
    next?.focus();
    next?.scrollIntoView({ block: "nearest" });
  };

  return (
    <Paper
      withBorder
      shadow="md"
      p="lg"
      radius="lg"
      bd="1px solid var(--mantine-primary-color-filled)"
      onFocus={(event) => setFocused(items.current.indexOf(event.target))}
      onKeyDown={(event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        if (event.key === "Enter") {
          event.preventDefault();
          if (!busy) onAccept(ticked);
          return;
        }
        const step = STEPS[event.key];
        if (!step) return;
        event.preventDefault();
        move(step);
      }}
    >
      <Stack gap="md">
        <Stack gap="xs">
          <Group gap="xs">
            <Badge variant="filled">{messages.sure}</Badge>
            <Title order={2}>{messages.sureTitle}</Title>
          </Group>
          <Text c="dimmed">{messages.sureText(rows.length)}</Text>
          <KeyHints keys={KEYS} />
        </Stack>
        <Table verticalSpacing={4}>
          <Table.Tbody>
            {rows.map((row, i) => {
              const top = row.choices[0];
              const text = [row.payee, row.narration].filter(Boolean).join(" · ");
              return (
                <Table.Tr
                  key={row.import_id}
                  bg={focused === i ? "var(--mantine-primary-color-light)" : undefined}
                  opacity={unticked.has(row.import_id) ? 0.5 : 1}
                  onClick={() => {
                    toggle(row.import_id);
                    items.current[i]?.focus();
                  }}
                  style={{ cursor: "pointer" }}
                >
                  <Table.Td w={1}>
                    <Checkbox
                      ref={(el) => {
                        items.current[i] = el;
                      }}
                      aria-label={text}
                      checked={!unticked.has(row.import_id)}
                      // The row's own click toggles, so the box's click must not reach it.
                      onClick={(event) => event.stopPropagation()}
                      onChange={() => toggle(row.import_id)}
                    />
                  </Table.Td>
                  <Table.Td c="dimmed" style={{ whiteSpace: "nowrap" }}>
                    {row.date}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={1}>
                      {text}
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
                  <Table.Td>
                    <Text size="sm" lineClamp={1}>
                      <AccountName account={top.account} />{" "}
                      <Text component="span" c="dimmed" inherit>
                        {Math.round(top.probability * 100)}%
                      </Text>
                    </Text>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
        <Group justify="flex-end">
          <Button
            ref={(el) => {
              items.current[rows.length] = el;
            }}
            onClick={() => !busy && onAccept(ticked)}
          >
            {messages.accept(ticked.size)}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
