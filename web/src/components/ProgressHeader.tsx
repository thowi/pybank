import { Group, Progress, Stack, Text, Title } from "@mantine/core";
import { messages } from "../messages";
import { KeyHints } from "./KeyHints";

interface Props {
  answered: number;
  // The keys that work now, for the hint line.
  keys: [string, string][];
  skipped: number;
  total: number;
  year: number | null;
}

export function ProgressHeader({ answered, keys, skipped, total, year }: Props) {
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
      {keys.length > 0 && <KeyHints keys={keys} />}
    </Stack>
  );
}
