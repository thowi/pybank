import { Group, Kbd, Progress, Stack, Text, UnstyledButton } from "@mantine/core";
import type { Choice } from "../api";
import { AccountName } from "./AccountName";

interface Props {
  choices: Choice[];
  disabled: boolean;
  onPick: (account: string) => void;
}

export function Choices({ choices, disabled, onPick }: Props) {
  return (
    <Stack gap="xs">
      {choices.map((choice, i) => (
        <UnstyledButton
          key={choice.account}
          disabled={disabled}
          onClick={() => onPick(choice.account)}
          p="sm"
          bd="1px solid var(--mantine-color-default-border)"
          bg={i === 0 ? "var(--mantine-primary-color-light)" : undefined}
          style={{ borderRadius: "var(--mantine-radius-md)" }}
        >
          <Group wrap="nowrap">
            <Kbd size="lg">{i + 1}</Kbd>
            <Stack gap={4} style={{ flex: 1 }}>
              <Group justify="space-between" wrap="nowrap">
                <AccountName account={choice.account} />
                <Text size="sm" c="dimmed">
                  {Math.round(choice.probability * 100)}%
                </Text>
              </Group>
              <Progress value={choice.probability * 100} size="xs" />
            </Stack>
          </Group>
        </UnstyledButton>
      ))}
    </Stack>
  );
}
