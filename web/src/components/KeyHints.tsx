import { Group, Kbd, Text } from "@mantine/core";

/** A line of key hints. Each entry holds the space-separated keys and their label. */
export function KeyHints({ keys }: { keys: [string, string][] }) {
  return (
    <Group gap="md">
      {keys.map(([shortcut, label]) => (
        <Text key={shortcut} size="xs" c="dimmed">
          {shortcut.split(" ").map((key) => (
            <Kbd key={key} size="xs" mr={2}>
              {key}
            </Kbd>
          ))}{" "}
          {label}
        </Text>
      ))}
    </Group>
  );
}
