import { Group, Kbd, Progress, Stack, Text, Title } from "@mantine/core";
import { messages } from "../messages";

interface Props {
  answered: number;
  skipped: number;
  total: number;
  year: number | null;
}

const KEYS: [string, string][] = [
  ["↵ 1 2 3", messages.keys.pick],
  ["s", messages.keys.skip],
  ["n", messages.keys.note],
  ["o", messages.keys.split],
  ["/", messages.keys.search],
  ["u", messages.keys.undo],
];

export function ProgressHeader({ answered, skipped, total, year }: Props) {
  const share = (n: number) => (total ? (n / total) * 100 : 0);
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="baseline">
        <Title order={1} size="h3">
          {messages.title(year)}
        </Title>
        <Text size="sm" c="dimmed">
          {messages.progress(answered, skipped, total - answered - skipped, total)}
        </Text>
      </Group>
      <Progress.Root size="lg">
        <Progress.Section value={share(answered)} />
        <Progress.Section value={share(skipped)} color="gray" />
      </Progress.Root>
      <Group gap="md">
        {KEYS.map(([keys, label]) => (
          <Text key={keys} size="xs" c="dimmed">
            {keys.split(" ").map((key) => (
              <Kbd key={key} size="xs" mr={2}>
                {key}
              </Kbd>
            ))}{" "}
            {label}
          </Text>
        ))}
      </Group>
    </Stack>
  );
}
