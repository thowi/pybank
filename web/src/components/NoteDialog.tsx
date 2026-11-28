import { Button, Group, Modal, Stack, Textarea } from "@mantine/core";
import { useState } from "react";
import { messages } from "../messages";

interface Props {
  busy: boolean;
  onClose: () => void;
  onSave: (note: string) => void;
  opened: boolean;
}

export function NoteDialog({ busy, onClose, onSave, opened }: Props) {
  const [note, setNote] = useState("");
  const save = () => note.trim() && !busy && onSave(note.trim());
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      onExitTransitionEnd={() => setNote("")}
      title={messages.note}
    >
      <Stack>
        <Textarea
          autosize
          data-autofocus
          minRows={3}
          onChange={(event) => setNote(event.currentTarget.value)}
          // Enter saves, Shift+Enter starts a new line. Enter also ends an IME composition.
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
            event.preventDefault();
            save();
          }}
          placeholder={messages.notePlaceholder}
          value={note}
        />
        <Group justify="flex-end">
          <Button disabled={!note.trim()} loading={busy} onClick={save}>
            {messages.note}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
