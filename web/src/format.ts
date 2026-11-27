/** Formats a decimal amount string in its currency, or plainly if no ISO code. */
export function formatAmount(amount: string, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { currency, style: "currency" }).format(
      Number(amount),
    );
  } catch {
    return `${amount} ${currency}`;
  }
}

/** Splits an account into its parents and its last segment. */
export function splitAccount(account: string): { leaf: string; parents: string[] } {
  const parts = account.split(":");
  return { leaf: parts[parts.length - 1], parents: parts.slice(0, -1) };
}
