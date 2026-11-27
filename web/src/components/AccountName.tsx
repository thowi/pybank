import { Text } from "@mantine/core";
import { splitAccount } from "../format";

/** The account's last segment in bold, after its dimmed parents. */
export function AccountName({ account }: { account: string }) {
  const { leaf, parents } = splitAccount(account);
  return (
    <Text component="span" inherit>
      <Text component="span" c="dimmed" inherit>
        {parents.join(" › ")} ›{" "}
      </Text>
      <Text component="span" fw={700} inherit>
        {leaf}
      </Text>
    </Text>
  );
}
